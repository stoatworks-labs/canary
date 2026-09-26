#!/usr/bin/env python3
"""
Additive schematic -> PCB sync, then a full verification diff.

KiCad's own "Update PCB from Schematic" (F8) is GUI-only and kicad-cli cannot do
it. This does the additive part programmatically via pcbnew: it adds footprints
for components that exist in the schematic but not on the board, and then forces
EVERY pad's net on the whole board to match the schematic netlist.

That second step is what makes this trustworthy: it is not "add the new bits and
hope", it re-asserts the complete netlist and then verify() diffs pad-by-pad
against the schematic. If a single pad disagrees the script fails loudly.

Usage:
  <kicad python> sync_pcb.py <netlist.net> <board.kicad_pcb>
"""
import os as _os
_REPO = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import re
import sys
from collections import defaultdict

import pcbnew

FP_LIB_DIRS = [
    "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints",
    _REPO + "/hardware/lib",
]


def parse_netlist(path):
    """-> ({ref: (fpid, value)}, {(ref, pad): netname})"""
    d = open(path).read()

    comps = {}
    cbody = d[d.index("(components"):d.index("(libparts")]
    for blk in re.split(r"\n\s*\(comp\s", cbody)[1:]:
        ref = re.search(r'\(ref "([^"]+)"\)', blk)
        val = re.search(r'\(value "([^"]*)"\)', blk)
        fp = re.search(r'\(footprint "([^"]+)"\)', blk)
        if ref and fp:
            comps[ref.group(1)] = (fp.group(1), val.group(1) if val else "")

    pads = {}
    nbody = d[d.index("(nets"):]
    for blk in re.split(r"\n\t\t\(net\s", nbody)[1:]:
        nm = re.search(r'\(name "([^"]+)"\)', blk)
        if not nm:
            continue
        net = nm.group(1)
        for ref, pad in re.findall(r'\(ref "([^"]+)"\)\s*\(pin "([^"]+)"', blk):
            pads[(ref, pad)] = net
    return comps, pads


def find_fp_file(fpid):
    lib, name = fpid.split(":", 1)
    for root in FP_LIB_DIRS:
        p = os.path.join(root, lib + ".pretty", name + ".kicad_mod")
        if os.path.exists(p):
            return os.path.join(root, lib + ".pretty"), name
    return None, None


def net_for(board, name, cache):
    """Get or create a NETINFO_ITEM for `name`."""
    if name in cache:
        return cache[name]
    ni = board.FindNet(name)
    if ni is None or ni.GetNetname() != name:
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
    cache[name] = ni
    return ni


def main():
    netlist_path, board_path = sys.argv[1], sys.argv[2]
    comps, padnets = parse_netlist(netlist_path)

    board = pcbnew.LoadBoard(board_path)
    on_board = {f.GetReference(): f for f in board.GetFootprints()}

    # Work out what needs loading BEFORE touching the board.
    #
    # ORDER MATTERS: in this KiCad 10 SWIG build, calling board.Remove() first
    # leaves pcbnew.FootprintLoad's internal plugin object untyped
    # ('SwigPyObject has no attribute FootprintLoad'). Same class of hazard as
    # PCB_SHAPE creation breaking GetFootprints(). So: load everything, THEN
    # mutate the board.
    todo = []          # (ref, value, fpid, reason)
    for ref, (fpid, val) in sorted(comps.items()):
        fp = on_board.get(ref)
        if fp is None:
            todo.append((ref, val, fpid, "new"))
            continue
        lid = fp.GetFPID()
        cur = f"{lid.GetLibNickname()}:{lid.GetLibItemName()}"
        if cur != fpid:
            todo.append((ref, val, fpid, f"swap from {cur}"))

    loaded, failed = [], []
    for ref, val, fpid, reason in todo:
        libdir, name = find_fp_file(fpid)
        fp = pcbnew.FootprintLoad(libdir, name) if libdir else None
        if fp is None:
            failed.append((ref, fpid))
            continue
        # FootprintLoad() returns a footprint whose LIB_ID has an EMPTY library
        # nickname, so the board would store `(footprint "R_0402_1005Metric")`
        # instead of `(footprint "Resistor_SMD:R_0402_1005Metric")`. That never
        # matches the schematic again, so every subsequent run re-added and
        # re-parked the same parts, silently undoing their placement. Set it.
        fp.SetFPID(pcbnew.LIB_ID(fpid.split(":", 1)[0], name))
        fp.SetReference(ref)
        fp.SetValue(val)
        loaded.append((ref, fp, reason))

    # Now mutate: drop the old instances, add the freshly loaded ones.
    for ref, fp, reason in loaded:
        old = on_board.get(ref)
        if old is not None:
            board.Remove(old)
    for i, (ref, fp, reason) in enumerate(loaded):
        # Park off-board; place.py positions them afterwards.
        fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(140.0),
                                       pcbnew.FromMM(20.0 + 4.0 * i)))
        board.Add(fp)

    pcbnew.SaveBoard(board_path, board)
    for ref, fp, reason in loaded:
        print(f"  {ref:<7} {reason}")
    print(f"footprints added/swapped : {len(loaded)}")
    if failed:
        print(f"FAILED TO LOAD           : {failed}")
    return 1 if failed else 0


