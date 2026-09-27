#!/usr/bin/env python3
"""
Put simulated d&b amplifiers on the virtual dbCAN bus.

This is what closes the loop. Until now the proven chain stopped at "R1
discovers and connects to the interface". With the hub, the host build of the
firmware and this, the whole chain runs in software:

    R1  <--TCP/UDP-->  canaryd (the shipping C)  <--vcan-->  vamp.py

**Scope warning, inherited from dbcan_device.py and just as important here.**
dbCAN's *identifier* layout is documented; its *application layer* — what the
payload bytes mean — is not, in any vendor document we have. So these devices
address frames correctly and cannot speak an amplifier's language. The default
reply echoes the request.

That makes this an instrument, not an oracle. It answers "does R1 change its
behaviour when something replies on the bus, and does our bridge carry the
reply back intact?" Any R1 reaction is evidence about the protocol to be read
and written down — never proof that a device is correct.

    python3 tools/vamp.py 1.2 1.3
    python3 tools/vamp.py 1.2 --reply deadbeef
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dbcan_device import VirtualDevice
from rmbcp import parse_dbcan_id
from vcan import DEFAULT_PORT, VCanNode


def run(devices: list[VirtualDevice], port: int, verbose: bool = True) -> int:
    with VCanNode(port=port, timeout=None) as node:
        names = ", ".join(d.address for d in devices)
        print(f"vamp: {len(devices)} device(s) on vcan {port}: {names}", flush=True)

        while True:
            frame = node.recv()
            if frame is None:
                continue
            can_id, data, _extended, rtr = frame
            if rtr:
                continue

            cls_, subnet, dev = parse_dbcan_id(can_id)
            if verbose:
                print(f"  rx {can_id:#05x} (class={cls_} {subnet}.{dev:02d}) "
                      f"{data.hex(' ') or '-'}", flush=True)

            for device in devices:
                for reply_id, payload in device.respond(can_id, data):
                    node.send(reply_id, payload)
                    if verbose:
                        print(f"  tx {reply_id:#05x} <- {device.address} "
                              f"{payload.hex(' ') or '-'}", flush=True)


def main(argv: list | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("address", nargs="+",
                   help="dbCAN addresses in d&b's subnet.device form, e.g. 1.2")
    p.add_argument("--reply", help="hex payload to answer with; default echoes")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    payload = bytes.fromhex(args.reply) if args.reply else None
    if payload is not None and len(payload) > 8:
        p.error("a CAN frame carries at most 8 data bytes")

    try:
        devices = [VirtualDevice.parse(a, reply_payload=payload)
                   for a in args.address]
    except ValueError as exc:
        p.error(str(exc))

    try:
        return run(devices, args.port, verbose=not args.quiet)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
