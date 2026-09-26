#!/usr/bin/env python3
"""
Verify the safety-critical copper gaps by MEASURING the poured copper.

The zone outlines are drawn to create the isolation barrier and the chassis
moat geometrically, but "drawn correctly" is not "poured correctly": KiCad's
filler applies its own clearances, thermal reliefs and min-thickness pruning.
This loads the finished board and checks the actual filled polygons.

Method: boolean-intersect the filled copper against the forbidden region. Any
non-zero area is a real violation, in mm^2, not a heuristic.
"""
import os as _os
_REPO = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import sys

import pcbnew

BOARD = _REPO + "/hardware/dbcanary.kicad_pcb"
BAR_TOP, BAR_BOT, BAR_RIGHT = 66.5, 73.5, 80.5
MOAT = 2.03
CHASSIS_ISLAND = (82.03, 83.03, 113.97, 99.5)


def poly(pts):
    s = pcbnew.SHAPE_POLY_SET()
    s.NewOutline()
    for x, y in pts:
        s.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
    return s


def rect(x0, y0, x1, y1):
    return poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def area_in(fill, region):
    a = pcbnew.SHAPE_POLY_SET(fill)
    a.BooleanIntersection(region)
    return a.Area() / 1e12


def main():
    board = pcbnew.LoadBoard(BOARD)
    barrier = rect(20.0, BAR_TOP, BAR_RIGHT, BAR_BOT)
    moat = rect(CHASSIS_ISLAND[0] - MOAT, CHASSIS_ISLAND[1] - MOAT,
                CHASSIS_ISLAND[2] + MOAT, CHASSIS_ISLAND[3])

    rows, bad = [], 0
    for z in board.Zones():
        if z.GetIsRuleArea():
            rows.append((z.GetZoneName(), "rule area", "", "", ""))
            continue
        name = z.GetZoneName()
        net = z.GetNetname().split("/")[-1]
        for lay in z.GetLayerSet().CuStack():
            fill = z.GetFilledPolysList(lay)
            if fill.Area() == 0:
                continue
            a_tot = fill.Area() / 1e12
            a_bar = area_in(fill, barrier)
            # Only system-side nets must respect the chassis moat.
            a_moat = area_in(fill, moat) if net in ("GND", "VCC_3V3") else 0.0
            flag = ""
            if a_bar > 0.001:
                flag += f" BARRIER+{a_bar:.2f}mm2"
                bad += 1
            if a_moat > 0.001:
                flag += f" MOAT+{a_moat:.2f}mm2"
                bad += 1
            rows.append((name, board.GetLayerName(lay), net,
                         f"{a_tot:8.1f} mm2", flag))

    w = max(len(r[0]) for r in rows)
    for r in rows:
        print(f"  {r[0]:<{w}}  {r[1]:<10} {r[2]:<10} {r[3]:>11} {r[4]}")
    print(f"\nisolation barrier ({BAR_BOT - BAR_TOP:.1f} mm) and "
          f"chassis moat ({MOAT} mm) violations: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
