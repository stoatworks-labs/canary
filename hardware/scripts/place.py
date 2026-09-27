#!/usr/bin/env python3
"""
CANary rev A — board resize + component placement.

Run with KiCad's bundled Python so `pcbnew` is importable:
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 place.py

Why pcbnew and not hand-editing: .kicad_pcb is a serialised object graph with
UUIDs and cross-references. pcbnew is KiCad's own parser/serialiser — the same one
its plugins use — so structure and UUIDs are preserved. Never text-edit the board.

FLOORPLAN RATIONALE
-------------------
Board is 100 x 80 mm. That is not "as small as possible" by area, but JLCPCB's
cheapest tier is <=100 x 100 mm, so 100 x 80 costs exactly the same as a tighter
92 x 72 while making the layout far easier. Two hard constraints drive it:

  * The ESP32-S3-WROOM-1 footprint carries an ALL-LAYER copper keepout of
    48 x 21 mm on its antenna side. It is placed so that keepout falls off the
    top board edge entirely, with the module antenna overhanging.
  * Three etherCON jacks need ~78 mm of one edge. Their front plates are 25 mm
    wide but the FOOTPRINT COURTYARD IS ONLY ~14.4 mm, so DRC will NOT catch them
    physically colliding. They are spaced 28 mm apart by hand for that reason.

Domains, left to right along the bottom edge:
    CAN_GND (isolated)      |    GND / CHASSIS
    J201, J202 + ADM3053    |    W5500 + magnetics + J401
The ADM3053 straddles the barrier, logic side up, isolated side down.
"""
import os as _os
_REPO = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import sys
import pcbnew

BOARD = _REPO + "/hardware/canary.kicad_pcb"

# Board outline, mm. JLCPCB cheap tier is <=100x100.
# Top edge is y=19, not 20: buys 1 mm of copper-to-edge clearance for J102's
# USB-C pads (0.23 mm actual vs a 0.5 mm rule) WITHOUT pulling the connector
# inward, so its mating face stays at the board edge where a cable can reach.
# Board is then 100 x 81 mm - still inside JLCPCB's <=100x100 price tier.
X0, Y0, X1, Y1 = 20.0, 19.0, 120.0, 100.0

# etherCON jacks: real front plate is 25 mm wide, courtyard is not. Space by hand.
JACK_Y = 92.0             # jack courtyard then spans y 84..100, at the bottom edge
JACK_ROT = 180.0          # pads point INTO the board; front plate faces the edge

# ref: (x, y, rotation)
#
# U301 sits at x=54 rather than centred: its all-layer antenna keepout is 48 mm
# wide (x = origin +/- 24), and at x=48 that swallowed the left edge where the
# status LEDs live. At x=54 the keepout spans x 30..78, leaving x 20..30 clear.
PLACEMENT = {
    # ---- MCU. Antenna keepout (48 x 21) falls off the top edge entirely.
    "U301": (54.0, 26.5, 0),
    "C301": (66.0, 45.0, 0), "C302": (69.0, 45.0, 0), "C303": (72.0, 45.0, 0),

    # ---- USB-C + PD sink, top right. CC lines stay short to J102.
    "J102": (106.0, 25.0, 0),
    "F101": (116.0, 31.0, 90),
    "C107": (98.0, 30.0, 0), "C108": (102.0, 30.0, 0),
    "U104": (105.0, 37.0, 0),
    "R106": (112.0, 36.0, 0), "R107": (115.0, 36.0, 0), "C109": (118.0, 36.0, 0),

    # ---- Buck 5V -> 3V3, right side below the USB block.
    "U103": (106.0, 46.0, 0),
    "L102": (115.0, 46.0, 0),
    "C105": (99.0, 44.0, 0),
    "C106": (115.0, 53.0, 0),
    "R103": (106.0, 52.0, 0), "R104": (110.0, 52.0, 0),

    # ---- Ethernet: W5500 -> magnetics -> LAN jack, stacked toward the bottom edge.
    "U401": (88.0, 60.0, 0),
    "Y401": (77.0, 58.0, 90),
    "C401": (77.0, 53.0, 0), "C402": (77.0, 63.0, 0),
    "R401": (80.8, 61.8, 0),   # 3.0 mm from the EXRES1 pin (rule: <=7 mm)
    # Crystal feedback + XO series damping, clustered at Y401.
    "R411": (72.0, 58.0, 0), "R412": (72.0, 62.0, 0),
    "C403": (98.0, 58.0, 0), "C404": (98.0, 61.0, 0), "C405": (98.0, 64.0, 0),
    "C406": (98.0, 67.0, 0), "C407": (98.0, 70.0, 0),
    "C408": (81.0, 53.0, 0), "C409": (84.0, 53.0, 0), "C410": (81.0, 64.0, 0),
    # MDI termination: 49.9R from each pair leg to its centre tap. WIZnet wants
    # these hard against the transformer on the system-ground side, so they sit
    # in the gap between U401's courtyard (ends y=63.2) and T401's (starts 67.3).
    "R406": (84.0, 66.8, 0), "R407": (87.0, 66.8, 0),
    "R408": (90.0, 66.8, 0), "R409": (93.0, 66.8, 0),
    # Centre-tap bias/decoupling, right of the magnetics.
    "R410": (96.0, 74.0, 0), "C412": (96.0, 77.0, 0), "C413": (96.0, 80.0, 0),
    "T401": (88.0, 75.0, 0),
    # Bob Smith termination, left of the magnetics.
    "R402": (102.0, 86.0, 90), "R403": (102.0, 90.0, 90),
    "R404": (105.0, 86.0, 90), "R405": (105.0, 90.0, 90),
    "C411": (108.0, 88.0, 90),
    "J401": (92.0, JACK_Y, JACK_ROT),

    # ---- Isolated CAN. U201 straddles the barrier at y=70; rotation set by
    #      measurement so the isolated pins face the CAN jacks below.
    "U201": (47.0, 70.0, 90),
    # logic side, above the barrier
    "C201": (40.0, 60.0, 0), "C202": (44.0, 60.0, 0), "C203": (48.0, 60.0, 0),
    # isolated side, below the barrier
    # These are VISO / CAN_GND parts, so they MUST sit below the barrier. U201's
    # isolated pads are at y=74.65; at the previous y=68 they were on the LOGIC
    # side and their nets would have had to cross the isolation barrier.
    # Positions come from auto_place() below, anchored to U201's isolated pads.
    "FB201": None, "C204": None, "C205": None, "C206": None,
    "R201": (56.0, 76.0, 0),
    "D201": (60.0, 76.0, 0),
    "R202": (48.0, 78.0, 90), "R203": (52.0, 78.0, 90),
    "C207": None,
    "SW201": (30.0, 76.5, 0),          # field control - must stay reachable
    "J201": (36.0, JACK_Y, JACK_ROT),
    "J202": (64.0, JACK_Y, JACK_ROT),

    # ---- UI on the left edge, clear of the antenna keepout (which starts at x=30).
    "D301": (23.5, 26.0, 90), "D302": (23.5, 30.0, 90),
    "D303": (23.5, 34.0, 90), "D304": (23.5, 38.0, 90),
    "R302": (27.0, 26.0, 90), "R303": (27.0, 30.0, 90),
    "R304": (27.0, 34.0, 90), "R305": (27.0, 38.0, 90),
    "SW301": (28.0, 48.0, 0), "SW302": (28.0, 58.0, 0),
    "R301": (36.0, 47.0, 0), "C304": (36.0, 51.0, 0),
    "J301": (60.0, 57.0, 0),
}


