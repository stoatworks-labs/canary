#!/usr/bin/env python3
"""
Adversarial soak against the shipping bridge C.

The unit tests feed the decoder well-formed input and check the answer. This
feeds it what a show network actually delivers — split frames, garbage, floods,
half-open sockets, a second master barging in — and checks the one property
that matters at 2 a.m. in a venue: the bridge is still answering afterwards.

The specific cases are not invented. Each one is a way this bridge is already
known to be able to fail:

  - `silence is load-bearing`: tools/board_test.py records that when the
    emulator started answering 0x44/0xA4, R1 stopped progressing past
    initialisation and looped on reset-device. A regression there is invisible
    except as "R1 mysteriously will not connect".
  - `one master at a time`: bridge.c closes a second connection while one is
    held. If it ever stopped doing that, two R1s would interleave frames onto
    an amplifier bus.
  - `Length=0`: found by hostsim/fuzz — see the regression vectors in
    components/rmbcp/test.
  - fragmentation: the decoder is correct on whole frames and had to be made
    correct across arbitrary splits; recv() chooses those splits, not us.

Run: firmware/hostsim/test/run_tests.sh (builds the daemon first).
"""

from __future__ import annotations

import os
import random
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

TCP_PORT = int(os.environ.get("DBCANARY_TCP_PORT", "30020"))
VCAN_PORT = int(os.environ.get("DBCANARY_VCAN_PORT", "35020"))

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


def connect() -> socket.socket:
    sock = socket.create_connection(("127.0.0.1", TCP_PORT), timeout=5)
    sock.settimeout(5)
    return sock


def ask_device_id(sock: socket.socket, timeout: float = 3.0) -> bool:
    """Send Device ID and wait for the answer. The liveness probe."""
    sock.sendall(rmbcp.encode(rmbcp.CMD_DEVICE_ID))
    decoder = rmbcp.Decoder()
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            chunk = sock.recv(512)
        except socket.timeout:
            return False
        if not chunk:
            return False
        for frame in decoder.feed(chunk):
            if frame.command == rmbcp.CMD_DEVICE_ID:
                return True
    return False


def drain(sock: socket.socket, seconds: float = 0.3) -> bytes:
    """Read whatever is pending, so a later probe is not confused by it."""
    sock.settimeout(seconds)
    out = b""
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            out += chunk
    except (socket.timeout, OSError):
        pass
    sock.settimeout(5)
    return out


def main() -> int:
    rng = random.Random(20260731)  # deterministic: a failure is reproducible
    env = dict(os.environ, DBCANARY_VCAN_PORT=str(VCAN_PORT))
    daemon = subprocess.Popen(
        [str(HOSTSIM / "dbcanaryd"), "--ip", "127.0.0.1", "--port", str(TCP_PORT)],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)

    try:
        ready = False
        deadline = time.time() + 5
        while time.time() < deadline:
            line = daemon.stdout.readline()
            if not line or "dbcanaryd ready" in line:
                ready = "dbcanaryd ready" in (line or "")
                break
        check("daemon.ready", ready, f"tcp {TCP_PORT}")
        if not ready:
            return 1

        # --- 1. fragmentation: every frame split at every possible boundary --
        sock = connect()
        good = rmbcp.encode(rmbcp.CMD_DEVICE_ID)
        worst_split_ok = True
        for cut in range(1, len(good)):
            sock.sendall(good[:cut])
            time.sleep(0.005)  # force a separate recv() on the far side
            sock.sendall(good[cut:])
            if not ask_device_id(sock):
                worst_split_ok = False
                break
            drain(sock, 0.05)
        check("fragmentation.every-boundary", worst_split_ok,
              f"{len(good) - 1} split points, one recv() each")

        # --- 2. the hostile frame the fuzzer found ---------------------------
        sock.sendall(bytes([rmbcp.SOF, 0x00, 0x40, rmbcp.EOF]))
        check("hostile.length-zero", ask_device_id(sock),
              "still answering after Length=0")
        drain(sock)

        # --- 3. garbage flood, then a real frame -----------------------------
        for _ in range(200):
            noise = bytes(rng.randrange(256) for _ in range(rng.randrange(1, 300)))
            sock.sendall(noise)
        drain(sock, 0.5)
        check("hostile.garbage-flood", ask_device_id(sock),
              "60 KB of noise, then resynchronised")
        drain(sock)

        # --- 4. a declared length that never arrives -------------------------
        # The decoder must hold this as pending without wedging on it.
        sock.sendall(bytes([rmbcp.SOF, 0xFF, 0x40]) + b"\x00" * 10)
        check("hostile.truncated-max-length", ask_device_id(sock),
              "a 255-byte frame that stops after 10")
        drain(sock)

        # --- 5. the silences must stay silent --------------------------------
        # If these ever get answered, R1 loops at initialisation forever.
        # Raw opcodes, as tools/board_test.py writes them: tools/rmbcp.py has no
        # constants for the two commands it deliberately never answers.
        for name, cmd in (("interfaces-version", 0x44),
                          ("baud-calc-interval", 0xA4)):
            drain(sock)
            sock.sendall(rmbcp.encode(cmd))
            time.sleep(0.3)
            replied = drain(sock, 0.3)
            check(f"silence.{name}", replied == b"",
                  "no reply, as R1 requires" if replied == b""
                  else f"answered with {replied.hex()}")

        # --- 6. one master at a time -----------------------------------------
        second = None
        try:
            second = connect()
            time.sleep(0.3)
            # bridge.c close()s the second socket while one is held.
            second.settimeout(1.0)
            try:
                rejected = second.recv(16) == b""
            except (socket.timeout, ConnectionResetError):
                rejected = True
        except OSError:
            rejected = True
        finally:
            if second is not None:
                second.close()
        check("session.one-master-at-a-time", rejected,
              "second connection dropped while the first is held")
        check("session.first-survives-the-second", ask_device_id(sock),
              "original session unaffected")

        # --- 7. abrupt disconnects, repeatedly -------------------------------
        sock.close()
        reconnects_ok = True
        for i in range(25):
            try:
                s = connect()
                # Half a frame, then vanish — the worst case for a stream
                # decoder that keeps per-connection state.
                s.sendall(good[:3])
                s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                             __import__("struct").pack("ii", 1, 0))  # RST
                s.close()
            except OSError:
                reconnects_ok = False
                break
            time.sleep(0.02)
        check("session.reset-mid-frame", reconnects_ok,
              "25 connections killed mid-frame with RST")

        final = connect()
        check("session.alive-after-soak", ask_device_id(final),
              "bridge still serving after everything above")
        check("daemon.did-not-crash", daemon.poll() is None,
              "process alive" if daemon.poll() is None
              else f"exited with {daemon.poll()}")
        final.close()

    finally:
        daemon.terminate()
        try:
            daemon.wait(timeout=3)
        except subprocess.TimeoutExpired:
            daemon.kill()

    print(f"\n{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
