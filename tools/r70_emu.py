#!/usr/bin/env python3
"""
dbCANary — host-side d&b R70 emulator and discovery prober.

Purpose: everything the R70 does on the wire is publicly documented EXCEPT the
UDP 33333 discovery exchange that makes R1 list the interface. This tool cracks
that, using nothing but a laptop and a copy of R1 — no ESP32, no R70, no amps.

Run it on a machine in the same broadcast domain as R1, then in R1 open
  Extras > Options > CAN  and press "Refresh".
R1 will broadcast its probe; this tool prints it byte for byte and answers with
whichever hypothesis you selected. When R1 lists the device, the handshake is
solved and the bytes get written into docs/PROTOCOL.md and then the firmware.

  # 1. Watch only — learn what R1 actually sends.
  python3 tools/r70_emu.py sniff

  # 2. Answer the probe and see whether R1 lists us.
  python3 tools/r70_emu.py serve --host-name db-70 --mac 00:50:C2:5D:C0:BE

  # 3. Try a literal reply you worked out from a capture.
  python3 tools/r70_emu.py serve --reply raw --raw-hex 43064009...0d

If R1 runs in a VM, its network adapter must be BRIDGED, not NAT — a NATted
guest cannot reach a broadcast responder on the host.
"""

from __future__ import annotations

import argparse
import logging
import selectors
import socket
import sys
import time

import dbcan_device
import r70_ddt
import rmbcp
from rmbcp import Decoder

DISCOVERY_PORT = 33333  # fixed on the R70
DATA_PORT = 30000  # R70 socket 1 default, adjustable in its web UI

log = logging.getLogger("r70")


def hexdump(data: bytes, indent: str = "    ") -> str:
    """Classic offset / hex / printable-ASCII dump."""
    out = []
    for off in range(0, len(data), 16):
        chunk = data[off:off + 16]
        hexpart = " ".join(f"{b:02x}" for b in chunk)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        out.append(f"{indent}{off:04x}  {hexpart:<47}  |{text}|")
    return "\n".join(out)


def looks_like_rmbcp(data: bytes) -> list[rmbcp.Frame]:
    """Try to read the payload as RM Byte Command frames."""
    dec = Decoder()
    frames = dec.feed(data)
    # Only believe it if we consumed the datagram cleanly.
    return frames if frames and not dec.bad_frames and not dec.buf else []


def annotate_probe(data: bytes) -> None:
    """Log a discovery datagram and decode it as R70 device-detection."""
    log.info("\n%s", hexdump(data))
    try:
        pkt = r70_ddt.Packet.decode(data)
    except ValueError as exc:
        log.info("  -> not a device-detection packet: %s", exc)
        return
    kind = "REQUEST" if pkt.is_request else f"answer (opcode 0x{pkt.opcode:02X})"
    log.info("  -> %s, interface index %d, %d record(s)",
             kind, pkt.interface_index, len(pkt.records))
    for rec in pkt.records:
        log.info("       tag=%r ip=%s port=%d mac=%s host=%r service=%d protocol=%d",
                 rec.tag.decode("ascii", "replace"), rec.ip, rec.port,
                 rec.mac.hex(":"), rec.hostname, rec.service, rec.protocol)


def annotate(data: bytes) -> None:
    """Log a payload plus any structure we can recognise in it."""
    log.info("\n%s", hexdump(data))
    frames = looks_like_rmbcp(data)
    if frames:
        log.info("  -> parses as %d RM Byte Command frame(s):", len(frames))
        for f in frames:
            desc = f"command 0x{f.command:02X}"
            if f.command == rmbcp.CMD_DEVICE_ID:
                desc += " (Device ID string)"
            elif f.command == rmbcp.CMD_VERSION:
                desc += " (HW/SW version)"
            elif f.is_can:
                can_id, payload, ts = f.as_can()
                desc += f" CAN {rmbcp.describe_dbcan_id(can_id) if can_id < 0x800 else hex(can_id)}"
                desc += f" data={payload.hex(' ') or '-'}" + (f" ts={ts}" if ts else "")
            log.info("       %s data=%s", desc, f.data.hex(" ") or "-")
    else:
        printable = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
        log.info("  -> not RM Byte Command framing; as text: %r", printable)


# --- Discovery ---------------------------------------------------------------

def build_id_string(host_name: str, mac: str, port: int, transport: str) -> bytes:
    """
    Best-guess Device ID payload.

    R1's interface list shows entries as "<host>-<TRANSPORT>-<port>" alongside the
    MAC (e.g. "db-70-TCP-30000" / 0050C25DC0BE), and RMBCP command 0x40 is called
    "Device ID string" whose last 2 bytes are a 16-bit device id. So the most
    likely reply is that string plus the MAC. Unverified until R1 confirms.
    """
    mac_bytes = bytes.fromhex(mac.replace(":", "").replace("-", ""))
    name = f"{host_name}-{transport}-{port}".encode("ascii")
    return name + b"\x00" + mac_bytes


