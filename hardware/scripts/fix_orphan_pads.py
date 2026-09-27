#!/usr/bin/env python3
"""
v3 of the orphan-pad fix: same intent as fix_orphan_pads.py, re-dimensioned
for the board's REAL clearance rule, which DRC enforces at 0.20 mm (the
0.150 in ORDERING.md is the fab's capability, not this board's netclass).

v2 failed DRC by 0.001-0.009 mm in four places, all of them around the
ETH_TOCAP descent from U401.20: the GND stitch via at (89.34, 65.46) sits
0.59 mm from the pad-20 column, and 0.60 was needed. That via has no tracks
(verified: pure stitching), so it MOVES 0.26 mm east to (89.60, 65.46), and
TOCAP then descends straight down x 88.75 with 0.85 mm to spare.

Final geometry (all F.Cu 0.20 wide, 0.20 clearance rule, >=0.23 designed):
  ETH_TOCAP  (88.75,64.99) -> (88.75,65.68) -> (81.48,65.68)
             -> (80.45,64.35)  [inside C410.1. The turn stays at the
             original x 81.48: turning at 82.36 clipped C410.2's SW corner,
             and extending the lane to x 81.10 ran into the net-5 diagonal
             climbing NE at (79.46,64.50)-(81.76,66.80)]
  GND ribbon (88.25,65.24) -> (84.60,65.24) -> (84.08,64.46)  [stitch via]
  GND risers into U401 pads 16 and 19 down to the ribbon
  J301.1     B.Cu (60,57) -> (62.83,46.07) - placed by v2, kept as-is

Deletes v2's TOCAP/ribbon attempt first, matched by exact endpoints.
"""
import os as _os
_REPO = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import math
import sys

import pcbnew

sys.path.insert(0, _REPO + "/hardware/scripts")
import route_residual as rr

BOARD = _REPO + "/hardware/canary.kicad_pcb"
F, B = pcbnew.F_Cu, pcbnew.B_Cu

DELETE = [  # v2 attempt, exact endpoints
    ((88.75, 64.99), (88.75, 65.38)), ((88.75, 65.38), (88.39, 65.74)),
    ((88.39, 65.74), (82.36, 65.74)), ((82.36, 65.74), (80.67, 64.24)),
    ((80.67, 64.24), (80.22, 64.00)),
    ((88.30, 65.27), (84.60, 65.27)), ((84.60, 65.27), (84.08, 64.46)),
    ((86.75, 64.70), (86.75, 65.27)), ((88.25, 64.70), (88.25, 65.27)),
]
MOVE_VIA = ((89.34, 65.46), (89.60, 65.46))

NEW = [
    ("TOCAP v3", "ETH_TOCAP", F, 0.20,
     [(88.75, 64.99), (88.75, 65.68), (81.48, 65.68), (80.45, 64.35)]),
    ("GND ribbon", "GND", F, 0.20,
     [(88.25, 65.24), (84.60, 65.24), (84.08, 64.46)]),
    ("GND riser p16", "GND", F, 0.20, [(86.75, 64.70), (86.75, 65.24)]),
    ("GND riser p19", "GND", F, 0.20, [(88.25, 64.70), (88.25, 65.24)]),
]


def near(p, q, tol=0.02):
    return math.hypot(p[0] - q[0], p[1] - q[1]) < tol


def main():
    board = pcbnew.LoadBoard(BOARD)
    tomm = pcbnew.ToMM

    doomed = []
    via_to_move = None
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            p = t.GetPosition()
            if near((tomm(p.x), tomm(p.y)), MOVE_VIA[0]):
                via_to_move = t
            continue
        s, e = t.GetStart(), t.GetEnd()
        sp, ep = (tomm(s.x), tomm(s.y)), (tomm(e.x), tomm(e.y))
        for a, bpt in DELETE:
            if (near(sp, a) and near(ep, bpt)) or (near(sp, bpt) and near(ep, a)):
                doomed.append(t)
                break
    if via_to_move is None:
        raise SystemExit("stitch via not found")
    if len(doomed) != len(DELETE):
        raise SystemExit("expected %d segments to delete, found %d" %
                         (len(DELETE), len(doomed)))

    # Obstacles: collect, then drop doomed segs and the via being moved;
    # re-add the via at its new position.
    def keyof(g):
        return (round(g[0], 2), round(g[1], 2), round(g[2], 2), round(g[3], 2))
    doomed_keys = set()
    for a, bpt in DELETE:
        doomed_keys.add((round(a[0], 2), round(a[1], 2), round(bpt[0], 2), round(bpt[1], 2)))
        doomed_keys.add((round(bpt[0], 2), round(bpt[1], 2), round(a[0], 2), round(a[1], 2)))

    def build_obs(layer):
        out = []
        for kind, nc, g in rr.collect(board, layer):
            if kind == "seg" and keyof(g) in doomed_keys:
                continue
            if kind == "circ" and near((g[0], g[1]), MOVE_VIA[0]):
                g = (MOVE_VIA[1][0], MOVE_VIA[1][1], g[2])
            out.append((kind, nc, g))
        return out

    obs = {F: build_obs(F)}

    def find_net(suffix):
        for code in range(1, board.GetNetCount()):
            ni = board.FindNet(code)
            if ni and ni.GetNetname().split("/")[-1] == suffix:
                return ni
        raise SystemExit("net not found: " + suffix)

    failed = []
    for name, suffix, layer, width, pts in NEW:
        nc = find_net(suffix).GetNetCode()
        for k in range(len(pts) - 1):
            if not rr.seg_ok(pts[k], pts[k + 1], nc, width, obs[layer], 0.195):
                failed.append("%s (%.2f,%.2f)-(%.2f,%.2f): %s" % (
                    name, pts[k][0], pts[k][1], pts[k + 1][0], pts[k + 1][1],
                    rr.why_blocked(pts[k], pts[k + 1], nc, width, obs[layer], 0.195)))
                break
        else:
            for k in range(len(pts) - 1):
                obs[layer].append(("seg", nc, (pts[k][0], pts[k][1],
                                               pts[k + 1][0], pts[k + 1][1],
                                               width / 2)))
    if failed:
        for f in failed:
            print("BLOCKED " + f)
        print("NOT saved")
        return 1

    for t in doomed:
        board.Remove(t)
    via_to_move.SetPosition(pcbnew.VECTOR2I(rr.mm(MOVE_VIA[1][0]),
                                            rr.mm(MOVE_VIA[1][1])))
    print("deleted %d v2 segments; moved stitch via to (%.2f,%.2f)" %
          (len(doomed), MOVE_VIA[1][0], MOVE_VIA[1][1]))
    for name, suffix, layer, width, pts in NEW:
        net = find_net(suffix)
        for k in range(len(pts) - 1):
            rr.add_track(board, net, pts[k], pts[k + 1], width, layer)
        print("added %-14s w%.2f  %s" %
              (name, width, " ".join("(%.2f,%.2f)" % p for p in pts)))
    pcbnew.SaveBoard(BOARD, board)
    print("saved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