def assert_nets(netlist_path, board_path):
    """
    Force every pad's net to match the schematic, on a FRESHLY loaded board.

    This is a separate pass rather than part of main() on purpose. After main()
    has walked GetFPID()/FootprintLoad()/Remove()/Add(), pcbnew's SWIG type
    resolution is unreliable and footprint proxies come back as bare
    SwigPyObjects ('object is not iterable' on .Pads()) - whether the map was
    built before or after those calls. A clean LoadBoard resets that, which is
    why verify() has always worked. Same trick, same reason.
    """
    comps, padnets = parse_netlist(netlist_path)
    board = pcbnew.LoadBoard(board_path)
    cache = {}
    touched = 0
    revalued = 0
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        # Values must track the schematic on EVERY sync, not only when a
        # footprint is first loaded. C401/C402 were changed 22pF -> 18pF in
        # the schematic; the board kept 22pF and the BOM (generated from the
        # board) ordered the wrong capacitor.
        want_val = comps.get(ref, (None, None))[1]
        if want_val is not None and fp.GetValue() != want_val:
            fp.SetValue(want_val)
            revalued += 1
        for pad in fp.Pads():
            want = padnets.get((ref, pad.GetPadName()))
            if want is None:
                continue                      # NC pad: leave as-is
            if pad.GetNetname() != want:
                pad.SetNet(net_for(board, want, cache))
                touched += 1
    pcbnew.SaveBoard(board_path, board)
    print(f"pad nets updated         : {touched}")
    print(f"values updated           : {revalued}")
    return 0


def verify(netlist_path, board_path):
    """Diff every pad on the board against the schematic netlist."""
    comps, padnets = parse_netlist(netlist_path)
    board = pcbnew.LoadBoard(board_path)
    on_board = {f.GetReference(): f for f in board.GetFootprints()}

    missing = sorted(set(comps) - set(on_board))
    extra = sorted(set(on_board) - set(comps))
    mismatched = []
    for (ref, pad), want in padnets.items():
        fp = on_board.get(ref)
        if fp is None:
            continue
        p = fp.FindPadByNumber(pad)
        got = p.GetNetname() if p else "<no such pad>"
        if got != want:
            mismatched.append((ref, pad, want, got))

    print(f"components  schematic={len(comps)}  board={len(on_board)}")
    print(f"missing from board : {missing or 'none'}")
    print(f"extra on board     : {extra or 'none'}")
    print(f"pad net mismatches : {len(mismatched)}")
    for m in mismatched[:15]:
        print(f"   {m[0]}.{m[1]}  want={m[2]!r} got={m[3]!r}")
    ok = not missing and not extra and not mismatched
    print("SYNC VERIFIED" if ok else "SYNC FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    # One pass per PROCESS. pcbnew's SWIG type resolution degrades after a pass
    # of FootprintLoad/Remove/Add - even a second pcbnew.LoadBoard() then hands
    # back a bare SwigPyObject. Re-running the interpreter is the only reliable
    # reset, so the caller invokes: --add, then --nets, then --verify.
    mode = sys.argv[3] if len(sys.argv) > 3 else "--all"
    if mode == "--verify" or mode == "--verify-only":
        sys.exit(verify(sys.argv[1], sys.argv[2]))
    if mode == "--nets":
        sys.exit(assert_nets(sys.argv[1], sys.argv[2]))
    sys.exit(main())
