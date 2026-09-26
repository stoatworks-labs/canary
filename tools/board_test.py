#!/usr/bin/env python3
"""
dbCANary board test — the acceptance runner for a physical unit.

One command that exercises everything a dbCANary board is supposed to do and
writes a parametric test record keyed to a serial number:

    tools/board_test.py --serial-number 0001 --port /dev/cu.usbmodem101

It has five stages. Each is independent and can be skipped, because during
bring-up you rarely have all five working at once and a runner that refuses to
report anything until everything passes is useless on a bench.

  console   Drive the board's own self-test over USB and read its verdicts.
            Needs the SELF-TEST firmware build (idf.py build -DDBCANARY_SELFTEST=1)
            and pyserial. This is the only stage that sees inside the board.

  discover  Send R1's real discovery probe on UDP 33333 and check the answer.
            The probe is a byte-exact capture of R1 V3.46, so a pass here means
            R1 will list the board, not that our own decoder likes our own
            encoder.

  rmbcp     Connect on TCP 30000 and walk the command set, including the two
            commands that must NOT be answered. That silence is load-bearing:
            when the emulator started replying to 0x44 and 0xA4, R1 stopped
            progressing past initialisation and looped on reset-device. A
            regression there is invisible except as "R1 mysteriously will not
            connect", so it is tested explicitly.

  can       Send a CAN frame through the bridge and read it off the wire with
            an isolated USB-CAN adapter, and back again. Needs python-can and
            an ISOLATED adapter - see the warning in run_can().

  record    Write the whole thing to JSON, so a board's history is a file and
            not a memory.

Everything except `console` and `can` runs against tools/r70_emu.py with
--simulate, which means the runner itself is testable today, with no hardware:

    tools/board_test.py --simulate

That is what tools/test_board_test.py does in CI.

Exit status is 0 only if no check FAILED. SKIP is not a failure - it is the
runner saying it could not look.
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import r70_ddt
import rmbcp

HERE = Path(__file__).resolve().parent

DISCOVERY_PORT = 33333
DATA_PORT = 30000

# Byte-exact capture of R1 V3.46 scanning for interfaces (see
# tools/test_r70_ddt.py). Sending R1's own bytes is the whole point: it removes
# any chance that the board passes our probe and fails the real one.
R1_PROBE = bytes.fromhex("02008001" + "00" * 14 + "52373020" + "00" * 46)

PASS, FAIL, SKIP, INFO = "PASS", "FAIL", "SKIP", "INFO"


@dataclass
class Check:
    name: str
    verdict: str
    detail: str = ""
    stage: str = ""


@dataclass
class Run:
    checks: list = field(default_factory=list)

    def add(self, stage: str, name: str, verdict: str, detail: str = "") -> Check:
        c = Check(name=name, verdict=verdict, detail=detail, stage=stage)
        self.checks.append(c)
        symbol = {PASS: "  ok  ", FAIL: " FAIL ", SKIP: " skip ", INFO: " info "}[verdict]
        print(f"[{symbol}] {stage}.{name}  {detail}")
        return c

    def expect(self, stage: str, name: str, ok: bool, detail: str = "") -> bool:
        self.add(stage, name, PASS if ok else FAIL, detail)
        return ok

    @property
    def failed(self) -> int:
        return sum(1 for c in self.checks if c.verdict == FAIL)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.verdict == PASS)

    @property
    def skipped(self) -> int:
        return sum(1 for c in self.checks if c.verdict == SKIP)


# ===========================================================================
# console — the board's own self-test, over USB
# ===========================================================================
RESULT_RE = re.compile(r"^RESULT\s+(\S+)\s+(PASS|FAIL|SKIP|INFO)\s*(.*)$")
END_RE = re.compile(r"^SELFTEST-END\s+pass=(\d+)\s+fail=(\d+)\s+skip=(\d+)\s+info=(\d+)")


def parse_selftest(text: str) -> tuple[list, dict, dict]:
    """Pull RESULT lines, the SELFTEST-END tally and the JSON line out of a
    console transcript.

    Written as a pure function on a string, separately from the serial port,
    because the parsing is the part worth testing and the serial port is the
    part that needs hardware. It must survive ESP-IDF log lines interleaved
    with the output, which is the normal case: the logger and printf share one
    UART and neither waits for the other.
    """
    results, tally, blob = [], {}, {}
    for line in text.splitlines():
        line = line.strip()
        m = RESULT_RE.match(line)
        if m:
            results.append({"name": m.group(1), "verdict": m.group(2),
                            "detail": m.group(3).strip()})
            continue
        m = END_RE.match(line)
        if m:
            tally = {"pass": int(m.group(1)), "fail": int(m.group(2)),
                     "skip": int(m.group(3)), "info": int(m.group(4))}
            continue
        if line.startswith("JSON "):
            try:
                blob = json.loads(line[5:])
            except json.JSONDecodeError:
                blob = {"error": "unparseable JSON line"}
    return results, tally, blob


def run_console(run: Run, port: str, baud: int, timeout: float) -> dict:
    stage = "console"
    try:
        import serial  # noqa: PLC0415  - optional dependency
    except ImportError:
        run.add(stage, "available", SKIP,
                "pyserial not installed: pip install pyserial")
        return {}

    try:
        ser = serial.Serial(port, baud, timeout=0.5)
    except Exception as exc:                                  # noqa: BLE001
        run.add(stage, "open", FAIL, f"{port}: {exc}")
        return {}

    with ser:
        time.sleep(0.3)
        ser.reset_input_buffer()
        ser.write(b"\r\nselftest\r\n")
        ser.flush()

        text = ""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            chunk = ser.read(4096)
            if chunk:
                text += chunk.decode("utf-8", "replace")
                # "OK" on its own line is the console's end-of-command marker.
                if END_RE.search(text) and re.search(r"^OK\s*$", text, re.M):
                    break
            elif END_RE.search(text):
                break

    results, tally, blob = parse_selftest(text)

    if not results:
        run.add(stage, "selftest", FAIL,
                "no RESULT lines - is this the self-test build? "
                "(idf.py build -DDBCANARY_SELFTEST=1)")
        return {"transcript": text}

    for r in results:
        run.add(stage, r["name"], r["verdict"], r["detail"])

    if not tally:
        # Without the terminator we cannot tell "all results seen" from "read
        # timed out halfway", and a truncated clean run looks like a pass.
        run.add(stage, "complete", FAIL,
                f"no SELFTEST-END line after {timeout:.0f} s - output may be truncated")
    else:
        run.expect(stage, "complete", tally["fail"] == 0,
                   f"board reports pass={tally['pass']} fail={tally['fail']} "
                   f"skip={tally['skip']} info={tally['info']}")

    return {"transcript": text, "tally": tally, "json": blob}


# ===========================================================================
# discover — UDP 33333, with R1's own probe bytes
# ===========================================================================
def run_discover(run: Run, target: str, port: int, timeout: float) -> str | None:
    """Returns the discovered IP, or None. `target` may be a broadcast address."""
    stage = "discover"
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)

    try:
        sock.sendto(R1_PROBE, (target, port))
    except OSError as exc:
        run.add(stage, "probe", FAIL, f"could not send to {target}:{port}: {exc}")
        sock.close()
        return None

    answers = []
    deadline = time.monotonic() + timeout
    with sock:
        while time.monotonic() < deadline:
            try:
                data, peer = sock.recvfrom(4096)
            except socket.timeout:
                break
            if data == R1_PROBE:
                continue                      # our own broadcast, looped back
            answers.append((data, peer))

    if not answers:
        run.add(stage, "answer", FAIL,
                f"no reply to R1's probe within {timeout:.0f} s - R1 would not list this board")
        return None

    data, peer = answers[0]
    run.add(stage, "answer", PASS, f"{len(data)} bytes from {peer[0]}:{peer[1]}")

    try:
        pkt = r70_ddt.Packet.decode(data)
    except ValueError as exc:
        run.add(stage, "decode", FAIL, f"answer does not decode: {exc}")
        return None

    run.expect(stage, "opcode", pkt.opcode == r70_ddt.OP_ANSWER,
               f"opcode 0x{pkt.opcode:02X}, expected 0x{r70_ddt.OP_ANSWER:02X}")

    # R1 echoes the interface index back to itself; a mismatched one makes the
    # answer land against the wrong adapter in its list.
    run.expect(stage, "interface-index", pkt.interface_index == R1_PROBE[0],
               f"{pkt.interface_index}, probe used {R1_PROBE[0]}")

    # R1 leaves the socket column read-only
    # unless the device advertises at least two sockets. One record is not a
    # protocol error; it is a device R1 cannot fully configure.
    run.expect(stage, "socket-count", len(pkt.records) >= 2,
               f"{len(pkt.records)} socket record(s); R1 needs >= 2 to make the "
               f"socket column editable")

    # R1 discards any record that repeats an earlier
    # (service, protocol, port) triple, so duplicates silently reduce the count.
    triples = [(r.service, r.protocol, r.port) for r in pkt.records]
    run.expect(stage, "socket-uniqueness", len(set(triples)) == len(triples),
               f"{len(triples)} records, {len(set(triples))} distinct - "
               f"R1 drops the repeats")

    for rec in pkt.records:
        run.expect(stage, "record-filter",
                   r70_ddt._valid_combination(rec.service, rec.protocol),
                   f"service={rec.service} protocol={rec.protocol} on port {rec.port}")
        break   # they share a filter verdict; one report is enough

    rec = pkt.records[0]
    run.expect(stage, "tag", rec.tag == r70_ddt.TAG_R70,
               f"{rec.tag!r}, expected {r70_ddt.TAG_R70!r}")
    run.add(stage, "identity", INFO,
            f"host={rec.hostname!r} mac={rec.mac.hex(':')} ip={rec.ip} port={rec.port}")

    # The advertised IP is what R1 will connect to. If it does not match where
    # the datagram came from, R1 lists the board and then cannot reach it -
    # which looks like a firewall problem and is not one.
    run.expect(stage, "advertised-ip", rec.ip == peer[0],
               f"advertises {rec.ip}, answered from {peer[0]}")

    return rec.ip


# ===========================================================================
# rmbcp — TCP 30000
# ===========================================================================
class Session:
    """One RMBCP conversation, with a resynchronising decoder."""

    def __init__(self, host: str, port: int, timeout: float = 3.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        self.dec = rmbcp.Decoder()
        self.pending: list = []

    def close(self) -> None:
        self.sock.close()

    def send(self, command: int, data: bytes = b"") -> None:
        self.sock.sendall(rmbcp.encode(command, data))

    def read_frame(self, timeout: float = 1.5):
        """Next frame, or None if nothing arrives in time."""
        if self.pending:
            return self.pending.pop(0)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.sock.settimeout(max(0.05, deadline - time.monotonic()))
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                return None
            self.pending.extend(self.dec.feed(chunk))
            if self.pending:
                return self.pending.pop(0)
        return None

    def ask(self, command: int, data: bytes = b"", timeout: float = 1.5):
        self.send(command, data)
        return self.read_frame(timeout)


def run_rmbcp(run: Run, host: str, port: int, silence_wait: float) -> None:
    stage = "rmbcp"
    try:
        sess = Session(host, port)
    except OSError as exc:
        run.add(stage, "connect", FAIL, f"{host}:{port}: {exc}")
        return
    run.add(stage, "connect", PASS, f"{host}:{port}")

    try:
        # --- 0x40 Device ID -------------------------------------------------
        f = sess.ask(rmbcp.CMD_DEVICE_ID)
        if f is None:
            run.add(stage, "device-id", FAIL, "no reply to 0x40")
        else:
            ok = f.command == rmbcp.CMD_DEVICE_ID
            # Payload is "<host>-<TRANSPORT>-<port>\0" + 6-byte MAC. R1 shows
            # the string and keys its interface list on the MAC, so a missing
            # NUL or a short MAC means R1 lists a nameless device.
            body = f.data
            nul = body.find(b"\x00")
            ok = ok and nul > 0 and len(body) - nul - 1 == 6
            name = body[:nul].decode("ascii", "replace") if nul > 0 else "<no NUL>"
            mac = body[nul + 1:].hex(":") if nul > 0 else "-"
            run.expect(stage, "device-id", ok,
                       f"cmd=0x{f.command:02X} name={name!r} mac={mac}")

        # --- 0x41 Versions --------------------------------------------------
        f = sess.ask(rmbcp.CMD_VERSION)
        run.expect(stage, "version",
                   f is not None and f.command == rmbcp.CMD_VERSION and len(f.data) == 6,
                   "6 bytes: HW, FW, bootloader" if f else "no reply to 0x41")

        # --- 0x42 Error status ----------------------------------------------
        f = sess.ask(0x42)
        ok = f is not None and f.command == 0x42 and len(f.data) == 2
        run.expect(stage, "error-status", ok and f.data == b"\x00\x00",
                   f"{f.data.hex()}" if ok else "no 2-byte reply to 0x42")

        # --- 0x47 Bus load ---------------------------------------------------
        f = sess.ask(rmbcp.CMD_BUSLOAD)
        run.expect(stage, "busload",
                   f is not None and f.command == rmbcp.CMD_BUSLOAD and len(f.data) == 2,
                   f"{int.from_bytes(f.data, 'big')} msgs/interval"
                   if f and len(f.data) == 2 else "no reply to 0x47")

        # --- 0x56 CAN baud rate ---------------------------------------------
        # dbCAN is fixed at 100 kbit/s (0xFE). A board reporting anything else
        # is either mis-built or has grown a configurable rate it must not have.
        f = sess.ask(0x56)
        ok = f is not None and f.command == 0x56 and f.data[:1] == b"\xFE"
        run.expect(stage, "can-baud", ok,
                   f"0x{f.data[0]:02X} (0xFE = 100 kbit/s)"
                   if f and f.data else "no reply to 0x56")

        # --- 0xA3 Block time echo -------------------------------------------
        f = sess.ask(rmbcp.CMD_IP_BLOCK_WAIT, b"\x0A")
        run.expect(stage, "block-time-echo",
                   f is not None and f.command == rmbcp.CMD_IP_BLOCK_WAIT
                   and f.data == b"\x0A",
                   "0xA3 echoed" if f else "no reply to 0xA3")

        # --- 0xC0 Reset device ----------------------------------------------
        # Spec 2.10.1: a device answers reset with its Device ID, not with
        # 0xC0. Getting this wrong is what made R1 loop during bring-up.
        f = sess.ask(0xC0)
        run.expect(stage, "reset-answers-device-id",
                   f is not None and f.command == rmbcp.CMD_DEVICE_ID,
                   f"0x{f.command:02X}" if f else "no reply to 0xC0")

        # --- 0x44 and 0xA4 must stay SILENT ---------------------------------
        # This is the only check here that asserts an absence, and it is the
        # one that matters most: replying to these stops R1 dead.
        for cmd, what in ((0x44, "interfaces-version"), (0xA4, "baud-calc-interval")):
            sess.send(cmd, b"\x00" * 2)
            f = sess.read_frame(silence_wait)
            run.expect(stage, f"silent-{what}", f is None,
                       "no reply, correct" if f is None
                       else f"answered 0x{f.command:02X} - R1 will loop on reset-device")

        # --- CAN frame in ----------------------------------------------------
        # A transparent bridge does not answer its own CAN frames, so the only
        # thing assertable without a bus is that the link survives one.
        sess.send(rmbcp.CMD_CAN11, (0x123).to_bytes(2, "big") + bytes([0x55, 0xAA]))
        f = sess.ask(rmbcp.CMD_DEVICE_ID)
        run.expect(stage, "alive-after-can-frame",
                   f is not None and f.command == rmbcp.CMD_DEVICE_ID,
                   "still answering after a CAN frame" if f else "link died")
    finally:
        sess.close()


# ===========================================================================
# can — the real bus, through an isolated adapter
# ===========================================================================
def run_can(run: Run, host: str, port: int, channel: str, interface: str,
            timeout: float) -> None:
    """End-to-end: TCP -> bridge -> CAN wire, and back.

    THE ADAPTER MUST BE GALVANICALLY ISOLATED. A non-isolated USB-CAN dongle
    ties CAN_GND to the host's ground through the USB shield, which shorts out
    the ADM3053 barrier this board exists to provide. The board will appear to
    work perfectly and the isolation test in BENCH-BRINGUP.md B.4 will pass on
    a board that is no longer isolated, because by then the short is gone.
    """
    stage = "can"
    try:
        import can  # noqa: PLC0415  - optional dependency
    except ImportError:
        run.add(stage, "available", SKIP,
                "python-can not installed: pip install python-can")
        return

    try:
        bus = can.Bus(channel=channel, interface=interface, bitrate=100_000)
    except Exception as exc:                                  # noqa: BLE001
        run.add(stage, "adapter", FAIL, f"{interface}:{channel}: {exc}")
        return

    try:
        sess = Session(host, port)
    except OSError as exc:
        run.add(stage, "connect", FAIL, f"{host}:{port}: {exc}")
        bus.shutdown()
        return

    try:
        run.add(stage, "adapter", PASS, f"{interface}:{channel} at 100 kbit/s")

        # --- host -> board -> wire ------------------------------------------
        want_id, want_data = 0x123, bytes([0x55, 0xAA, 0x00, 0xFF])
        sess.send(rmbcp.CMD_CAN11, want_id.to_bytes(2, "big") + want_data)

        seen = None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            msg = bus.recv(timeout=0.2)
            if msg and msg.arbitration_id == want_id and bytes(msg.data) == want_data:
                seen = msg
                break
        run.expect(stage, "tcp-to-wire", seen is not None,
                   f"id=0x{want_id:03X} data={want_data.hex()} seen on the bus"
                   if seen else f"frame never reached the wire within {timeout:.0f} s")

        # --- wire -> board -> host -------------------------------------------
        back_id, back_data = 0x456, bytes([0x0F, 0xF0, 0x5A])
        bus.send(can.Message(arbitration_id=back_id, data=back_data,
                             is_extended_id=False))

        got = None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            f = sess.read_frame(0.3)
            if f is None:
                continue
            _channel, inner = rmbcp.unwrap_extended(f)
            if not inner.is_can:
                continue
            can_id, payload, _ts = inner.as_can()
            if can_id == back_id and payload == back_data:
                got = f
                break
        run.expect(stage, "wire-to-tcp", got is not None,
                   f"id=0x{back_id:03X} arrived over TCP" if got
                   else f"nothing arrived over TCP within {timeout:.0f} s")
    finally:
        sess.close()
        bus.shutdown()


# ===========================================================================
# simulate — run the emulator as the device under test
# ===========================================================================
class Simulator:
    """tools/r70_emu.py as a subprocess, standing in for a board.

    Everything except the console and the CAN wire behaves identically to real
    firmware here, so the runner is exercised end to end today rather than the
    first time a board is plugged in. That is the point: a test rig that has
    never been run is not evidence about anything.
    """

    def __init__(self, udp_port: int, tcp_port: int):
        self.proc = subprocess.Popen(
            [sys.executable, str(HERE / "r70_emu.py"), "serve",
             "--udp-port", str(udp_port), "--tcp-port", str(tcp_port),
             "--answer-from", "127.0.0.1"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        # Wait for the listener rather than sleeping a guessed interval.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                out = self.proc.stdout.read() if self.proc.stdout else ""
                raise RuntimeError(f"emulator exited immediately:\n{out}")
            try:
                socket.create_connection(("127.0.0.1", tcp_port), timeout=0.2).close()
                return
            except OSError:
                time.sleep(0.1)
        self.stop()
        raise RuntimeError(f"emulator did not listen on TCP {tcp_port} within 10 s")

    def stop(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


# ===========================================================================
def build_record(args, run: Run, console: dict) -> dict:
    return {
        "schema": "dbcanary.board-test/1",
        "serial_number": args.serial_number,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "operator": args.operator,
        "simulated": args.simulate,
        "note": ("SIMULATED - this record proves the runner works, not that a "
                 "board does" if args.simulate else ""),
        "summary": {"pass": run.passed, "fail": run.failed, "skip": run.skipped},
        "checks": [asdict(c) for c in run.checks],
        "board_selftest": console.get("json", {}),
    }


def main(argv: list | None = None) -> int:
    p = argparse.ArgumentParser(
        description="dbCANary board acceptance test",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Run with --simulate to exercise the runner with no hardware.",
    )
    p.add_argument("--simulate", action="store_true",
                   help="run tools/r70_emu.py locally as the device under test")
    p.add_argument("--host", help="board IP; default is to discover it")
    p.add_argument("--broadcast", default="255.255.255.255",
                   help="where to send the discovery probe (default: %(default)s)")
    p.add_argument("--tcp-port", type=int, default=DATA_PORT)
    p.add_argument("--udp-port", type=int, default=DISCOVERY_PORT)
    p.add_argument("--port", dest="serial_port",
                   help="serial port of the self-test console, e.g. /dev/cu.usbmodem101")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--serial-number", default="unknown",
                   help="stamped into the record")
    p.add_argument("--operator", default="", help="stamped into the record")
    p.add_argument("--can-channel", help="python-can channel, e.g. can0 or PCAN_USBBUS1")
    p.add_argument("--can-interface", default="socketcan",
                   help="python-can interface (default: %(default)s)")
    p.add_argument("--skip", default="",
                   help="comma-separated stages to skip: console,discover,rmbcp,can")
    p.add_argument("--timeout", type=float, default=3.0,
                   help="per-stage network timeout in seconds (default: %(default)s)")
    p.add_argument("--console-timeout", type=float, default=25.0,
                   help="how long the board's self-test may take (default: %(default)s)")
    p.add_argument("--silence-wait", type=float, default=0.75,
                   help="how long to wait when proving a command is NOT answered")
    p.add_argument("--record", type=Path, help="write the JSON test record here")
    args = p.parse_args(argv)

    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    run = Run()
    sim = None

    if args.simulate:
        # 127.0.0.1 rather than a broadcast: the emulator binds INADDR_ANY, and
        # unicast keeps the test off whatever network the machine is on.
        sim = Simulator(args.udp_port, args.tcp_port)
        args.broadcast = "127.0.0.1"
        print("SIMULATED RUN - proves the runner, not a board\n")

    console: dict = {}
    try:
        if "console" not in skip:
            if args.simulate:
                # Recorded rather than silently omitted: a run whose summary
                # says "0 skipped" is claiming it looked at everything.
                run.add("console", "available", SKIP,
                        "simulated run - there is no board to talk to")
            elif args.serial_port:
                console = run_console(run, args.serial_port, args.baud,
                                      args.console_timeout)
            else:
                run.add("console", "available", SKIP,
                        "no --port given; the board's own self-test was not read")

        host = args.host
        if "discover" not in skip:
            found = run_discover(run, args.broadcast, args.udp_port, args.timeout)
            host = host or found
        elif not host:
            run.add("discover", "available", SKIP, "skipped, and no --host given")

        if "rmbcp" not in skip:
            if host:
                run_rmbcp(run, host, args.tcp_port, args.silence_wait)
            else:
                run.add("rmbcp", "available", SKIP,
                        "no address: discovery found nothing and no --host given")

        if "can" not in skip:
            if args.simulate:
                run.add("can", "available", SKIP,
                        "simulated run - there is no CAN wire")
            elif not args.can_channel:
                run.add("can", "available", SKIP,
                        "no --can-channel; the CAN wire was not tested")
            elif not host:
                run.add("can", "available", SKIP, "no address for the bridge")
            else:
                run_can(run, host, args.tcp_port, args.can_channel,
                        args.can_interface, args.timeout)
    finally:
        if sim:
            sim.stop()

    record = build_record(args, run, console)
    if args.record:
        args.record.parent.mkdir(parents=True, exist_ok=True)
        args.record.write_text(json.dumps(record, indent=2) + "\n")
        print(f"\nrecord written to {args.record}")

    print(f"\n{run.passed} passed, {run.failed} failed, {run.skipped} skipped")
    if args.simulate:
        print("This was a SIMULATED run. It says nothing about any board.")
    return 1 if run.failed else 0


if __name__ == "__main__":
    sys.exit(main())
