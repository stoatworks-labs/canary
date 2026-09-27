#!/usr/bin/env python3
"""
End-to-end: an R1-shaped client -> the shipping bridge C -> a simulated amp,
and the amp's answer all the way back.

This is the test the project could not run before. tools/r70_emu.py proved the
protocol against real R1, but it is a Python re-implementation; the C that goes
on the board had only ever been checked one component at a time. And nothing
had ever exercised the CAN return path, because that needed a bus.

Chain under test:

    this script  --TCP 30000-->  canaryd (components/bridge + rmbcp + dbcan)
                                       |
                                    vcan hub
                                       |
                                  vamp.py (VirtualDevice)

A pass means the bridge parsed an RMBCP CAN frame, put it on the bus with the
right identifier, and re-encoded the device's answer back onto the socket. It
does NOT mean the payload is meaningful — see the scope warning in vamp.py.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOSTSIM = HERE.parent
ROOT = HOSTSIM.parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import rmbcp  # noqa: E402
from rmbcp import OBJ_DEVICE_PROCESS_DATA, OBJ_PRIMARY_MASTER, dbcan_id  # noqa: E402

VCAN_PORT = int(os.environ.get("CANARY_VCAN_PORT", "35010"))
TCP_PORT = int(os.environ.get("CANARY_TCP_PORT", "30010"))

PASSED = 0
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print(f"[  ok  ] {name}  {detail}")
    else:
        FAILED += 1
        print(f"[ FAIL ] {name}  {detail}")


def wait_for_line(proc: subprocess.Popen, needle: str, timeout: float = 5.0) -> bool:
    """Wait for a known-good line on stdout rather than sleeping and hoping."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        if needle in line:
            return True
    return False


def main() -> int:
    procs: list[subprocess.Popen] = []
    env = dict(os.environ, CANARY_VCAN_PORT=str(VCAN_PORT))

    try:
        hub = subprocess.Popen(
            [sys.executable, str(ROOT / "tools" / "vcan.py"), "hub",
             "--port", str(VCAN_PORT)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
        procs.append(hub)
        check("hub.started", wait_for_line(hub, "vcan hub"), f"port {VCAN_PORT}")

        amp_addr = "1.2"
        amp = subprocess.Popen(
            [sys.executable, str(ROOT / "tools" / "vamp.py"), amp_addr,
             "--port", str(VCAN_PORT), "--reply", "a1b2c3"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
        procs.append(amp)
        check("amp.started", wait_for_line(amp, "vamp:"), f"device {amp_addr}")

        daemon = subprocess.Popen(
            [str(HOSTSIM / "canaryd"), "--ip", "127.0.0.1",
             "--port", str(TCP_PORT)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        procs.append(daemon)
        check("bridge.started", wait_for_line(daemon, "canaryd ready"),
              f"tcp {TCP_PORT}")

        sock = socket.create_connection(("127.0.0.1", TCP_PORT), timeout=5)
        sock.settimeout(5)
        check("bridge.connected", True, f"127.0.0.1:{TCP_PORT}")

        # Address the amp exactly as a dbCAN master would.
        request_id = dbcan_id(OBJ_PRIMARY_MASTER, 1, 2)
        payload = bytes.fromhex("0102030405")
        sock.sendall(rmbcp.encode_can(request_id, payload))

        decoder = rmbcp.Decoder()
        expected_id = dbcan_id(OBJ_DEVICE_PROCESS_DATA, 1, 2)
        reply = None
        deadline = time.time() + 5
        while time.time() < deadline and reply is None:
            try:
                chunk = sock.recv(512)
            except socket.timeout:
                break
            if not chunk:
                break
            for frame in decoder.feed(chunk):
                if frame.is_can:
                    reply = frame.as_can()
                    break

        check("can.reply-returned", reply is not None,
              "the amp's frame came back over TCP" if reply
              else "no CAN frame arrived within 5 s")
        if reply is not None:
            reply_id, reply_payload, _ts = reply
            check("can.reply-identifier", reply_id == expected_id,
                  f"{reply_id:#05x}, expected {expected_id:#05x} "
                  f"(class 2 = process data from device)")
            check("can.reply-payload", reply_payload == bytes.fromhex("a1b2c3"),
                  reply_payload.hex(" "))

        # The bridge must survive traffic addressed to nobody.
        sock.sendall(rmbcp.encode_can(dbcan_id(OBJ_PRIMARY_MASTER, 7, 63), b"\x00"))
        sock.sendall(rmbcp.encode(rmbcp.CMD_DEVICE_ID))
        deadline = time.time() + 5
        alive = False
        while time.time() < deadline and not alive:
            try:
                chunk = sock.recv(512)
            except socket.timeout:
                break
            if not chunk:
                break
            for frame in decoder.feed(chunk):
                if frame.command == rmbcp.CMD_DEVICE_ID:
                    alive = True
                    break
        check("bridge.alive-after-unaddressed-frame", alive,
              "still answering Device ID")

        sock.close()
    finally:
        for proc in reversed(procs):
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()

    print(f"\n{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
