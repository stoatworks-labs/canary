#!/usr/bin/env python3
"""
Re-route USB_DP / USB_DM as an actual differential pair.

Why this exists
---------------
After the J102 180-degree refit the two nets were electrically connected and DRC
was clean, so nothing complained - but they were not routed as a pair at all:

    USB_DP   B.Cu lane at y 44.00, x 43.0 .. 106.75
    USB_DM   B.Cu lane at y 34.50, x 41.0 .. 104.60

Two single-ended traces 9.5 mm apart for a 63 mm run. Coupling between them is
essentially zero and the loop they enclose is about 600 mm^2, which is the
dominant radiator on this board. Length came out 95.2 mm (DP) against 79.2 mm
(DM) - 16.0 mm of skew, ~89 ps.

(The EMC analyzer reported 100.2 / 142.8 mm and 42.6 mm of mismatch. That figure
was inflated by duplicate stacked segments - see DEDUPE below - which this script
also removes. The true pre-fix mismatch was 16.0 mm.)

What this does
--------------
Deletes every track and via on both nets and re-lays them from scratch:

  * the J102 escapes are rebuilt exactly as the refit had them. They are forced
    by the connector pinout - A6/B6 and A7/B7 interleave on 0.5 mm pitch, so one
    pair must link ABOVE the pad row and the other BELOW, and only DP fits above.
    That asymmetry is why the two nets enter B.Cu 5.3 mm apart in y, and it is
    the entire source of the length mismatch.

  * one coupled lane on B.Cu, 0.30 mm trace on 0.55 mm pitch (0.25 mm gap),
    57.4 mm long, DM at y 34.60 and DP at y 35.15. The lane sits in a measured
    2.25 mm clear band (y 34.10 .. 36.35 for a 0.30 mm trace at 0.20 clearance).
    0.30/0.25 on the 0.2104 mm prepreg is ~94 ohm differential against USB's
    90 ohm. That is a bonus, not the point: the S3's USB is full-speed only, so
    Z0 is irrelevant here - it matters only if this ever gets a HS PHY.

  * a trombone on DM, west of x 104.60, adding exactly 6.98 mm so the two nets
    come out equal. It has to go west: DP descends at x 106.45, so anything DM
    does east of 104.60 shorts to it. The free pocket at y 30.75 .. 31.75 runs
    clear from x 96 to x 111.5, which is where the fold sits.

Hard constraints found by probing the real obstacle set, do not "simplify" these
away:

  * DP cannot descend at x 105.75 - a via on net 7 sits at (105.47, 33.89).
  * DP cannot descend at x 106.75 - the USB_CC1 via sits at (107.25, 29.60).
    x 106.45 is the only column that clears both.
  * Neither net can cut diagonally from the lane to the module pads: U301 pad 12
    (x 44.50..46.00, y 34.76..35.66) sits square across that line. Both escapes
    dogleg east of the pad column and come in horizontally.
  * DM must be the UPPER lane. Its transition via (104.60, 30.20) is west of
    DP's descent column, so if DM took the lower lane it would have to cross
    DP's horizontal run to get there.

DEDUPE: both nets carried exact duplicate segments stacked on top of each other
(DP: (43.00,44.00)-(43.00,39.00) twice; DM: (104.60,34.50)-(41.00,34.50) twice).
Deleting the nets wholesale removes them. Nothing else on this board was checked
for the same fault - worth a sweep.

Order of operations. Each line is its own process - SWIG degrades after
mutation - and the sequence is NOT arbitrary:

    route_usb_pair.py             re-route the pair
    zones.py                      refill, so the pours reflect the new routing
    route_usb_pair.py --stitch    the four RP-001 return vias
    zones.py                      canonical pour state after the vias
    route_usb_pair.py --verify    re-read the FILE and assert the result
    verify_zones.py               isolation barrier + chassis moat intact
    kicad-cli pcb drc

Then regenerate every fab package - a stale vendor folder is how a wrong board
gets ordered.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import math

import pcbnew
import route_residual as rr

F, B = pcbnew.F_Cu, pcbnew.B_Cu

W_ESC = 0.20          # escape width: 0.5 mm pitch pads leave 0.20 mm gaps
W_LANE = 0.30         # coupled lane
GAP = 0.25            # edge-to-edge in the lane -> 0.55 mm pitch
CLEAR = 0.20          # the board's real netclass clearance, not ORDERING.md's 0.15

Y_DM, Y_DP = 34.60, 35.15
TROMBONE = 3.49       # west excursion; +6.98 mm total, which is the exact deficit

# DP steps off the lane before its via. With the via ON the lane at y 35.15 its
# barrel sat 0.55 mm from DM's lane centreline - 0.10 mm of copper gap against a
# 0.20 rule, and DRC caught it. The step costs nothing in length: the F.Cu drop
# to the pad shortens by exactly what the B.Cu jog adds.
Y_DP_VIA = 35.60

# (layer, width, polyline)
DM_PATH = [
    (F, W_ESC, [(106.75, 26.645), (106.75, 28.30)]),
    (F, W_ESC, [(105.75, 26.645), (105.75, 28.30)]),
    (F, W_ESC, [(105.75, 28.30), (106.75, 28.30)]),
    (F, W_ESC, [(105.75, 28.30), (104.60, 30.00), (104.60, 30.20)]),
    (B, W_LANE, [(104.60, 30.20), (104.60, 30.90),
                 (104.60 - TROMBONE, 30.90), (104.60 - TROMBONE, 31.60),
                 (104.60, 31.60), (104.60, Y_DM), (46.60, Y_DM)]),
    (F, W_ESC, [(46.60, Y_DM), (46.60, 36.48), (45.25, 36.48)]),
]
DM_VIAS = [(104.60, 30.20), (46.60, Y_DM)]

DP_PATH = [
    (F, W_ESC, [(105.25, 26.645), (105.25, 24.90)]),
    (F, W_ESC, [(106.25, 26.645), (106.25, 24.90)]),
    (F, W_ESC, [(105.25, 24.90), (106.25, 24.90)]),
    (B, W_LANE, [(105.75, 24.90), (106.45, 25.90),
                 (106.45, Y_DP), (47.20, Y_DP), (47.20, Y_DP_VIA)]),
    (F, W_ESC, [(47.20, Y_DP_VIA), (47.20, 37.75), (45.25, 37.75)]),
]
DP_VIAS = [(105.75, 24.90), (47.20, Y_DP_VIA)]

# Return-path stitching for RP-001 / DP-003.
#
# WHAT ACTUALLY GOES WRONG HERE. The diagnosis this file used to carry was
# backwards, and acting on it sent the work at the pours, which are innocent.
#
# The symptom is real: a via handed gnd_code comes back out of the saved file
# on VCC_3V3, and DRC reports it dangling. That was recorded as zones.py
# orphaning the via and the In2 plane absorbing it, curable by a bigger GND
# pour. Neither half holds.
#
# Instrumenting the pass shows the via holding netcode 8 (GND) through
# SetNetCode(), through board.Add(), and in board.GetTracks() immediately
# before the save. board.Save() is what writes VCC_3V3. The cause is the
# STALE In2 fill: the VCC_3V3 plane was poured when this via did not exist, so
# it has no clearance hole here and the via lands in solid VCC_3V3 copper. The
# connectivity rebuild that runs inside Save() sees the via touching that
# plane and claims it. Which of the four it claims moves run to run - five
# identical runs off one baseline gave GND/BAD/GND/BAD, all-GND, all-GND,
# GND/GND/BAD/GND, all-GND.
#
# zones.py is not the culprit, it is the repair. Its refill cuts the clearance
# hole and reconnects the via to the GND pours. That is the whole reason the
# fault looked intermittent: it depended on whether anything re-read the file
# before the next refill papered over it.
#
# The fix is one line - refill the zones in THIS process, after the Add()s and
# before the Save(), so In2 has its hole before connectivity runs. Six
# consecutive runs then came out all-GND. See stitch_pass().
#
# WHY THE SITES SIT ~1.0 mm OUT and not on the 1.5 mm ring this file wanted.
# A foreign via voids GND fill for 0.56 mm around itself - 0.30 barrel plus
# the 0.25 mm local clearance zones.py sets, measured off the poured copper,
# not derived. A site with GND fill all the way round a ring of radius m must
# therefore sit at least m + 0.56 mm from the signal via it serves. At m = 1.5
# that is 2.06 mm. RP-001's search radius on this stackup is
# max(2 x 0.1, 1.0) = 1.0 mm, the 0.1 being "dielectric 1". So the ring test
# and the rule it was written to satisfy are in direct conflict - not just on
# this board, on any board - and the ring test is the one that has to give.
#
# The 1.5 mm ring is unreachable at the module regardless. Poured into every
# legally fillable square micron, with island removal and min thickness both
# switched off, the nearest F.Cu+B.Cu+In1.Cu site carrying a 1.5 mm ring is
# 4.41 mm from DP's transition and 3.80 mm from DM's. On the copper as it is
# actually poured there is none within 3.5 mm of either. No pour change closes
# that: SYSTEM in zones.py already covers both regions in full, and the fill
# stops exactly where U301's pad column, this pair's own F.Cu escapes, J102's
# 0.5 mm pad field and the coupled lane's B.Cu void say it must. Every one of
# those is foreign copper. There is no pour to extend.
#
# Each site below is instead the most deeply buried point inside RP-001's
# 1.0 mm: 0.85 .. 1.00 mm from its signal via, GND fill present on F.Cu, In1.Cu
# AND B.Cu, and 0.40 .. 0.45 mm of ring clear on all three. Copper clearance
# needs 0.80 mm centre to centre (0.30 + 0.30 + 0.20) and hole-to-hole 0.5495;
# the closest of the four is 0.85. gnd_fill_layers() and --verify still police
# all of it.
#
# Still true, and still worth not repeating:
#   * route_residual.collect() sees pads and tracks but NOT zone fills, so a
#     site can look completely free while sitting inside the In2 plane with no
#     GND on any layer. Two vias went exactly there. Test the pour polygons.
#   * When siting a GND via, other GND vias drop out of the obstacle set -
#     right for copper clearance, wrong for drill spacing. One candidate
#     landed 0.06 mm from the existing via at (103.230, 30.000). Hence
#     HOLE_TO_HOLE.
#   * That existing via is 1.385 mm from DM's J102 transition. Inside the old
#     2.4 mm budget, outside RP-001's 1.0 mm - so it does not serve it, and
#     DM_J102 gets its own via like the other three.
STITCH = [
    (105.15, 24.10),     # DP_J102, 1.00 mm from (105.75, 24.90)
    (48.00, 36.15),      # DP_U301, 0.97 mm from (47.20, 35.60)
    (103.95, 29.50),     # DM_J102, 0.96 mm from (104.60, 30.20)
    (47.10, 33.75),      # DM_U301, 0.99 mm from (46.60, 34.60)
]
STITCH_BUDGET = 1.00     # RP-001's search radius on this stackup, and enforced
STITCH_MARGIN = 0.35     # required ring depth inside the GND fill, all 3 layers
HOLE_TO_HOLE = 0.2495    # board setup minimum


def polylen(pts):
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def gnd_fills(board):
    """{layer name: [filled polygon sets]} for the GND zones."""
    out = {}
    for z in board.Zones():
        if z.GetIsRuleArea() or z.GetNetname() != "GND":
            continue
        for li in z.GetLayerSet().CuStack():
            try:
                poly = z.GetFilledPolysList(li)
            except Exception:
                continue
            if poly:
                out.setdefault(board.GetLayerName(li), []).append(poly)
    return out


def gnd_fill_layers(board, x, y, margin=0.0, fills=None):
    """Layers whose GND fill contains (x, y) - and, if margin, a ring around it.

    route_residual.collect() reports pads and tracks only, so it cannot answer
    this at all. Without the margin term a site can sit legally inside the fill
    yet close enough to its edge that adding the via orphans it on refill.
    """
    fills = gnd_fills(board) if fills is None else fills
    out = []
    for layer, polys in fills.items():
        def inside(px, py):
            v = pcbnew.VECTOR2I(rr.mm(px), rr.mm(py))
            return any(p.Contains(v) for p in polys)
        if not inside(x, y):
            continue
        if margin:
            ring = [(x + margin * math.cos(2 * math.pi * k / 16),
                     y + margin * math.sin(2 * math.pi * k / 16)) for k in range(16)]
            if not all(inside(px, py) for px, py in ring):
                continue
        out.append(layer)
    return out


def stitch_pass(dry):
    """
    Second process. The GND stitching vias CANNOT be added in the same pass as
    the re-route: place_via() there produced vias on net VCC_3V3 despite being
    handed the GND NETINFO_ITEM, because the 26 Remove() calls ahead of it had
    already degraded the bindings - the exact failure hardware/scripts/README.md
    warns about. Two of the four came out wrong and DRC caught them as dangling.
    A clean process with no removals in front of the Add() gets it right.

    That was necessary but not sufficient: see the note above the ZONE_FILLER
    call at the end, which is what stopped Save() re-netting the vias.
    """
    board = pcbnew.LoadBoard(rr.BOARD)
    n2c = {}
    for fp in board.GetFootprints():
        for p in fp.Pads():
            n2c[p.GetNetname()] = p.GetNetCode()
    gnd_code = n2c["GND"]
    sig = [v for v in (DP_VIAS + DM_VIAS)]

    stale = []
    for t in board.GetTracks():
        if t.GetClass() != "PCB_VIA":
            continue
        p = t.GetPosition()
        xy = (round(rr.tomm(p.x), 3), round(rr.tomm(p.y), 3))
        if any(math.dist(xy, s) < 1e-3 for s in STITCH):
            stale.append((t, xy, t.GetNetname()))

    print("stitch pass: %d via(s) already at the stitch sites %s" % (
        len(stale), [(x, n) for _, x, n in stale]))
    if not STITCH:
        print("stitch pass: STITCH is empty - see the comment above it. "
              "Nothing to do; this is deliberate, not a bug.")
        return 0
    fills = gnd_fills(board)
    bad = []
    for (sx, sy) in STITCH:
        on = gnd_fill_layers(board, sx, sy, STITCH_MARGIN, fills)
        d = min(math.dist((sx, sy), v) for v in sig)
        print("   (%.3f,%.3f)  %.2f mm from the nearest signal via | %.2f mm "
              "inside GND on: %s" % (
                  sx, sy, d, STITCH_MARGIN,
                  ", ".join(sorted(on)) if on else "NOTHING"))
        if {"F.Cu", "B.Cu", "In1.Cu"} - set(on):
            bad.append("(%.3f,%.3f) has no GND fill %.2f mm out on %s" % (
                sx, sy, STITCH_MARGIN,
                ", ".join(sorted({"F.Cu", "B.Cu", "In1.Cu"} - set(on)))))
        # Enforced, not just printed. A site that drifts past RP-001's radius
        # stops serving the transition it was placed for, and nothing else in
        # this file would notice.
        if d > STITCH_BUDGET + 1e-9:
            bad.append("(%.3f,%.3f) is %.2f mm out, past the %.2f mm budget" % (
                sx, sy, d, STITCH_BUDGET))
    if bad:
        print("REFUSING, %d problem(s):" % len(bad))
        for b in bad:
            print("   " + b)
        return 1
    if dry:
        print("--dry-run: no changes written")
        return 0

    for t, _, _ in stale:
        board.Remove(t)
    # Two rules here, both learned the hard way, both non-obvious:
    #
    #   1. SetNetCode(int), never SetNet(NETINFO_ITEM). A held NETINFO_ITEM
    #      pointer goes stale part-way through a loop of Add() calls; two of
    #      these four came out on VCC_3V3 and re-running moved WHICH two.
    #   2. Set the net BEFORE board.Add(). Add() transfers ownership to the
    #      board and the Python proxy is dead afterwards, so a SetNetCode()
    #      following the Add() silently lands nowhere - which reproduced the
    #      same wrong-net symptom on roughly one run in three.
    #
    # Both failures are invisible in-process: the object reports the right net
    # right up until the file is re-read. That is what --verify is for.
    for (sx, sy) in STITCH:
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(pcbnew.VECTOR2I(rr.mm(sx), rr.mm(sy)))
        v.SetWidth(rr.mm(rr.VIA_DIA))
        v.SetDrill(rr.mm(rr.VIA_DRILL))
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNetCode(gnd_code)
        board.Add(v)
    #   3. REFILL BEFORE SAVING. This is the one that mattered. Every via above
    #      lands inside In2's VCC_3V3 fill, which was poured when it did not
    #      exist and so carries no clearance hole for it. The connectivity
    #      rebuild that runs inside Save() sees the barrel touching that plane
    #      and re-nets the via to VCC_3V3 - a different subset on nearly every
    #      run, which is what made this look like a zone-fill race. Cutting the
    #      hole first, and tying the via to the GND pours first, removes the
    #      ambiguity: six consecutive runs came out all-GND against two bad in
    #      five without it. zones.py still runs after this pass; that is what
    #      returns the pours to their canonical state.
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(rr.BOARD)
    print("stitch pass: %d via(s) placed, pours refilled to match. Run "
          "zones.py, then --verify, each in its own process." % len(STITCH))
    return 0


def verify_pass():
    """Re-read the SAVED FILE and assert what the mutating passes claim.

    Deliberately parsed as text rather than through pcbnew. Two independent
    reasons: the SWIG bindings that wrote the file are the same ones that would
    read it back, and a run of LoadBoard()+GetNetname() over these vias returned
    the wrong net on roughly two runs in five while the file on disk was correct
    every time. The file is the artifact that gets fabricated, so the file is
    what gets checked. This is read-only inspection - nothing here writes.
    """
    import re

    src = open(rr.BOARD).read()
    vias = {}
    for m in re.finditer(r"\(via\b(.*?)\n\t\)", src, re.S):
        blk = m.group(1)
        at = re.search(r"\(at ([-\d.]+) ([-\d.]+)\)", blk)
        net = re.search(r'\(net "([^"]*)"\)', blk)
        if at:
            vias[(round(float(at.group(1)), 3), round(float(at.group(2)), 3))] = (
                net.group(1) if net else "<none>")

    bad = []
    for (sx, sy) in STITCH:
        got = vias.get((round(sx, 3), round(sy, 3)), "MISSING")
        print("  stitch  (%9.3f,%8.3f)  %s" % (sx, sy, got))
        if got != "GND":
            bad.append("stitch via (%.3f,%.3f) is on %s, expected GND" % (sx, sy, got))
    for name, want in (("USB_DP", DP_VIAS), ("USB_DM", DM_VIAS)):
        for (vx, vy) in want:
            got = vias.get((round(vx, 3), round(vy, 3)), "MISSING")
            print("  %-7s (%9.3f,%8.3f)  %s" % (name, vx, vy, got))
            if got != name:
                bad.append("%s via (%.2f,%.2f) is on %s" % (name, vx, vy, got))

    lens = {"USB_DP": 0.0, "USB_DM": 0.0}
    for m in re.finditer(r"\(segment\b(.*?)\n\t\)", src, re.S):
        blk = m.group(1)
        net = re.search(r'\(net "([^"]*)"\)', blk)
        if not net or net.group(1) not in lens:
            continue
        s_ = re.search(r"\(start ([-\d.]+) ([-\d.]+)\)", blk)
        e_ = re.search(r"\(end ([-\d.]+) ([-\d.]+)\)", blk)
        if s_ and e_:
            lens[net.group(1)] += math.dist(
                (float(s_.group(1)), float(s_.group(2))),
                (float(e_.group(1)), float(e_.group(2))))
    skew = abs(lens["USB_DP"] - lens["USB_DM"])
    print("  USB_DP %.2f mm, USB_DM %.2f mm, mismatch %.2f mm (%.1f ps)" % (
        lens["USB_DP"], lens["USB_DM"], skew, skew * 5.53))
    if skew > 0.5:
        bad.append("length mismatch %.2f mm" % skew)
    if min(lens.values()) < 1.0:
        bad.append("a USB net has almost no copper - parse or routing failure")

    if bad:
        print("\nVERIFY FAILED:")
        for x in bad:
            print("  " + x)
        return 1
    print("verify: OK")
    return 0


def main():
    dry = "--dry-run" in sys.argv
    if "--verify" in sys.argv:
        return verify_pass()
    if "--stitch" in sys.argv:
        return stitch_pass(dry)
    board = pcbnew.LoadBoard(rr.BOARD)

    # ---- QUERY EVERYTHING FIRST. pcbnew's SWIG bindings return untyped objects
    # ---- once the board has been mutated, so no lookups may happen after this.
    n2c = {}
    for fp in board.GetFootprints():
        for p in fp.Pads():
            n2c[p.GetNetname()] = p.GetNetCode()
    dp_code, dm_code, gnd_code = n2c["USB_DP"], n2c["USB_DM"], n2c["GND"]
    nets = {c: board.FindNet(c) for c in (dp_code, dm_code, gnd_code)}

    # GND's own copper is not an obstacle to a GND via.
    obs_gnd = {
        F: [o for o in rr.collect(board, F) if o[1] != gnd_code],
        B: [o for o in rr.collect(board, B) if o[1] != gnd_code],
        "in": [o for o in rr.collect(board, pcbnew.In1_Cu, include_inner=True)
               if o[1] != gnd_code],
    }

    obs = {
        F: [o for o in rr.collect(board, F) if o[1] not in (dp_code, dm_code)],
        B: [o for o in rr.collect(board, B) if o[1] not in (dp_code, dm_code)],
    }
    obs_inner = [o for o in rr.collect(board, pcbnew.In1_Cu, include_inner=True)
                 if o[1] not in (dp_code, dm_code)]

    existing_via_holes = []
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA" and t.GetNetCode() not in (dp_code, dm_code):
            p = t.GetPosition()
            existing_via_holes.append((rr.tomm(p.x), rr.tomm(p.y)))

    doomed, dup = [], 0
    seen = set()
    for t in board.GetTracks():
        if t.GetNetCode() not in (dp_code, dm_code):
            continue
        doomed.append(t)
        if t.GetClass() != "PCB_VIA":
            s, e = t.GetStart(), t.GetEnd()
            key = (t.GetNetCode(), t.GetLayer(),
                   tuple(sorted([(s.x, s.y), (e.x, e.y)])))
            if key in seen:
                dup += 1
            seen.add(key)

    old_len = {}
    for c in (dp_code, dm_code):
        old_len[c] = sum(
            math.dist((rr.tomm(t.GetStart().x), rr.tomm(t.GetStart().y)),
                      (rr.tomm(t.GetEnd().x), rr.tomm(t.GetEnd().y)))
            for t in doomed if t.GetNetCode() == c and t.GetClass() != "PCB_VIA")

    # ---- PRE-FLIGHT: every new segment and via against the real obstacle set.
    plan = [(dp_code, DP_PATH, DP_VIAS), (dm_code, DM_PATH, DM_VIAS)]
    fails = []
    for code, path, vias in plan:
        for layer, w, pts in path:
            for i in range(len(pts) - 1):
                if not rr.seg_ok(pts[i], pts[i + 1], code, w, obs[layer], CLEAR):
                    fails.append("%s seg (%.2f,%.2f)->(%.2f,%.2f) on %s: %s" % (
                        board.GetNetInfo().GetNetItem(code).GetNetname(),
                        pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1],
                        board.GetLayerName(layer),
                        rr.why_blocked(pts[i], pts[i + 1], code, w, obs[layer], CLEAR)))
        for (vx, vy) in vias:
            for tag, o in (("B.Cu", obs[B]), ("F.Cu", obs[F]), ("inner", obs_inner)):
                if not rr.seg_ok((vx, vy), (vx, vy), code, rr.VIA_DIA, o, CLEAR):
                    fails.append("via (%.2f,%.2f) blocked on %s: %s" % (
                        vx, vy, tag,
                        rr.why_blocked((vx, vy), (vx, vy), code, rr.VIA_DIA, o, CLEAR)))

    # DP against DM. This does NOT fall out of the checks above: seg_ok skips
    # same-net obstacles, and both USB nets are filtered out of every obstacle
    # set, so each net is invisible to the other. The first version of this
    # script had no such check and DRC found a 0.10 mm gap between DM's lane and
    # DP's transition via. Keep this.
    def explode(path, vias):
        segs, vs = [], []
        for layer, w, pts in path:
            for i in range(len(pts) - 1):
                segs.append((layer, w, pts[i], pts[i + 1]))
        for (vx, vy) in vias:
            vs.append((vx, vy))
        return segs, vs

    dp_segs, dp_vias = explode(DP_PATH, DP_VIAS)
    dm_segs, dm_vias = explode(DM_PATH, DM_VIAS)
    R = rr.VIA_DIA / 2

    for la, wa, a0, a1 in dp_segs:
        for lb, wb, b0, b1 in dm_segs:
            if la != lb:
                continue
            d = rr.seg_seg_dist(a0, a1, b0, b1)
            if d < wa / 2 + wb / 2 + CLEAR - 1e-9:
                fails.append(
                    "DP/DM %s: (%.2f,%.2f)-(%.2f,%.2f) vs (%.2f,%.2f)-(%.2f,%.2f) "
                    "gap %.3f mm" % (board.GetLayerName(la), a0[0], a0[1], a1[0],
                                     a1[1], b0[0], b0[1], b1[0], b1[1],
                                     d - wa / 2 - wb / 2))
    for segs, vias, tag in ((dp_segs, dm_vias, "DP track vs DM via"),
                            (dm_segs, dp_vias, "DM track vs DP via")):
        for _, w, s0, s1 in segs:
            for (vx, vy) in vias:                 # through vias hit every layer
                d = rr.seg_dist(vx, vy, s0[0], s0[1], s1[0], s1[1])
                if d < w / 2 + R + CLEAR - 1e-9:
                    fails.append("%s at (%.2f,%.2f): gap %.3f mm" % (
                        tag, vx, vy, d - w / 2 - R))
    for (ax, ay) in dp_vias:
        for (bx, by) in dm_vias:
            d = math.dist((ax, ay), (bx, by))
            if d < rr.VIA_DIA + CLEAR - 1e-9:
                fails.append("DP via (%.2f,%.2f) vs DM via (%.2f,%.2f): gap %.3f mm"
                             % (ax, ay, bx, by, d - rr.VIA_DIA))

    # NOTE: the stitching vias are deliberately NOT validated here. Their sites
    # depend on where the GND pours end up AFTER this re-route and a refill, and
    # at this point the board still carries the old routing, which carves the
    # pours differently. Validating them against the pre-refill fills rejected
    # good sites and accepted doomed ones. The --stitch pass does it instead,
    # and the documented order runs zones.py in between.
    lane_gap = abs(Y_DP - Y_DM) - W_LANE
    if abs(lane_gap - GAP) > 1e-6:
        fails.append("lane pitch gives %.3f mm gap, expected %.3f" % (lane_gap, GAP))

    new_len = {}
    for code, path, _ in plan:
        new_len[code] = sum(polylen(pts) for _, _, pts in path)
    skew_mm = abs(new_len[dp_code] - new_len[dm_code])
    if skew_mm > 0.5:
        fails.append("length mismatch %.2f mm exceeds the 0.5 mm budget" % skew_mm)

    print("USB_DP  was %6.2f mm  ->  now %6.2f mm" % (old_len[dp_code], new_len[dp_code]))
    print("USB_DM  was %6.2f mm  ->  now %6.2f mm" % (old_len[dm_code], new_len[dm_code]))
    print("mismatch was %5.2f mm  ->  now %5.2f mm  (%.1f ps at 5.53 ps/mm)" % (
        abs(old_len[dp_code] - old_len[dm_code]), skew_mm, skew_mm * 5.53))
    print("coupled run %.1f mm at %.2f mm pitch; loop area %.0f mm^2 -> %.0f mm^2" % (
        104.60 - 47.20, abs(Y_DP - Y_DM),
        63.6 * 9.5, (104.60 - 47.20) * abs(Y_DP - Y_DM)))
    print("deleting %d items on the two nets (%d were exact duplicates)" % (len(doomed), dup))

    if fails:
        print("\nPRE-FLIGHT FAILED - nothing written:")
        for f in fails:
            print("  " + f)
        return 1
    print("pre-flight clean")

    if dry:
        print("--dry-run: no changes written")
        return 0

    # ---- MUTATE. Nothing above this line may be re-queried.
    for t in doomed:
        board.Remove(t)
    for code, path, vias in plan:
        net = nets[code]
        for layer, w, pts in path:
            for i in range(len(pts) - 1):
                rr.add_track(board, net, pts[i], pts[i + 1], w, layer)
        for (vx, vy) in vias:
            rr.place_via(board, net, vx, vy, obs[B])

    board.Save(rr.BOARD)
    print("saved %s" % rr.BOARD)
    print("next, one process each: zones.py, verify_zones.py, then DRC")
    return 0


if __name__ == "__main__":
    sys.exit(main())