def socket_specs(args: argparse.Namespace) -> list[tuple[int, int, int]]:
    """
    The sockets we advertise, as (service, protocol, port).

    A real R70 has four. R1's flags() keeps the socket column read-only unless
    it sees at least two, so advertising the full set is not cosmetic.
    """
    return [
        (args.service, args.protocol, args.tcp_port + i)
        for i in range(args.sockets)
    ]


def make_reply(args: argparse.Namespace, probe: bytes, peer_ip: str) -> bytes | None:
    """Produce the discovery response for the chosen strategy."""
    if args.reply == "none":
        return None
    if args.reply == "raw":
        if not args.raw_hex:
            log.error("--reply raw needs --raw-hex")
            return None
        return bytes.fromhex(args.raw_hex.replace(" ", ""))
    # A real R70 sits on exactly one network and answers with one IP. We can see
    # probes on every local interface, and answering all of them hands R1 several
    # entries that share a host name and port — i.e. the same buildIfUniqueName().
    # Restrict ourselves to one interface to stay faithful.
    if args.answer_from:
        ours = r70_ddt.local_ip_towards(peer_ip)
        if ours != args.answer_from:
            log.info("  <- (ignored: probe reaches us on %s, not %s)", ours, args.answer_from)
            return None

    # "ddt" (default): the real device-detection answer, as documented from
    # captures of R1's discovery traffic. See r70_ddt.py and docs/PROTOCOL.md §4.
    try:
        return r70_ddt.build_answer(
            probe,
            hostname=args.host_name,
            mac=bytes.fromhex(args.mac.replace(":", "").replace("-", "")),
            sockets=socket_specs(args),
            peer_ip=peer_ip,
        )
    except ValueError as exc:
        log.error("cannot build answer: %s", exc)
        return None


def open_discovery_socket(port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass  # not fatal; some platforms refuse it
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("", port))
    sock.setblocking(False)
    return sock


# --- Data socket (RM Byte Command Protocol over TCP) -------------------------

# Gateway settings that R1 reads and writes. Key = the REQUEST command byte;
# the matching SET command is always request+1 (0x56 request / 0x57 set, and so
# on). Values are the defaults an R70 would report. All from the RMBCP spec
# chapters 2.6-2.9; see docs/PROTOCOL.md §2.
CAN_BAUD_100K = 0xFE  # dbCAN's fixed rate, per the spec's baud-rate table

SETTINGS_DEFAULTS: dict[int, bytes] = {
    0x50: bytes(4),                  # receive channel ID settings
    0x52: bytes(4),                  # receive channel mask settings
    0x56: bytes([CAN_BAUD_100K]),    # CAN baud rate -> 100 kBit/s
    0x5A: b"\x00",                   # active / passive mode
    0x5C: bytes(2),                  # receive channel cycle time
    0x60: b"\x01",                   # feedback settings: serial output on
    0x80: b"\x00",                   # server objects on/off
    0x84: bytes(4),                  # transmit channel ID settings
    0x86: bytes(4),                  # transmit channel mask settings
    0x88: bytes(2),                  # transmit channel cycle time
    0xA0: b"\x00",                   # timestamp settings: off
}

# Commands that carry a value and are simply acknowledged by echoing it back.
ECHO_COMMANDS = {
    0x49: "set CAN transmit delay time",
    0xA2: "set CAN transmit delay time",
    0xA3: "set IP-block wait time",
}

# Commands R1 sends that a real R70 evidently does NOT answer. Observed: when we
# started replying to 0x44 and 0xA4, R1 stopped progressing past initialisation
# and began issuing 0xC0 (reset device) in a loop. On the connection where we
# ignored them, R1 went on to 0x57 (set CAN baud rate) and started scanning the
# bus. Silence is the faithful behaviour here.
SILENT_COMMANDS = {
    0x44: "interfaces version",
    0xA4: "set CAN baudrate calculation interval",
}