# Parts whose position is solved rather than hard-coded: they must land in the
# isolated domain, as close to U201's isolated pads as free space allows.
AUTO = {
    "FB201": ("U201-iso", 20.0, 80.0),
    "C204":  ("U201-iso", 20.0, 80.0),
    "C205":  ("U201-iso", 20.0, 80.0),
    "C206":  ("U201-iso", 20.0, 80.0),
    "C207":  ("U201-iso", 20.0, 80.0),
}


def auto_place(board, fps, barrier_y):
    """
    Grid-search a free spot for each AUTO part, nearest-first to its anchor.

    Guessing coordinates by eye kept producing courtyard collisions, because a
    courtyard is not the pad extent and rotation changes it. This measures.
    """
    anchor_fp = fps["U201"]
    iso_pads = [p for p in anchor_fp.Pads() if int(p.GetPadName()) >= 11]
    ax = sum(pcbnew.ToMM(p.GetPosition().x) for p in iso_pads) / len(iso_pads)
    ay = sum(pcbnew.ToMM(p.GetPosition().y) for p in iso_pads) / len(iso_pads)

    placed = []
    for ref, (_anchor, xlo, xhi) in AUTO.items():
        fp = fps[ref]
        best = None
        for gy in [barrier_y + 4.0 + 2.0 * i for i in range(6)]:
            for gx in [xlo + 1.0 * i for i in range(int((xhi - xlo)))]:
                fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(gx), pcbnew.FromMM(gy)))
                box = fp.GetCourtyard(pcbnew.F_CrtYd).BBox()
                box.Inflate(pcbnew.FromMM(0.15))
                clash = False
                for other in board.GetFootprints():
                    if other.GetReference() == ref:
                        continue
                    ob = other.GetCourtyard(pcbnew.F_CrtYd).BBox()
                    if ob.GetWidth() and ob.Intersects(box):
                        clash = True
                        break
                if clash:
                    continue
                d = (gx - ax) ** 2 + (gy - ay) ** 2
                if best is None or d < best[0]:
                    best = (d, gx, gy)
        if best is None:
            raise SystemExit(f"auto_place: no free spot for {ref}")
        _d, bx, by = best
        fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(bx), pcbnew.FromMM(by)))
        placed.append((ref, bx, by, _d ** 0.5))
    return placed


