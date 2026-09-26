#!/usr/bin/env python3
"""
Stitch the pour nets to their planes - with a collision model that is correct.

The autorouter carves the GND / CAN_GND / VCC_3V3 pours into fragments. A
fragment holding a pad but no via cannot reach its plane, and DRC reports it.
The cure is a via per pad plus a coarse grid; the earlier attempts did that but
kept introducing shorts, because the model was wrong in three ways:

  * pads were circles of max(w,h)/2 rather than rectangles;
  * only F.Cu and B.Cu were checked, yet a THROUGH via passes through In1/In2
    as well (this is exactly how a via landed on a USB_CC2 track on In2);
  * hole-to-hole spacing was never considered at all, only copper clearance.

All three are handled here, reusing the router's geometry helpers so there is
one implementation rather than two that disagree.
"""
import os as _os
_REPO = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import sys

import pcbnew

sys.path.insert(0, _REPO + "/hardware/scripts")
import route_residual as R  # noqa: E402

BOARD = R.BOARD
VIA_DIA, VIA_DRILL = 0.6, 0.3
CLEAR = 0.25
HOLE_CLEAR = 0.30          # board rule is 0.25; take a little margin
POUR_NETS = ("GND", "CAN_GND", "CHASSIS", "VCC_3V3")
RINGS = (0.75, 0.95, 1.15, 1.4, 1.7, 2.1, 2.6)
ANGLES = 36
GRID_PITCH = 7.0
REGIONS = [
    ("GND",      20.5, 19.5, 119.5, 66.0),
    ("GND",      80.5, 66.0, 119.5, 80.5),
    ("CAN_GND",  20.5, 73.5,  80.5, 99.5),
    ("CHASSIS",  82.5, 83.5, 113.5, 99.0),
]


def tomm(v):
    return pcbnew.ToMM(v)


def net_by_suffix(board, suffix):
    """Nets are sheet-prefixed; an exact match wins over a suffix match."""
    names = [str(n) for n in board.GetNetsByName().keys()]
    if suffix in names:
        return board.FindNet(suffix)
    hits = [n for n in names if n.endswith("/" + suffix)]
    return board.FindNet(hits[0]) if hits else None


def collect_holes(board):
    """(x, y, drill_radius) for every drilled feature - pads and vias alike."""
    holes = []
    for fp in board.GetFootprints():
        for p in fp.Pads():
            d = p.GetDrillSize()
            if d.x > 0:
                pos = p.GetPosition()
                holes.append((tomm(pos.x), tomm(pos.y),
                              max(tomm(d.x), tomm(d.y)) / 2))
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            pos = t.GetPosition()
            holes.append((tomm(pos.x), tomm(pos.y), tomm(t.GetDrill()) / 2))
    return holes


def hole_ok(cx, cy, holes):
    r = VIA_DRILL / 2
    for hx, hy, hr in holes:
        if (cx - hx) ** 2 + (cy - hy) ** 2 < (r + hr + HOLE_CLEAR) ** 2:
            return False
    return True


def via_ok(cx, cy, nc, obs, holes):
    # A through via must clear copper on EVERY layer, and every hole by drill.
    return (R.seg_ok((cx, cy), (cx, cy), nc, VIA_DIA, obs, CLEAR)
            and hole_ok(cx, cy, holes))


def place(board, net, cx, cy, obs, holes):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(cx), pcbnew.FromMM(cy)))
    v.SetWidth(pcbnew.FromMM(VIA_DIA))
    v.SetDrill(pcbnew.FromMM(VIA_DRILL))
    v.SetViaType(pcbnew.VIATYPE_THROUGH)
    v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
    v.SetNet(net)
    board.Add(v)
    obs.append(("circ", net.GetNetCode(), (cx, cy, VIA_DIA / 2)))
    holes.append((cx, cy, VIA_DRILL / 2))


def main():
    board = pcbnew.LoadBoard(BOARD)
    obs = R.collect(board, pcbnew.F_Cu, include_inner=True) + \
        [o for o in R.collect(board, pcbnew.B_Cu) if o[0] == "seg"]
    holes = collect_holes(board)

    nets = {}
    for suffix in POUR_NETS:
        n = net_by_suffix(board, suffix)
        if n is not None:
            nets[n.GetNetCode()] = n

    # 1. A via beside every pad on a pour net that has none nearby.
    per_pad = 0
    for fp in board.GetFootprints():
        for p in fp.Pads():
            nc = p.GetNetCode()
            if nc not in nets:
                continue
            pos = p.GetPosition()
            px, py = tomm(pos.x), tomm(pos.y)
            near = any(nc2 == nc and (g[0] - px) ** 2 + (g[1] - py) ** 2 < 2.0 ** 2
                       for k, nc2, g in obs if k == "circ")
            if near:
                continue
            import math
            spot = None
            for r in RINGS:
                for i in range(ANGLES):
                    a = 2 * math.pi * i / ANGLES
                    cx, cy = px + r * math.cos(a), py + r * math.sin(a)
                    if via_ok(cx, cy, nc, obs, holes):
                        spot = (cx, cy)
                        break
                if spot:
                    break
            if spot:
                place(board, nets[nc], spot[0], spot[1], obs, holes)
                per_pad += 1

    # 2. A coarse grid so large pour areas are tied down as well.
    grid = 0
    for suffix, x0, y0, x1, y1 in REGIONS:
        net = net_by_suffix(board, suffix)
        if net is None:
            continue
        nc = net.GetNetCode()
        gy = y0 + GRID_PITCH / 2
        while gy < y1:
            gx = x0 + GRID_PITCH / 2
            while gx < x1:
                if via_ok(gx, gy, nc, obs, holes):
                    place(board, net, gx, gy, obs, holes)
                    grid += 1
                gx += GRID_PITCH
            gy += GRID_PITCH

    pcbnew.SaveBoard(BOARD, board)
    print(f"per-pad vias : {per_pad}")
    print(f"grid vias    : {grid}")
    print(f"total added  : {per_pad + grid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
