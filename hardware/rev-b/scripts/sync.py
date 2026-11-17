#!/usr/bin/env python3
"""
Rev B schematic -> PCB sync, for a board that starts as rev A's routed copper.

    <kicad python> hardware/rev-b/scripts/sync.py            # sync, then verify
    <kicad python> hardware/rev-b/scripts/sync.py --verify   # verify only

Rev A's sync_pcb.py re-asserts every pad's net but leaves tracks where they
were, which is right for adding parts and wrong for renames: a renamed net's
tracks would stay on the old name and short against their own pads. So this:

1. renames nets in place (plan.RENAMED): every pad, track, via and zone on the
   old net moves to the new one, so routed copper follows its net;
2. adds the footprints the schematic has and the board lacks, parked in a row
   below the board for layout.py to place (KiCad's library, or hardware/lib for
   canary: footprints);
3. gives rev A parts that became another part (plan.CHANGED) their new value,
   and every sourced part its LCSC / MPN / Manufacturer fields (hidden, F.Fab);
4. sets every pad's net from the netlist, and fails if any pad disagrees.

Pads that change net (plan.MOVED) leave their tracks behind on the old net;
layout.py deals with that copper explicitly. Close KiCad first: it holds the
board in memory and overwrites what a script wrote.
"""
import os
import re
import subprocess
import sys
import tempfile

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import plan  # noqa: E402

REVB = os.path.normpath(os.path.join(HERE, ".."))
BOARD = os.path.join(REVB, "canary.kicad_pcb")
ROOT_SCH = os.path.join(REVB, "canary.kicad_sch")
KICAD_CLI = os.environ.get("KICAD_CLI", "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli")
FP_ROOT = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"
PROJECT_LIBS = {"canary": os.path.normpath(os.path.join(REVB, "..", "lib", "canary.pretty"))}


def done(code=0):
    sys.stdout.flush()
    os._exit(code)  # KiCad's Python segfaults in teardown after a save


def netlist():
    """-> ({ref: (fpid, value)}, {(ref, pad): net or None})"""
    out = tempfile.NamedTemporaryFile(suffix=".net", delete=False).name
    subprocess.run([KICAD_CLI, "sch", "export", "netlist", "--format", "kicadsexpr",
                    "-o", out, ROOT_SCH], check=True, capture_output=True)
    text = open(out, encoding="utf-8").read()
    comps = {}
    for blk in re.split(r"\(comp\s", text[text.index("(components"):text.index("(libparts")])[1:]:
        ref = re.search(r'\(ref "([^"]+)"\)', blk)
        fp = re.search(r'\(footprint "([^"]+)"\)', blk)
        val = re.search(r'\(value "([^"]*)"\)', blk)
        if ref and fp:
            comps[ref.group(1)] = (fp.group(1), val.group(1) if val else "")
    pads = {}
    for blk in re.split(r"\(net\s+\(code", text[text.index("(nets"):])[1:]:
        name = re.search(r'\(name "([^"]+)"\)', blk).group(1)
        for ref, pin in re.findall(r'\(node\s+\(ref "([^"]+)"\)\s+\(pin "([^"]+)"\)', blk):
            pads[(ref, pin)] = None if name.startswith("unconnected-") else name
    return comps, pads


def net(board, name):
    n = board.FindNet(name)
    if n is None:
        board.Add(pcbnew.NETINFO_ITEM(board, name))
        n = board.FindNet(name)  # re-fetch: the proxy from Add() goes stale
    return n


def items(board):
    for f in board.GetFootprints():
        yield from f.Pads()
    yield from board.GetTracks()
    yield from board.Zones()


def rename(board):
    moved = 0
    for old, new in plan.RENAMED.items():
        if board.FindNet(old) is None:
            continue
        code = net(board, new).GetNetCode()
        for it in items(board):
            if it.GetNetname() == old:
                it.SetNetCode(code)
                moved += 1
    print(f"renamed {len(plan.RENAMED)} nets, {moved} items moved")


