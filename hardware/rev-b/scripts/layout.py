#!/usr/bin/env python3
"""
Rev B placement on rev A's routed board: put the new parts down, clear the
copper they displace, and leave the new connections for route.py.

    <kicad python> hardware/rev-b/scripts/layout.py place   # positions, U301 courtyard, keep-outs
    <kicad python> hardware/rev-b/scripts/layout.py strip   # removes displaced copper (own process)
    <kicad python> hardware/rev-b/scripts/layout.py check   # courtyards and pads, read-only

Run after sync.py. Each stage is its own process because pcbnew loses its type
registry after a Remove(). Rev A's copper stays where it was except:

- stitching vias (GND, CAN_GND, CHASSIS) inside a new part's courtyard, a hole's
  keep-out ring or the PoE keep-out;
- VCC_5V's F.Cu run from C108 to the via at (80.5, 42.8), which crossed where
  J501 now stands; route.py routes VCC_5V again;
- the old VCC_5V copper between F101 and R106/R107, which becomes VBUS_FUSED
  (the USB side of the U105 power mux), and the one segment that joined it to
  the rest of VCC_5V, which goes: U105 now feeds VCC_5V instead;
- every BOB_SMITH track and the last ETH_CT_RD segment to R403: each Bob Smith
  75R gets its own DC-blocking capacitor for PoE, wired by route.PREROUTES.

The PoE block lives in the bottom-right corner: U402 stands on end beside
T401 with its 57 V input pins on the board edge, the bridges and TVS below it.
KEEPOUT_POE keeps every pour, on every layer, off the primary side. U402 is
the isolation barrier, and nothing on GND or CHASSIS may fill up to its input.

U301's courtyard was the stock WROOM-1 one, a 48 x 41 mm box: the antenna's
15 mm side clearance carried all the way down the module. Here it is the
antenna strip at full width plus the module body. The antenna keep-out rule
area inside the footprint is unchanged.
"""
import math
import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
BOARD = os.path.normpath(os.path.join(HERE, "..", "canary.kicad_pcb"))
REVA = os.path.normpath(os.path.join(HERE, "..", "..", "canary.kicad_pcb"))
MM = pcbnew.FromMM