class DataSession:
    """One R1 connection on the data port, speaking RMBCP."""

    def __init__(self, conn: socket.socket, peer, args: argparse.Namespace):
        self.conn, self.peer, self.args = conn, peer, args
        self.dec = Decoder()
        self.started = time.monotonic()
        self.can_tx = 0
        self.settings = dict(SETTINGS_DEFAULTS)
        self.device = args.virtual_device  # VirtualDevice or None

    def on_readable(self) -> bool:
        """Returns False when the peer has gone away."""
        try:
            chunk = self.conn.recv(4096)
        except ConnectionError:
            return False
        if not chunk:
            return False

        for frame in self.dec.feed(chunk):
            self._handle(frame)
        return True

    def _send(self, command: int, data: bytes = b"") -> None:
        try:
            self.conn.sendall(rmbcp.encode(command, data))
        except OSError as exc:
            log.warning("send failed: %s", exc)

    def _device_id(self) -> bytes:
        return build_id_string(self.args.host_name, self.args.mac,
                               self.args.tcp_port, "TCP")

    def _handle(self, frame: rmbcp.Frame) -> None:
        # Unwrap the multi-channel form so one code path handles both.
        channel, inner = rmbcp.unwrap_extended(frame)

        if inner.is_can:
            self._handle_can(channel, inner)
            return

        cmd, data = inner.command, inner.data

        if cmd == rmbcp.CMD_DEVICE_ID:
            log.info("R1 -> device ID request")
            self._send(cmd, self._device_id())
        elif cmd == rmbcp.CMD_VERSION:
            log.info("R1 -> version request")
            # HW, FW, bootloader — 16-bit each. Invented until a real R70 is read.
            self._send(cmd, bytes([0x01, 0x00, 0x03, 0x00, 0x01, 0x00]))
        elif cmd == 0x42:  # error status
            log.info("R1 -> error status request")
            self._send(cmd, bytes(2))  # no errors
        elif cmd in SILENT_COMMANDS:
            log.info("R1 -> %s (deliberately not answered)", SILENT_COMMANDS[cmd])
        elif cmd == rmbcp.CMD_BUSLOAD:
            self._send(cmd, bytes(2))
        elif cmd == 0x58:  # CAN controller reset
            log.info("R1 -> CAN controller reset")
            self._send(cmd)
        elif cmd == 0xC0:  # reset device
            # Spec 2.10.1: "The devices respond to this command with the
            # Command 'Device ID'" — not with 0xC0.
            log.info("R1 -> reset device (answering with Device ID)")
            self._send(rmbcp.CMD_DEVICE_ID, self._device_id())
        elif cmd in ECHO_COMMANDS:
            log.info("R1 -> %s = %s", ECHO_COMMANDS[cmd], data.hex(" ") or "-")
            self._send(cmd, data)
        elif cmd in self.settings:  # a request for stored settings
            log.info("R1 -> request setting 0x%02X", cmd)
            self._send(cmd, self.settings[cmd])
        elif cmd - 1 in self.settings:  # the matching set command
            base = cmd - 1
            self.settings[base] = data
            log.info("R1 -> set 0x%02X = %s", cmd, data.hex(" ") or "-")
            self._send(cmd, data)
        else:
            # Deliberately silent. Replying 0x48 ("device cannot execute
            # command") is the spec's answer, but it is untested against R1 and
            # the one run that reached the CAN scan simply ignored these.
            log.info("R1 -> unanswered command 0x%02X data=%s",
                     cmd, data.hex(" ") or "-")

    def _handle_can(self, channel: int, inner: rmbcp.Frame) -> None:
        can_id, payload, _ts = inner.as_can()
        self.can_tx += 1
        where = rmbcp.describe_dbcan_id(can_id) if not inner.is_extended_id else "extended"
        log.info("R1 -> CAN[%d] id=0x%03X %-34s %s",
                 channel, can_id, where, payload.hex(" ") or "-")

        # A real bridge forwards this to the CAN controller. With no amplifier
        # attached nothing answers — so optionally stand one in.
        if self.device is None or inner.is_extended_id:
            return
        for reply_id, reply_payload in self.device.respond(can_id, payload):
            log.info("    <- %-34s %s",
                     rmbcp.describe_dbcan_id(reply_id), reply_payload.hex(" ") or "-")
            try:
                self.conn.sendall(rmbcp.encode_can(reply_id, reply_payload))
            except OSError as exc:
                log.warning("CAN reply failed: %s", exc)

    def close(self) -> None:
        log.info("closed %s:%d after %.1fs, %d CAN frames from R1",
                 *self.peer, time.monotonic() - self.started, self.can_tx)
        self.conn.close()