def add_missing(board, comps):
    have = {f.GetReference() for f in board.GetFootprints()}
    io = pcbnew.PCB_IO_MGR.FindPlugin(pcbnew.PCB_IO_MGR.KICAD_SEXP)
    x = 22.0
    added = []
    for ref, (fpid, value) in sorted(comps.items()):
        if ref in have:
            continue
        lib, name = fpid.split(":", 1)
        fp = io.FootprintLoad(PROJECT_LIBS.get(lib, os.path.join(FP_ROOT, lib + ".pretty")), name)
        if fp is None:
            sys.exit(f"{ref}: footprint {fpid} not found")
        fp.SetReference(ref)
        fp.SetValue(value)
        fp.SetFPIDAsString(fpid)
        fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(108.0)))
        board.Add(fp)
        added.append(ref)
        x += 6.0
    print(f"added {len(added)} footprints: {' '.join(added)}")


SOURCING_FIELDS = ("LCSC", "MPN", "Manufacturer")


def change(board):
    for ref, want in plan.CHANGED.items():
        f = board.FindFootprintByReference(ref)
        if "value" in want:
            f.SetValue(want["value"])
    print(f"changed {len(plan.CHANGED)} rev A parts: {' '.join(plan.CHANGED)}")
    wants = {ref: p[5] for ref, p in plan.PARTS.items()}
    wants.update(plan.CHANGED)
    n = 0
    for ref, want in wants.items():
        f = board.FindFootprintByReference(ref)
        for name in SOURCING_FIELDS:
            if name not in want:
                continue
            f.SetField(name, want[name])
            # SetField() makes the field visible on F.Silkscreen: sourcing
            # metadata, not a board marking (rev A's write_lcsc_fields.py)
            field = next(c for c in f.GetFields() if c.GetName() == name)
            field.SetVisible(False)
            field.SetLayer(pcbnew.F_Fab)
            n += 1
    # Fit=DNP pads: KiCad's own DNP attribute too, which BOM and placement
    # exports honour; the Fit field alone is only a note to a reader
    dnp = [ref for ref, p in plan.PARTS.items() if p[5].get("Fit") == "DNP"]
    for ref in dnp:
        board.FindFootprintByReference(ref).SetDNP(True)
    print(f"{n} sourcing fields written; DNP: {' '.join(dnp)}")


def assign(board, pads):
    for f in board.GetFootprints():
        for p in f.Pads():
            key = (f.GetReference(), p.GetNumber())
            if key not in pads:
                continue
            name = pads[key]
            p.SetNetCode(net(board, name).GetNetCode() if name else 0)


def verify(board, comps, pads):
    errors = []
    onboard = {f.GetReference(): f for f in board.GetFootprints()}
    for ref in comps:
        if ref not in onboard:
            errors.append(f"{ref}: in the schematic, not on the board")
    for ref, f in onboard.items():
        if ref not in comps and not ref.startswith(("#", "G", "kibuzzard")):
            errors.append(f"{ref}: on the board, not in the schematic")
        elif ref in plan.CHANGED and f.GetValue() != comps[ref][1]:
            errors.append(f"{ref}: board value {f.GetValue()!r}, schematic {comps[ref][1]!r}")
        for p in f.Pads():
            key = (ref, p.GetNumber())
            if key in pads and (pads[key] or "") != p.GetNetname():
                errors.append(f"{ref}.{p.GetNumber()}: board {p.GetNetname()!r}, schematic {pads[key]!r}")
    for e in errors:
        print("FAIL", e)
    print(f"{'FAIL' if errors else 'OK'}: {len(onboard)} footprints, {len(pads)} schematic pins checked")
    return 1 if errors else 0


def main():
    comps, pads = netlist()
    board = pcbnew.LoadBoard(BOARD)
    if "--verify" not in sys.argv:
        rename(board)
        add_missing(board, comps)
        change(board)
        assign(board, pads)
        board.Save(BOARD)
        board = pcbnew.LoadBoard(BOARD)
    done(verify(board, comps, pads))


if __name__ == "__main__":
    main()