# ref: (x, y, rotation) of the footprint origin: the centre for SMD parts,
# pad 1 for the pin headers.
PLACE = {
    # front-panel header: SMD so the B.Cu USB pair and PD_PG run on beneath
    # it. Turned 180 degrees: pin 1 at the bottom, so the I2C and FN pins
    # (13-16) come out at the top beside their resistors, and the LED and BOOT
    # pins at the bottom beside the sinks.
    "J501": (89.4, 34.35, 180),
    # I2C and FN conditioning, beside U301's IO1/IO2 and IO38/IO39 pads. The
    # pull-ups are turned round so every GPIO-side pin faces the module and
    # every 3V3 or front-panel pin faces away from it.
    "R510": (67.0, 21.2, 0), "R508": (67.0, 22.6, 180),
    "R511": (67.0, 24.0, 0), "R509": (67.0, 25.4, 180),
    "R507": (67.0, 30.6, 0), "R505": (67.0, 32.0, 180),
    "R506": (67.0, 33.4, 0), "R504": (67.0, 34.8, 180),
    "R502": (67.0, 37.0, 0), "R503": (67.0, 38.4, 180),   # BOOT pins one above the other
    # EN series and its jumper at the top, then the LED sinks in the order
    # their B.Cu lanes arrive from under U301 (route.PREROUTES): LAN, ERR, CAN
    "R501": (72.5, 21.4, 0), "JP501": (75.9, 21.4, 0),
    "U502": (72.5, 24.4, 0), "C502": (75.6, 24.4, 90),
    "U504": (72.5, 27.6, 0), "C504": (75.6, 27.6, 90),
    "U503": (72.5, 30.8, 0), "C503": (75.6, 30.8, 90),
    "U501": (72.5, 34.0, 0), "C501": (75.6, 34.0, 90),
    # U505 (I2C, FN, RESET) at the top beside J501's pins 9-16, the
    # polyfuses below it beside pins 1-2
    "U505": (80.15, 22.5, 0),
    "F502": (80.4, 31.0, 90), "F501": (80.4, 36.0, 90),
    # U506 (LED sinks, BOOT) under the sinks. Both arrays at rotation 0 so
    # each pin leaves sideways: at 90 they faced row to row and boxed in their
    # middle pins.
    "U506": (76.9, 37.6, 0),
    # USB data pads, between J501 and J102
    "J502": (98.8, 21.6, 0),
    # TPS2116 power mux in the pocket below the CH224K's PD traces: F101's
    # output reaches it on B.Cu, and its output joins VCC_5V through a via on
    # rev A's In2 VCC_5V run (route.PREROUTES). C110 is its USB-side input cap,
    # C112 the EXT_5V one, R108/R109 the priority threshold.
    "U105": (115.6, 40.3, 180), "C110": (115.2, 38.2, 0),
    "R108": (118.4, 39.35, 180), "R109": (118.4, 38.25, 0), "C112": (117.6, 41.2, 270),
    # auxiliary 5 V input: the header beside U103, its fuse, TVS and ideal
    # diode in the strip above U402, next to the EXT_5V node they feed
    "J103": (101.3, 46.6, 0), "D105": (109.7, 48.7, 90),
    "C419": (96.4, 54.5, 0), "C418": (99.75, 54.5, 180), "U106": (103.7, 54.5, 180),
    "C111": (105.8, 54.5, 90), "F102": (108.7, 54.5, 180),
    # PoE: U402 on end, input pins (5-8) along the board edge over the plane
    # cut-out, output pins (1-4) on the GND side; bridges with their AC pins
    # facing the Bob Smith network, TVS below them
    "U402": (109.6, 67.1, 270),
    "D401": (114.0, 80.7, 180), "D402": (114.0, 86.1, 180), "D403": (114.0, 90.6, 0),
    # Bob Smith DC blocks, one per 75R, each on the pad that has room
    "C414": (102.0, 83.5, 90), "C416": (105.0, 83.5, 90),
    "C415": (102.0, 92.5, 270), "C417": (106.265, 89.9, 270),
    # dbCAN pads between the two CAN etherCONs, isolated side
    "J203": (46.5, 86.5, 0), "J204": (51.5, 86.5, 0),
    # W5500 reset pull-up, near U401's RSTn
    "R413": (94.5, 51.0, 0),
    # M3 holes: NE and SW are where a flashing fixture (not in this repository)
    # asked for tooling holes
    "H501": (116.45, 22.45, 0), "H502": (23.45, 96.45, 0),
    "H503": (116.45, 96.45, 0), "H504": (75.5, 95.0, 0),
}
POUR_NETS = {"GND", "CAN_GND", "CHASSIS"}   # stitching vias on these are free to go
HOLE_KEEPOUT_R = 4.0
CORNER_HOLES = {"H501", "H502", "H503"}   # mm: an M3 head is 2.75 mm radius; this leaves air past it

# Copper that changes (rev A coordinates, mm). Segments are matched by both ends.
VBUS_FUSED = [  # F101.2 -> R106.1 / R107.1, was VCC_5V
    ((116.0, 29.6), (117.239, 30.838)), ((117.239, 30.838), (117.239, 33.013)),
    ((117.239, 33.013), (116.878, 33.373)), ((116.878, 33.373), (113.829, 33.373)),
    ((113.829, 33.373), (113.829, 35.339)), ((113.829, 35.339), (114.49, 36.0)),
    ((112.151, 35.339), (113.829, 35.339)), ((111.49, 36.0), (112.151, 35.339)),
]
DELETE = [
    ((113.829, 33.373), (105.475, 33.373)),   # joined VBUS_FUSED to VCC_5V
    ((101.52, 32.164), (91.151, 32.164)),     # VCC_5V across J501
    ((91.151, 32.164), (80.497, 42.819)),
    # BOB_SMITH: all of it, rewired through the DC-blocking capacitors
    ((105.3, 89.475), (105.0, 89.175)), ((105.778, 85.954), (105.0, 85.175)),
    ((108.0, 89.475), (105.3, 89.475)), ((102.0, 89.175), (105.0, 89.175)),
    ((105.778, 88.397), (105.778, 85.954)), ((102.0, 85.175), (105.0, 85.175)),
    ((105.0, 89.175), (105.778, 88.397)),
    # ETH_CT_RD from its via to R403, now to C415 instead
    ((103.5, 93.5), (102.0, 90.83)), ((102.0, 90.83), (102.0, 90.825)),
]

