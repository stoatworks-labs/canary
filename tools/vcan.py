#!/usr/bin/env python3
"""
A virtual CAN bus over UDP, so the firmware and simulated amplifiers can share
a bus with no hardware and no Linux.

SocketCAN's `vcan` would be the obvious choice, but it is Linux-only and this
project is developed on a Mac. So: every participant sends datagrams to a hub,
and the hub reflects each one to all the *other* participants. That is what a
CAN bus looks like from a node — everyone hears everyone, nobody hears itself.

The C side of this format is firmware/hostsim/vcan.c, which backs the
`driver/twai.h` stand-in. The two must agree byte for byte:

    0..3   identifier, uint32 little-endian
    4      flags: bit0 extended, bit1 RTR
    5      DLC (0..8)
    6..13  data, unused bytes zero

A datagram of any other length registers a peer without injecting traffic.

WHAT THIS IS NOT: there is no arbitration, no bit timing, no error counters and
no real bus-off. Ordering under contention is whatever the loopback gives you.
Use it to test protocol and plumbing, never to make a timing claim.

    python3 tools/vcan.py hub          # run the bus
    python3 tools/vcan.py dump         # watch every frame on it
"""

from __future__ import annotations

import argparse
import socket
import struct
import sys

FRAME_LEN = 14
DEFAULT_PORT = 35000

FLAG_EXTENDED = 1
FLAG_RTR = 2


def encode_frame(can_id: int, data: bytes, extended: bool = False,
                 rtr: bool = False) -> bytes:
    """Pack one frame into the 14-byte virtual-bus format."""
    if len(data) > 8:
        raise ValueError("a CAN frame carries at most 8 data bytes")
    flags = (FLAG_EXTENDED if extended else 0) | (FLAG_RTR if rtr else 0)
    return struct.pack("<IBB", can_id, flags, len(data)) + data.ljust(8, b"\x00")


def decode_frame(raw: bytes) -> tuple[int, bytes, bool, bool]:
    """Unpack a frame. Returns (id, data, extended, rtr)."""
    if len(raw) != FRAME_LEN:
        raise ValueError(f"expected {FRAME_LEN} bytes, got {len(raw)}")
    can_id, flags, dlc = struct.unpack("<IBB", raw[:6])
    dlc = min(dlc, 8)
    return can_id, raw[6:6 + dlc], bool(flags & FLAG_EXTENDED), bool(flags & FLAG_RTR)


class VCanNode:
    """One participant on the virtual bus."""

    def __init__(self, port: int = DEFAULT_PORT, timeout: float | None = 1.0):
        self.hub = ("127.0.0.1", port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(timeout)
        self.sock.sendto(b"\x00", self.hub)  # register

    def send(self, can_id: int, data: bytes, extended: bool = False) -> None:
        self.sock.sendto(encode_frame(can_id, data, extended), self.hub)

    def recv(self) -> tuple[int, bytes, bool, bool] | None:
        """Next frame, or None on timeout / a registration ping."""
        try:
            raw, _ = self.sock.recvfrom(64)
        except socket.timeout:
            return None
        if len(raw) != FRAME_LEN:
            return None
        return decode_frame(raw)

    def close(self) -> None:
        self.sock.close()

    def __enter__(self) -> "VCanNode":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def run_hub(port: int, quiet: bool = False) -> int:
    """Reflect every datagram to every peer except the one that sent it."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port))
    peers: set[tuple[str, int]] = set()

    if not quiet:
        print(f"vcan hub on 127.0.0.1:{port}", flush=True)

    while True:
        raw, sender = sock.recvfrom(64)
        peers.add(sender)
        if len(raw) != FRAME_LEN:
            continue  # registration ping
        for peer in peers:
            if peer != sender:
                sock.sendto(raw, peer)


def run_dump(port: int) -> int:
    """Print every frame on the bus. A passive node, so it perturbs nothing."""
    with VCanNode(port=port, timeout=None) as node:
        print(f"watching vcan on 127.0.0.1:{port}", flush=True)
        while True:
            frame = node.recv()
            if frame is None:
                continue
            can_id, data, extended, rtr = frame
            kind = "ext" if extended else "std"
            flag = " RTR" if rtr else ""
            print(f"  {can_id:#05x} [{kind}]{flag} {data.hex(' ') or '-'}",
                  flush=True)


def main(argv: list | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mode", choices=("hub", "dump"))
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    try:
        return run_hub(args.port, args.quiet) if args.mode == "hub" \
            else run_dump(args.port)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
