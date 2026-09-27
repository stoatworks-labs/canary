#!/usr/bin/env python3
"""
Delete stitching vias that DRC objects to.

A stitching via is redundant by construction - it exists only to give a pour
fragment a path to its plane, and there are ~170 of them. So when one lands too
close to a pad, a hole or the board edge, removing it is always safe, whereas
nudging it can push it into something else (which is what kept happening).

Only vias on the pour nets are ever removed, and only those DRC named. Vias
belonging to signal routing are left alone - those must be fixed by moving.
"""
import os as _os
_REPO = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import json
import sys

import pcbnew

BOARD = _REPO + "/hardware/canary.kicad_pcb"
POUR = ("GND", "CAN_GND", "CHASSIS", "VCC_3V3")
TOL = 1200


def main(drc_path):
    d = json.load(open(drc_path))
    targets = []
    for v in d["violations"]:
        if v["type"] not in ("clearance", "hole_clearance",
                             "copper_edge_clearance", "shorting_items",
                             "solder_mask_bridge", "via_dangling"):
            continue
        for i in v["items"]:
            if i["description"].startswith("Via"):
                targets.append((i["pos"]["x"], i["pos"]["y"]))

    board = pcbnew.LoadBoard(BOARD)
    # Snapshot positions ONCE. Calling board.GetTracks() again inside the loop
    # returns untyped SwigPyObjects (GetPosition().x raises) - the same SWIG
    # hazard as elsewhere in this project: query first, mutate second.
    vias = [(t, pcbnew.ToMM(t.GetPosition().x), pcbnew.ToMM(t.GetPosition().y),
             t.GetNetname().split("/")[-1])
            for t in board.GetTracks() if t.GetClass() == "PCB_VIA"]
    removed, kept = 0, 0
    for vx, vy in targets:
        for t, px, py, leaf in vias:
            if abs(px - vx) < 0.002 and abs(py - vy) < 0.002:
                if leaf in POUR:
                    board.Remove(t)
                    removed += 1
                else:
                    kept += 1
                break

    pcbnew.SaveBoard(BOARD, board)
    print(f"stitching vias removed : {removed}")
    if kept:
        print(f"signal vias left alone : {kept}  (need moving, not deleting)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