# Pours stay off the PoE primary: U402's input column, the bridges, the TVS
# and the AC links' ends. 2 mm from the input pads to GND on the west; on the
# north the edge stops short of C106's In2 via, which needs the 3V3 plane.
POE_KEEPOUT = [(112.9, 55.6), (120.05, 55.6), (120.05, 92.45), (108.4, 92.45),
               (108.4, 81.0), (107.4, 81.0), (107.4, 77.6), (112.9, 77.6)]

COURTYARD_U301 = [  # antenna strip at full width, then the module body + pads
    (29.95, -1.29), (78.05, -1.29), (78.05, 19.8), (63.75, 19.8), (63.75, 39.99),
    (44.25, 39.99), (44.25, 19.8), (29.95, 19.8),
]


def done(code=0):
    sys.stdout.flush()
    os._exit(code)


def at(x, y):
    return pcbnew.VECTOR2I(MM(x), MM(y))


def close(p, q, tol=0.002):
    return abs(pcbnew.ToMM(p.x) - q[0]) < tol and abs(pcbnew.ToMM(p.y) - q[1]) < tol


def find_segment(board, a, b):
    hits = [t for t in board.GetTracks() if t.GetClass() == "PCB_TRACK" and
            ((close(t.GetStart(), a) and close(t.GetEnd(), b)) or
             (close(t.GetStart(), b) and close(t.GetEnd(), a)))]
    if len(hits) != 1:
        sys.exit(f"segment {a} -> {b}: {len(hits)} matches, expected 1")
    return hits[0]


