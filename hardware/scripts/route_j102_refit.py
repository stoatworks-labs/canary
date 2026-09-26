#!/usr/bin/env python3
"""
Re-route the 17 connections torn up by the J102 move (rot 180, y 25 -> 22.60).

The 2026-07-31 fix put the USB-C mouth on the board edge, which flipped the
whole fan-out: the pads now sit at y 26.64 with the board interior BELOW them
(+y), where the original escape pocket was above. The surviving routing is
intact and ends where the pads used to be, so every job here is pad -> short
escape -> (via) -> existing dangling end. Nothing long is drawn.

Geometry rules inherited from route_residual.py (imported, not copied):
segment/rect/circle distance against real board obstacles per layer, through
vias checked against every copper layer, USB-pair work at the board's actual
0.20/0.20 rule, everything else at 0.25 clearance.

Plan (all coordinates mm, KiCad page frame):
  CHASSIS   4 PTH shell pads ringed on B.Cu above the row (y 21.55) and the
            right column dropped to the surviving trunk at (110.32, 29.50).
  USB_DP    B6+A6 linked ABOVE the row at y 24.9 (the only pair that fits
            there - A9's column is pinched by the NPTH peg at x 103.11), via
            at the link midpoint, B.Cu lane at x 106.30 down to the trunk end
            (106.75, 44.00). x 106.30, not 105.75: the VCC_5V via at
            (105.47, 33.89) sits 0.28 mm off the natural lane.
  USB_DM    A7+B7 linked BELOW the row at y 28.3, diagonal to a via at
            (104.60, 30.2), straight down B.Cu to the trunk end (104.60, 34.50).
  USB_CC1   A5 stub straight down to a via at (107.25, 29.6) - not 29.2, which
            pinched CC2's In2 lane to exactly 0.60 mm - then In2 diagonal to
            the dangling In2 end at (105.68, 33.24).
  USB_CC2   B5 jogged to a via at (104.40, 28.6) - x 104.40, not 104.25,
            which pinched the A9 VBUS riser - then In2 at y 28.6 passing
            ABOVE CC1's via, to the dangling In2 end at (110.27, 31.38).
  VBUS_RAW  A4 riser dropped to y 31.2 then east to the trunk end at
            (114.14, 32.40). A9 CANNOT ride down its own column - a GND
            stitching via at (103.23, 30.00) sits 0.32 mm off it, and the
            CC1 stub walls F.Cu at x 107.25, the DP/DM descents wall B.Cu,
            and CC1's diagonal plus CC2's y 28.6 run wall In2 below y 28.6 -
            so A9 dives at (103.55, 27.9) and crosses on In2 at y 27.2, in
            the strip between the pad row and CC2's lane, surfacing at
            (108.45, 27.9) ON the A4 riser. 0.4 mm wide: the 0.2 mm trunk it
            joins is the bottleneck either way.
  VCC_5V    the orphan (97.05, 30.00)-(98.10, 28.95) fragment bridged to the
            trunk corner at (101.52, 30.00) around a GND pad at x 98.45..99.45
            y 29.27..30.73 that sits dead on the straight lane.

Run AFTER this: zones.py refill (separate process - SWIG degrades after
mutation), then DRC. Expect the zone-island entries to need stitching, not
tracks.
"""
import os as _os
_REPO = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import sys

import pcbnew

sys.path.insert(0, _REPO + "/hardware/scripts")
import route_residual as rr

BOARD = _REPO + "/hardware/dbcanary.kicad_pcb"

F, B, IN2 = pcbnew.F_Cu, pcbnew.B_Cu, pcbnew.In2_Cu