def run(args: argparse.Namespace) -> int:
    sel = selectors.DefaultSelector()

    try:
        udp = open_discovery_socket(args.udp_port)
    except OSError as exc:
        log.error("cannot bind UDP %d: %s", args.udp_port, exc)
        log.error("something else is already listening — a real R70 tool, or another copy of this.")
        return 1
    sel.register(udp, selectors.EVENT_READ, "udp")
    log.info("discovery listener on UDP %d (reply strategy: %s)", args.udp_port, args.reply)

    listeners: list[socket.socket] = []
    if args.reply != "none":
        # Listen on every port we advertise — R1 connects to whichever socket the
        # user selects, not necessarily the first.
        for _service, _protocol, port in socket_specs(args):
            tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                tcp.bind(("", port))
            except OSError as exc:
                log.error("cannot bind TCP %d: %s", port, exc)
                for done in listeners:
                    done.close()
                return 1
            tcp.listen(5)
            tcp.setblocking(False)
            sel.register(tcp, selectors.EVENT_READ, "tcp")
            listeners.append(tcp)
        log.info("data sockets on TCP %s, identifying as %s / %s",
                 ", ".join(str(p) for _s, _p, p in socket_specs(args)),
                 args.host_name, args.mac)

    if args.virtual_device:
        log.info("virtual amplifier at dbCAN %s — replies with CAN id 0x%03X "
                 "(payload is a placeholder, see dbcan_device.py)",
                 args.virtual_device.address, args.virtual_device.response_id)

    log.info("waiting — in R1 open Extras > Options > CAN and press Refresh (Ctrl-C to stop)")
    sessions: dict[socket.socket, DataSession] = {}

    try:
        while True:
            for key, _mask in sel.select(timeout=1.0):
                kind = key.data

                if kind == "udp":
                    probe, addr = key.fileobj.recvfrom(4096)
                    log.info("=" * 68)
                    log.info("DISCOVERY probe from %s:%d — %d bytes", *addr, len(probe))
                    annotate_probe(probe)
                    reply = make_reply(args, probe, addr[0])
                    if reply:
                        key.fileobj.sendto(reply, addr)
                        log.info("  <- answered %d bytes:", len(reply))
                        annotate_probe(reply)
                    elif args.reply == "none":
                        log.info("  <- (no reply: sniff mode)")
                    else:
                        log.info("  <- (not a request for us; ignored)")

                elif kind == "tcp":
                    conn, peer = key.fileobj.accept()
                    conn.setblocking(False)
                    local_port = key.fileobj.getsockname()[1]
                    log.info("=" * 68)
                    log.info("R1 CONNECTED from %s:%d to socket port %d — discovery worked.",
                             peer[0], peer[1], local_port)
                    sessions[conn] = DataSession(conn, peer, args)
                    sel.register(conn, selectors.EVENT_READ, "session")

                else:  # an established session
                    conn = key.fileobj
                    if not sessions[conn].on_readable():
                        sel.unregister(conn)
                        sessions.pop(conn).close()
    except KeyboardInterrupt:
        log.info("stopping")
    finally:
        for conn, session in list(sessions.items()):
            sel.unregister(conn)
            session.close()
        sel.close()
        udp.close()
        for tcp in listeners:
            tcp.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Emulate a d&b R70 well enough for R1 to discover and connect to it.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("mode", choices=["sniff", "serve"],
                        help="sniff = observe R1's probe only; serve = also answer it")
    parser.add_argument("--reply", choices=["ddt", "raw", "none"], default="ddt",
                        help="discovery reply mode (default: ddt = the real answer format)")
    parser.add_argument("--raw-hex", help="literal reply bytes for --reply raw")
    parser.add_argument("--host-name", default="db-70", help="R70 host name (default: db-70)")
    parser.add_argument("--mac", default="00:50:C2:5D:C0:BE",
                        help="MAC advertised in the answer. R1 does NOT validate the OUI, "
                             "so real hardware can use its own address")
    parser.add_argument("--answer-from", metavar="LOCAL_IP",
                        help="only answer probes that reach us on this local address, "
                             "so R1 sees a single interface as it would a real R70")
    parser.add_argument("--virtual-device", metavar="SUBNET.DEVICE",
                        help="stand in for an amplifier at this dbCAN address, e.g. 1.2. "
                             "Addressing is correct; the payload is a placeholder because "
                             "the dbCAN application layer is undocumented (see dbcan_device.py)")
    parser.add_argument("--virtual-reply-hex", metavar="HEX",
                        help="fixed reply payload for --virtual-device (default: echo)")
    parser.add_argument("--sockets", type=int, default=4,
                        help="how many sockets to advertise, ports counting up from "
                             "--tcp-port. A real R70 has 4, and R1 needs at least 2 "
                             "before it will let the socket column be edited (default 4)")
    parser.add_argument("--service", type=int, default=r70_ddt.SERVICE_SERVER,
                        help="record service byte: 1 or 2 (default 1)")
    parser.add_argument("--protocol", type=int, default=r70_ddt.PROTOCOL_TCP,
                        help="record protocol byte: 1=TCP, 3=UDP (default 1)")
    parser.add_argument("--udp-port", type=int, default=DISCOVERY_PORT)
    parser.add_argument("--tcp-port", type=int, default=DATA_PORT)
    args = parser.parse_args(argv)

    if args.mode == "sniff":
        args.reply = "none"

    if args.virtual_device:
        payload = bytes.fromhex(args.virtual_reply_hex) if args.virtual_reply_hex else None
        try:
            args.virtual_device = dbcan_device.VirtualDevice.parse(args.virtual_device, payload)
        except ValueError as exc:
            parser.error(str(exc))

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