def place(board):
    fps = {f.GetReference(): f for f in board.GetFootprints()}
    for ref, (x, y, rot) in PLACE.items():
        f = fps[ref]
        f.SetOrientationDegrees(rot)
        f.SetPosition(at(x, y))
    print(f"placed {len(PLACE)} footprints")

    # U301's courtyard: replace the box with the outline that is actually kept clear.
    u = fps["U301"]
    old = [g for g in u.GraphicalItems() if g.GetLayer() == pcbnew.F_CrtYd]
    for g in old:
        u.Remove(g)
    for (x1, y1), (x2, y2) in zip(COURTYARD_U301, COURTYARD_U301[1:] + COURTYARD_U301[:1]):
        s = pcbnew.PCB_SHAPE(u, pcbnew.SHAPE_T_SEGMENT)
        s.SetLayer(pcbnew.F_CrtYd)
        s.SetWidth(MM(0.05))
        s.SetStart(at(x1, y1))
        s.SetEnd(at(x2, y2))
        u.Add(s)
    print(f"U301 courtyard: {len(old)} shapes replaced by an {len(COURTYARD_U301)}-point outline")

    # VBUS_FUSED copper, then a copper keep-out ring round every hole.
    code = board.FindNet(f"/Power — PoE + USB-C PD, 5V and 3V3/VBUS_FUSED").GetNetCode()
    for a, b in VBUS_FUSED:
        find_segment(board, a, b).SetNetCode(code)
    print(f"{len(VBUS_FUSED)} segments moved to VBUS_FUSED")

    # Silkscreen: new references at rev A's 0.8 mm (JLCPCB's readable floor,
    # fix_silkscreen.py), and SW201 labelled (rev B list). No arrow: the
    # footprint's F.Fab "on" mark is on the pins 3/4 side but its 3D model's
    # arrow points the other way, so which way is ON waits for board #1.
    for ref in PLACE:
        if ref.startswith("H"):
            fps[ref].Reference().SetVisible(False)
            continue
        r = fps[ref].Reference()
        r.SetTextSize(pcbnew.VECTOR2I(MM(0.8), MM(0.8)))
        r.SetTextThickness(MM(0.12))
    t = pcbnew.PCB_TEXT(board)
    t.SetText("TERM 120R = BOTH ON")
    t.SetLayer(pcbnew.F_SilkS)
    t.SetPosition(at(33.8, 74.75))
    t.SetTextSize(pcbnew.VECTOR2I(MM(0.8), MM(0.8)))
    t.SetTextThickness(MM(0.12))
    board.Add(t)

    names = {z.GetZoneName() for z in board.Zones()}
    for ref in ("H501", "H502", "H503", "H504"):
        name = f"KEEPOUT_{ref}"
        if name in names:
            continue
        x, y, _ = PLACE[ref]
        z = pcbnew.ZONE(board)
        z.SetIsRuleArea(True)
        z.SetZoneName(name)
        z.SetLayerSet(pcbnew.LSET.AllCuMask())
        z.SetDoNotAllowTracks(True)
        z.SetDoNotAllowVias(True)
        z.SetDoNotAllowPads(False)   # the NPTH itself is a pad
        z.SetDoNotAllowZoneFills(True)
        z.SetDoNotAllowFootprints(False)
        poly = pcbnew.SHAPE_POLY_SET()
        poly.NewOutline()
        r = HOLE_KEEPOUT_R
        if ref in CORNER_HOLES:
            # A ring in a corner leaves a sliver of pour between it and the
            # edges, an island with nothing on it: square it off past the edges.
            for dx, dy in ((-r, -r), (r, -r), (r, r), (-r, r)):
                poly.Append(MM(x + dx), MM(y + dy))
        else:
            for i in range(32):
                a = 2 * math.pi * i / 32
                poly.Append(MM(x + r * math.cos(a)), MM(y + r * math.sin(a)))
        poly.thisown = 0
        z.SetOutline(poly)
        board.Add(z)
    if "KEEPOUT_POE" not in names:
        z = pcbnew.ZONE(board)
        z.SetIsRuleArea(True)
        z.SetZoneName("KEEPOUT_POE")
        z.SetLayerSet(pcbnew.LSET.AllCuMask())
        z.SetDoNotAllowTracks(False)
        z.SetDoNotAllowVias(False)
        z.SetDoNotAllowPads(False)
        z.SetDoNotAllowZoneFills(True)
        z.SetDoNotAllowFootprints(False)
        poly = pcbnew.SHAPE_POLY_SET()
        poly.NewOutline()
        for x, y in POE_KEEPOUT:
            poly.Append(MM(x), MM(y))
        poly.thisown = 0
        z.SetOutline(poly)
        board.Add(z)
    print("hole and PoE keep-outs in place")


def courtyard(f):
    # GetCourtyard() is a cache, and an empty one until it is built: without
    # this every courtyard test passes because there is nothing to hit.
    f.BuildCourtyardCaches()
    c = f.GetCourtyard(pcbnew.F_CrtYd)
    return c if c.OutlineCount() else None