# (name, netname-suffix, layer, width, clearance, [polyline], alternates)
# Polylines whose net is found via find_pad on the first spec when it is a
# ref.pad, else by net suffix lookup.
TRACKS = [
    # CHASSIS shell ring - PTH pads, so B.Cu reaches them directly.
    ("CHASSIS ring top", "CHASSIS", B, 0.50, 0.25,
     [(101.68, 21.55), (110.32, 21.55)], []),
    ("CHASSIS left col", "CHASSIS", B, 0.50, 0.25,
     [(101.68, 21.55), (101.68, 25.73)], []),
    ("CHASSIS right col", "CHASSIS", B, 0.50, 0.25,
     [(110.32, 21.55), (110.32, 25.73)], []),
    ("CHASSIS to trunk", "CHASSIS", B, 0.50, 0.25,
     [(110.32, 25.73), (110.32, 29.50)], []),

    # USB_DP pair link above the row + descent lane.
    ("DP stub B6", "USB_DP", F, 0.20, 0.20,
     [(105.25, 26.64), (105.25, 24.90)], []),
    ("DP stub A6", "USB_DP", F, 0.20, 0.20,
     [(106.25, 26.64), (106.25, 24.90)], []),
    ("DP link", "USB_DP", F, 0.20, 0.20,
     [(105.25, 24.90), (106.25, 24.90)], []),
    ("DP descent", "USB_DP", B, 0.20, 0.20,
     [(105.75, 24.90), (106.30, 25.90), (106.30, 43.40), (106.75, 44.00)],
     [[(105.75, 24.90), (106.45, 25.90), (106.45, 43.40), (106.75, 44.00)],
      [(105.75, 24.90), (106.15, 25.90), (106.15, 43.40), (106.75, 44.00)]]),

    # USB_DM pair link below the row + short descent.
    ("DM stub A7", "USB_DM", F, 0.20, 0.20,
     [(105.75, 26.64), (105.75, 28.30)], []),
    ("DM stub B7", "USB_DM", F, 0.20, 0.20,
     [(106.75, 26.64), (106.75, 28.30)], []),
    ("DM link", "USB_DM", F, 0.20, 0.20,
     [(105.75, 28.30), (106.75, 28.30)], []),
    ("DM to via", "USB_DM", F, 0.20, 0.20,
     [(105.75, 28.30), (104.60, 30.00), (104.60, 30.20)], []),
    ("DM descent", "USB_DM", B, 0.20, 0.20,
     [(104.60, 30.20), (104.60, 34.50)], []),

    # USB_CC1 straight drop + In2 diagonal to the dangling end.
    ("CC1 stub", "USB_CC1", F, 0.20, 0.20,
     [(107.25, 26.64), (107.25, 29.60)], []),
    ("CC1 In2", "USB_CC1", IN2, 0.20, 0.20,
     [(107.25, 29.60), (105.68, 33.24)], []),

    # USB_CC2 jog + In2 run above CC1's via to the dangling end.
    ("CC2 stub", "USB_CC2", F, 0.20, 0.20,
     [(104.25, 26.64), (104.25, 27.60), (104.40, 28.60)], []),
    ("CC2 In2", "USB_CC2", IN2, 0.20, 0.20,
     [(104.40, 28.60), (110.00, 28.60), (110.27, 31.38)],
     [[(104.40, 28.60), (109.80, 28.60), (110.27, 31.38)]]),

    # VBUS_RAW: A9 stub to a B.Cu dive, lane over the pocket, surfacing on the
    # A4 riser; A4 riser carries on to the trunk end on F.Cu.
    ("VBUS stub A9", "VBUS_RAW", F, 0.40, 0.25,
     [(103.55, 26.64), (103.55, 27.90)], []),
    ("VBUS In2 lane", "VBUS_RAW", IN2, 0.40, 0.25,
     [(103.55, 27.90), (104.50, 27.20), (108.00, 27.20), (108.45, 27.90)],
     [[(103.55, 27.90), (104.50, 27.35), (108.00, 27.35), (108.45, 27.90)]]),
    ("VBUS riser A4", "VBUS_RAW", F, 0.40, 0.25,
     [(108.45, 26.64), (108.45, 31.20)], []),
    ("VBUS east", "VBUS_RAW", F, 0.40, 0.25,
     [(108.45, 31.20), (113.30, 31.20), (114.14, 32.40)],
     [[(108.45, 31.20), (113.00, 31.20), (114.14, 32.40)],
      [(108.45, 31.20), (112.60, 31.20), (113.30, 31.90), (114.14, 32.40)]]),

    # VCC_5V orphan fragment bridged to the trunk corner, around the GND pad
    # at x 98.45..99.45 y 29.27..30.73.
    ("5V bridge", "VCC_5V", F, 0.20, 0.25,
     [(97.05, 30.00), (97.50, 28.70), (100.60, 28.70), (101.52, 29.60),
      (101.52, 30.00)],
     [[(97.05, 30.00), (97.50, 31.30), (100.60, 31.30), (101.52, 30.40),
       (101.52, 30.00)],
      [(97.05, 30.00), (97.30, 28.50), (100.80, 28.50), (101.52, 29.30),
       (101.52, 30.00)]]),
]

# (name, netname-suffix, x, y) - through vias, checked against every layer.
VIAS = [
    ("DP via", "USB_DP", 105.75, 24.90),
    ("DM via", "USB_DM", 104.60, 30.20),
    ("CC1 via", "USB_CC1", 107.25, 29.60),
    ("CC2 via", "USB_CC2", 104.40, 28.60),
    ("VBUS dive via", "VBUS_RAW", 103.55, 27.90),
    ("VBUS rise via", "VBUS_RAW", 108.45, 27.90),
]