def set_outline(board):
    """Replace Edge.Cuts with a fresh rectangle."""
    for d in list(board.GetDrawings()):
        if d.GetLayer() == pcbnew.Edge_Cuts:
            board.Remove(d)
    pts = [(X0, Y0), (X1, Y0), (X1, Y1), (X0, Y1)]
    for i in range(4):
        seg = pcbnew.PCB_SHAPE(board)
        seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
        seg.SetLayer(pcbnew.Edge_Cuts)
        seg.SetWidth(pcbnew.FromMM(0.1))
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % 4]
        seg.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(ax), pcbnew.FromMM(ay)))
        seg.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(bx), pcbnew.FromMM(by)))
        board.Add(seg)


def footprints_by_ref(board):
    """
    Map reference -> FOOTPRINT.

    Deliberately NOT FindFootprintByReference(): in this KiCad 10 SWIG build that
    returns an untyped SwigPyObject with no methods. Iterating GetFootprints()
    yields properly typed objects.
    """
    return {f.GetReference(): f for f in board.GetFootprints()}


def orient_isolator(fps):
    """
    Rotate U201 so the isolated pins (11-20, CAN_GND) sit BELOW the logic pins
    (1-10, GND) — i.e. facing the CAN jacks on the bottom edge.

    Determined by measurement rather than by reasoning about rotation sign, which
    is easy to get backwards in a y-down coordinate system.
    """
    fp = fps["U201"]
    for rot in (90.0, 270.0):
        fp.SetOrientationDegrees(rot)
        y_logic = fp.FindPadByNumber("1").GetPosition().y
        y_iso = fp.FindPadByNumber("11").GetPosition().y
        if y_iso > y_logic:                      # +y is down => isolated below
            return rot, pcbnew.ToMM(y_logic), pcbnew.ToMM(y_iso)
    raise SystemExit("could not orient U201 isolation barrier")


def report(board, fps_map):
    """Verify placement: courtyard overlaps and anything outside the outline."""
    tomm = pcbnew.ToMM
    fps = list(board.GetFootprints())

    outside = []
    for f in fps:
        for p in f.Pads():
            pos = p.GetPosition()
            x, y = tomm(pos.x), tomm(pos.y)
            if not (X0 + 0.5 <= x <= X1 - 0.5 and Y0 + 0.5 <= y <= Y1 - 0.5):
                outside.append((f.GetReference(), p.GetPadName(), round(x, 2), round(y, 2)))
                break

    boxes = []
    for f in fps:
        cy = f.GetCourtyard(pcbnew.F_CrtYd)
        bb = cy.BBox()
        if bb.GetWidth() == 0:
            continue
        boxes.append((f.GetReference(), bb))
    overlaps = []
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i][1], boxes[j][1]
            if a.Intersects(b):
                overlaps.append((boxes[i][0], boxes[j][0]))

    # etherCON front plates are 25mm but the courtyard is ~14.4mm: check by hand.
    jacks = [(r, fps_map[r]) for r in ("J201", "J202", "J401")]
    jack_gaps = []
    for i in range(len(jacks)):
        for j in range(i + 1, len(jacks)):
            dx = abs(tomm(jacks[i][1].GetPosition().x) - tomm(jacks[j][1].GetPosition().x))
            jack_gaps.append((jacks[i][0], jacks[j][0], round(dx, 1), "OK" if dx >= 26 else "TOO CLOSE"))

    return outside, overlaps, jack_gaps


def main():
    board = pcbnew.LoadBoard(BOARD)

    # NOTE: do all FOOTPRINT work BEFORE creating PCB_SHAPEs. In this KiCad 10
    # SWIG build, constructing PCB_SHAPE objects destabilises SWIG's type
    # resolution and subsequent GetFootprints() calls return untyped
    # SwigPyObjects with no methods. Order matters; this is not cosmetic.
    fps_map = footprints_by_ref(board)

    missing = []
    for ref, pos in PLACEMENT.items():
        fp = fps_map.get(ref)
        if fp is None:
            missing.append(ref)
            continue
        if pos is None:                  # solved by auto_place() after U201 is oriented
            continue
        x, y, rot_ = pos
        fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
        fp.SetOrientationDegrees(float(rot_))

    rot, y_logic, y_iso = orient_isolator(fps_map)
    solved = auto_place(board, fps_map, (y_logic + y_iso) / 2)
    unplaced = sorted(set(fps_map) - set(PLACEMENT))

    set_outline(board)          # must come last - see note above
    pcbnew.SaveBoard(BOARD, board)

    print(f"board      : {X1-X0:.0f} x {Y1-Y0:.0f} mm")
    print(f"placed     : {len(PLACEMENT) - len(missing)}/{len(fps_map)}")
    print(f"U201       : rot {rot:.0f} deg, logic pin1 y={y_logic:.2f}, "
          f"isolated pin11 y={y_iso:.2f} (isolated below -> faces CAN jacks)")
    if missing:
        print(f"MISSING    : {missing}")
    for ref, sx, sy, dist in solved:
        print(f"auto-place : {ref:<6} -> ({sx:.1f}, {sy:.1f})  {dist:.1f} mm from U201 iso pads")
    if unplaced:
        print(f"UNPLACED   : {unplaced}")


if __name__ == "__main__":
    main()