def strip(board):
    """Stitching vias inside a new courtyard or a keep-out, and the DELETE segments."""
    new = [board.FindFootprintByReference(r) for r in PLACE if not r.startswith("H")]
    rings = [(PLACE[r][0], PLACE[r][1]) for r in PLACE if r.startswith("H")]
    poe = pcbnew.SHAPE_POLY_SET()
    poe.NewOutline()
    for x, y in POE_KEEPOUT:
        poe.Append(MM(x), MM(y))
    doomed = [find_segment(board, a, b) for a, b in DELETE]
    # Which vias were stitching is rev A's answer, not this board's: the save
    # after placement has already handed any via under a new pad to that pad's net.
    reva = pcbnew.LoadBoard(REVA)
    stitching = {(v.GetPosition().x, v.GetPosition().y) for v in reva.GetTracks()
                 if v.GetClass() == "PCB_VIA" and v.GetNetname().split("/")[-1] in POUR_NETS}
    for v in board.GetTracks():
        if v.GetClass() != "PCB_VIA" or (v.GetPosition().x, v.GetPosition().y) not in stitching:
            continue
        p = v.GetPosition()
        x, y = pcbnew.ToMM(p.x), pcbnew.ToMM(p.y)
        r = pcbnew.ToMM(v.GetWidth(pcbnew.F_Cu)) / 2
        hit = any(max(abs(x - hx), abs(y - hy)) < HOLE_KEEPOUT_R + r for hx, hy in rings)
        hit = hit or poe.Contains(p)   # nothing left to stitch there
        for f in new:
            c = courtyard(f)
            if c and (c.Contains(p) or c.Outline(0).Collide(p, MM(r + 0.2))):
                hit = True
        if hit:
            doomed.append(v)
    for t in doomed:
        board.Remove(t)
    print(f"removed {len(DELETE)} segments and {len(doomed) - len(DELETE)} stitching vias")


def check(board):
    """Courtyard overlaps among all parts, pads over other nets' copper, the outline."""
    errors = []
    fps = list(board.GetFootprints())
    edge = board.GetBoardEdgesBoundingBox()
    cys = {f.GetReference(): courtyard(f) for f in fps}
    new = set(PLACE)
    errors += [f"{r}: no courtyard to test" for r in sorted(new) if cys.get(r) is None]
    for i, a in enumerate(fps):
        ca = cys[a.GetReference()]
        if ca is None:
            continue
        if a.GetReference() in new and not a.GetReference().startswith("H"):
            bb = ca.BBox()
            if not (edge.Contains(bb.GetOrigin()) and edge.Contains(bb.GetEnd())):
                errors.append(f"{a.GetReference()}: courtyard leaves the board")
        for b in fps[i + 1:]:
            if a.GetReference() not in new and b.GetReference() not in new:
                continue
            cb = cys[b.GetReference()]
            if cb is None:
                continue
            both = ca.CloneDropTriangulation()
            both.BooleanIntersection(cb)
            if both.Area() > 0:
                errors.append(f"courtyards {a.GetReference()} / {b.GetReference()} overlap "
                              f"{both.Area() / 1e12:.2f} mm2")
    tracks = list(board.GetTracks())
    for ref in new:
        f = board.FindFootprintByReference(ref)
        for p in f.Pads():
            shape = p.GetEffectivePolygon(pcbnew.F_Cu, pcbnew.ERROR_INSIDE)
            for t in tracks:
                if t.GetNetCode() == p.GetNetCode() and p.GetNetCode() != 0:
                    continue
                if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD and not t.IsOnLayer(pcbnew.F_Cu):
                    continue
                if t.GetClass() == "PCB_VIA":
                    hit = shape.Collide(t.GetPosition(), MM(0.2) + t.GetWidth(pcbnew.F_Cu) // 2)
                else:
                    seg = pcbnew.SEG(t.GetStart(), t.GetEnd())
                    hit = shape.Collide(seg, MM(0.2) + t.GetWidth() // 2)
                if hit:
                    errors.append(f"{ref}.{p.GetNumber()} ({p.GetNetname().split('/')[-1]}) "
                                  f"too close to {t.GetNetname().split('/')[-1]} "
                                  f"{t.GetClass()} at {pcbnew.ToMM(t.GetPosition().x):.2f},"
                                  f"{pcbnew.ToMM(t.GetPosition().y):.2f}")
    for e in errors:
        print("FAIL", e)
    print(f"{'FAIL' if errors else 'OK'}: {len(errors)} placement problems")
    return 1 if errors else 0


def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else "check"
    board = pcbnew.LoadBoard(BOARD)
    if stage == "place":
        place(board)
        board.Save(BOARD)
    elif stage == "strip":
        strip(board)
        board.Save(BOARD)
    elif stage == "check":
        done(check(board))
    else:
        sys.exit(f"unknown stage {stage}")
    done()


if __name__ == "__main__":
    main()
