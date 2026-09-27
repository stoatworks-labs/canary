#!/usr/bin/env python3
"""
Nudge the few autorouter vias that violate clearance or edge clearance.

A via cannot simply be moved: tracks attach to it BY POSITION, so shifting the
via alone would silently break the connection. Every track endpoint coincident
with the via is moved by the same delta.
"""
import os as _os
_REPO = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import json
import math
import sys

import pcbnew

BOARD = _REPO + "/hardware/canary.kicad_pcb"
BOARD_BOX = (20.0, 19.0, 120.0, 100.0)
VIA_R = 0.3
MARGIN = 0.06          # extra beyond the rule, mm
TOL = 1000             # position match tolerance, internal units (1 um)


def tomm(v):
    return pcbnew.ToMM(v)


def main(drc_path):
    d = json.load(open(drc_path))
    moves = []
    for v in d["violations"]:
        if v["type"] not in ("clearance", "copper_edge_clearance"):
            continue
        vias = [i for i in v["items"] if i["description"].startswith("Via")]
        others = [i for i in v["items"] if not i["description"].startswith("Via")]
        if len(vias) != 1 or not others:
            continue
        need = 0.0
        desc = v["description"]
        if "clearance" in desc and "actual" in desc:
            try:
                req = float(desc.split("clearance")[-1].split("mm")[0].strip().split()[-1])
                act = float(desc.split("actual")[-1].split("mm")[0].strip())
                need = req - act + MARGIN
            except Exception:
                need = 0.15
        vx, vy = vias[0]["pos"]["x"], vias[0]["pos"]["y"]
        if v["type"] == "copper_edge_clearance":
            # An Edge.Cuts segment reports its START point, not the nearest
            # point on it, so the vector to "the other item" points along the
            # board edge rather than away from it - which is why nudging this
            # one kept failing. Work out which edge is actually nearest and
            # push perpendicular, inward.
            x0, y0, x1, y1 = BOARD_BOX
            gaps = ((vx - x0, (1, 0)), (x1 - vx, (-1, 0)),
                    (vy - y0, (0, 1)), (y1 - vy, (0, -1)))
            gap, (ux, uy) = min(gaps, key=lambda g: g[0])
            need = 0.5 + VIA_R - gap + MARGIN
            if need <= 0:
                continue
            moves.append((vx, vy, ux * need, uy * need))
            continue
        ox, oy = others[0]["pos"]["x"], others[0]["pos"]["y"]
        dx, dy = vx - ox, vy - oy
        n = math.hypot(dx, dy)
        if n < 1e-6:
            dx, dy, n = 0.0, 1.0, 1.0
        moves.append((vx, vy, dx / n * need, dy / n * need))

    board = pcbnew.LoadBoard(BOARD)
    tracks = list(board.GetTracks())
    moved = 0
    for vx, vy, ddx, ddy in moves:
        target = pcbnew.VECTOR2I(pcbnew.FromMM(vx), pcbnew.FromMM(vy))
        delta = pcbnew.VECTOR2I(pcbnew.FromMM(ddx), pcbnew.FromMM(ddy))
        via = None
        for t in tracks:
            if t.GetClass() != "PCB_VIA":
                continue
            p = t.GetPosition()
            if abs(p.x - target.x) < TOL and abs(p.y - target.y) < TOL:
                via = t
                break
        if via is None:
            continue
        # Move every track endpoint sitting on this via by the same delta,
        # otherwise the via slides out from under its own connections.
        for t in tracks:
            if t.GetClass() == "PCB_VIA":
                continue
            s, e = t.GetStart(), t.GetEnd()
            if abs(s.x - target.x) < TOL and abs(s.y - target.y) < TOL:
                t.SetStart(pcbnew.VECTOR2I(s.x + delta.x, s.y + delta.y))
            if abs(e.x - target.x) < TOL and abs(e.y - target.y) < TOL:
                t.SetEnd(pcbnew.VECTOR2I(e.x + delta.x, e.y + delta.y))
        via.SetPosition(pcbnew.VECTOR2I(target.x + delta.x, target.y + delta.y))
        moved += 1
        print(f"  via at ({vx:7.3f},{vy:7.3f}) moved by "
              f"({ddx:+.3f},{ddy:+.3f}) mm")

    pcbnew.SaveBoard(BOARD, board)
    print(f"vias nudged : {moved}/{len(moves)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