def find_net(board, suffix):
    for code in range(1, board.GetNetCount()):
        ni = board.FindNet(code)
        if ni and ni.GetNetname().split("/")[-1] == suffix:
            return ni
    raise SystemExit("net not found: " + suffix)


def main():
    board = pcbnew.LoadBoard(BOARD)
    obs = {
        F: rr.collect(board, F),
        B: rr.collect(board, B),
        IN2: [o for o in rr.collect(board, F, include_inner=True)
              if o[0] != "seg"] +
             [("seg", nc, g) for k, nc, g in rr.collect(board, F, include_inner=True)
              if k == "seg"],
    }
    # In2 obstacle set: through-holes/vias/PTH pads block it, plus In2 tracks
    # only. collect() has no In2 mode, so build it: circles + PTH rects from
    # any layer, segs re-collected per layer below.
    in2_obs = []
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD:
                continue
            bb = p.GetBoundingBox()
            in2_obs.append(("rect", p.GetNetCode(),
                            (rr.tomm(bb.GetLeft()), rr.tomm(bb.GetTop()),
                             rr.tomm(bb.GetRight()), rr.tomm(bb.GetBottom()))))
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            pos = t.GetPosition()
            in2_obs.append(("circ", t.GetNetCode(),
                            (rr.tomm(pos.x), rr.tomm(pos.y), rr.VIA_DIA / 2)))
        elif t.GetLayer() == IN2:
            s, e = t.GetStart(), t.GetEnd()
            in2_obs.append(("seg", t.GetNetCode(),
                            (rr.tomm(s.x), rr.tomm(s.y), rr.tomm(e.x),
                             rr.tomm(e.y), rr.tomm(t.GetWidth()) / 2)))
    obs[IN2] = in2_obs

    obs_via = rr.collect(board, F, include_inner=True) + \
        [o for o in rr.collect(board, B) if o[0] == "seg"]

    failed = []
    placed_tracks = []
    placed_vias = []

    # Validate vias first: they gate everything.
    for name, suffix, x, y in VIAS:
        if not rr.seg_ok((x, y), (x, y), find_net(board, suffix).GetNetCode(),
                         rr.VIA_DIA, obs_via, 0.20):
            failed.append((name, rr.why_blocked((x, y), (x, y),
                                                find_net(board, suffix).GetNetCode(),
                                                rr.VIA_DIA, obs_via, 0.20)))

    for name, suffix, layer, width, clear, pts, alts in TRACKS:
        net = find_net(board, suffix)
        nc = net.GetNetCode()
        chosen, first_bad = None, None
        for cand in [pts] + alts:
            bad = None
            for k in range(len(cand) - 1):
                if not rr.seg_ok(cand[k], cand[k + 1], nc, width, obs[layer], clear):
                    bad = "%s (%.2f,%.2f)-(%.2f,%.2f): %s" % (
                        name, cand[k][0], cand[k][1], cand[k + 1][0], cand[k + 1][1],
                        rr.why_blocked(cand[k], cand[k + 1], nc, width,
                                       obs[layer], clear))
                    break
            if bad is None:
                chosen = cand
                break
            if first_bad is None:
                first_bad = bad
        if chosen is None:
            failed.append((name, first_bad))
            continue
        placed_tracks.append((name, net, layer, width, chosen))
        for k in range(len(chosen) - 1):
            obs[layer].append(("seg", nc, (chosen[k][0], chosen[k][1],
                                           chosen[k + 1][0], chosen[k + 1][1],
                                           width / 2)))

    if failed:
        for name, why in failed:
            print("BLOCKED %s: %s" % (name, why))
        print("nothing written")
        return 1

    for name, net, layer, width, chosen in placed_tracks:
        for k in range(len(chosen) - 1):
            rr.add_track(board, net, chosen[k], chosen[k + 1], width, layer)
    for name, suffix, x, y in VIAS:
        rr.place_via(board, find_net(board, suffix), x, y, [])
        placed_vias.append(name)

    pcbnew.SaveBoard(BOARD, board)
    print("placed %d polylines, %d vias" % (len(placed_tracks), len(placed_vias)))
    for name, net, layer, width, chosen in placed_tracks:
        lname = {F: "F.Cu", B: "B.Cu", IN2: "In2"}[layer]
        print("  %-18s %-5s w%.2f  %s" %
              (name, lname, width,
               " ".join("(%.2f,%.2f)" % p for p in chosen)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
