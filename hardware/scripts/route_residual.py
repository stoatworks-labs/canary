#!/usr/bin/env python3
"""
Hand-route the connections the autorouter could not finish.

Freerouting completes 139 of 141 nets but leaves four connections open. They are
all long runs across congested F.Cu, while B.Cu carries only 12 tracks - so they
are routed there instead, pad -> via -> B.Cu path -> via -> pad.

Paths are tried straight, then as two L-shapes, then as Z-shapes with a swept
offset, and every candidate is checked segment-by-segment against real geometry:
B.Cu tracks, every via and through-hole pad (which block all layers), the board
edge, and the isolation barrier. Nothing is placed unless a whole path clears.

Note on CHASSIS: J102's shell and J401's shell are one net, so the USB-C shield
needs a physical path to the chassis island ~65 mm away. It is routed as a track
rather than a poured rail because the right-hand board edge is populated
(F101/C109/R107/C106/L102) and a moated pour there would not fit. CHASSIS still
never touches GND galvanically - the single-point bond decision is unchanged.
"""
import os as _os
_REPO = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import math
import sys

import pcbnew

BOARD = _REPO + "/hardware/dbcanary.kicad_pcb"

VIA_DIA, VIA_DRILL = 0.6, 0.3
CLEAR = 0.25
EDGE = 0.6
BOARD_BOX = (20.0, 19.0, 120.0, 100.0)
BARRIER = (20.0, 66.5, 80.5, 73.5)

# (net suffix, from ref.pad, to ref.pad, track width mm)
# (net suffix, from ref.pad, to ref.pad, track width mm, clearance mm)
#
# The USB pair runs 0.20/0.20 - the board's actual design rule - rather than the
# 0.25 used elsewhere. It has to: the connector's pads are 0.30 mm wide on
# 0.50 mm pitch, leaving 0.20 mm gaps that no track can pass through, so the
# only way out is straight down off the OUTER pad of each pair, where there is
# exactly 0.35 mm to the neighbouring pad.
CONNECTIONS = [
    ("USB_DP",    "J102.B6", "U301.14", 0.20, 0.20),
    ("USB_DM",    "J102.B7", "U301.13", 0.20, 0.20),
    ("ETH_CT_RD", "T401.7",  "R403.1",  0.30, 0.25),
    ("CHASSIS",   "J102.SH", "J401.SH", 0.50, 0.25),
]

# Hand-built escape out of the USB-C fanout, per net: an explicit F.Cu polyline
# from a start point to where the transition via goes.
#
# The connector is 16 pads on 0.5 mm pitch in ONE row at y=20.95, with the
# shell pads at x=101.68/110.32 only - so the pocket at x~104.5..107.5,
# y~23..25 is open. DP drops straight down from B6 (0.225 mm to A7 and to A8,
# both above the 0.2 mm rule); DM continues from the stub the autorouter
# already ran below the pads. Left to a ring search this fails outright, which
# is exactly what happened.
USB_ESCAPES = {
    # Stop at y=22.60, not lower: an existing F.Cu track runs across this pocket
    # at y=23.31. The transition vias therefore sit in the 1.6 mm gap between
    # the pad row (ends y=21.68) and that track. They clear the 0.5 mm-pitch
    # pads because the pads' y-range ends above them, not by x-spacing.
    # This script now runs BEFORE the autorouter, on an empty pocket. That is
    # the whole point: run afterwards, the pocket already held a wide VBUS_RAW
    # track at y=23.31 and USB_CC2 descending In2 at x=106.84, which together
    # left no legal via position for DP at all.
    #
    # A6/B6 (DP) and A7/B7 (DM) interleave, so the two pairs cannot both be
    # linked on the same side. DM links BELOW the row at y=22.60; DP links
    # ABOVE it at y=19.70, which still clears the board edge (y=19) by 0.60 mm.
    "USB_DP": [(105.75, 20.95), (105.75, 19.70), (106.75, 19.70),
               (106.75, 20.95), (106.75, 23.60)],
    "USB_DM": [(106.25, 20.95), (106.25, 22.60), (104.60, 22.60)],
}

# Extra F.Cu stubs that a single polyline cannot express, because they branch.
# B7 and A7 are both USB_DM: the link runs from A7 down and left, passing UNDER
# B7 at x=105.25 without joining it, so B7 needs its own drop onto that link.
BRANCHES = {
    "USB_DM": [[(105.25, 20.95), (105.25, 22.60)]],
}

# Alternative fanouts, tried when the primary escape's via fails the ALL-LAYER
# check. The via is what matters: it is a through via, so it must clear In1 and
# In2 as well - the primary DP escape put it 0.09 mm from a USB_CC2 track on In2.
# Each entry is the full F.Cu polyline; its last point is where the via lands.
ALT_ESCAPES = {
    "USB_DP": [[(105.75, 20.95), (105.75, 19.70), (106.75, 19.70),
                (106.75, 20.95), (106.75, y)]
               for y in (23.60, 23.90, 24.20, 23.30, 24.60)],
    "USB_DM": [[(106.25, 20.95), (106.25, y), (x, y)]
               for y in (22.60, 22.90, 23.20)
               for x in (104.60, 104.30, 104.90, 104.00)],
}

# Explicit B.Cu corridors, and an explicit F.Cu landing polyline at the far end.
#
# Letting the generic search pick shapes does not work here: it chose the
# straight diagonal for the first net, which then cut B.Cu in half and starved
# the remaining three. These are Manhattan lanes chosen so no two cross, and so
# none strays into the isolated CAN domain (x <= 80.5, y >= 73.5) or within
# 0.4 mm of the chassis island edge at x = 82.03.
CORRIDORS = {
    "USB_DP":    ([(106.75, 23.60), (106.75, 44.00), (43.00, 44.00), (43.00, 39.00)],
                  [(43.00, 39.00), (45.25, 37.75)]),
    "USB_DM":    ([(104.60, 22.60), (104.60, 34.50), (41.00, 34.50)],
                  [(41.00, 34.50), (45.25, 36.48)]),
    "ETH_CT_RD": ([(81.50, 79.00), (81.50, 93.50), (103.50, 93.50)],
                  [(103.50, 93.50), (102.00, 90.83)]),
    # CHASSIS stops INSIDE the chassis island and lets the pour finish the job.
    # Driving it all the way to J401.SH meant threading past J401's NPTH latch
    # post at (97.10,87.60) and the Bob Smith resistors at y=86/90 - pointless,
    # since C411 and J401.SH are already in that island on the same net.
    "CHASSIS":   ([(110.32, 26.05), (110.32, 29.50), (112.50, 29.50),
                   (112.50, 90.00)], None),
}
# Alternate lanes tried in order when the primary corridor is blocked.
ALT_CORRIDORS = {
    "CHASSIS": [[(110.32, 26.05), (110.32, 29.5), (x, 29.5), (x, 90.0)]
                for x in (113.5, 111.5, 112.0, 109.5, 108.5, 107.5)],
    # Jog off the escape via, pick a clear vertical lane, cross on a clear
    # horizontal lane, then drop to the landing via. Tried in order; the first
    # fully clear combination wins.
    # DP's jog row must sit BELOW where DM turns (y=34.50). Jogging at y=26
    # laid DP straight across DM's descent, and since DP is routed first that
    # left DM with nowhere to go.
    "USB_DP": [[(106.75, 23.60), (106.75, jg), (xl, jg), (xl, yl),
                (43.00, yl), (43.00, 39.00)]
               for jg in (36.0, 37.5, 39.0, 35.5)
               for yl in (44.0, 46.0, 48.0, 42.0, 50.0, 52.0, 55.0)
               for xl in (103.0, 101.5, 100.0, 104.5, 98.5, 97.0)],
    # DM descends at the SMALLER x (105.25) and only ever turns LEFT; DP
    # descends at 106.75 and turns left further down. Because DM never travels
    # right of where it started, the two cannot cross - which is what every
    # jog-row variant kept doing, the pair leaving the connector 1.5 mm apart.
    "USB_DM": [([(104.60, 22.60), (104.60, yh), (41.00, yh)] if xv == 104.60
                else [(104.60, 22.60), (xv, 22.60), (xv, yh), (41.00, yh)])
               for xv in (104.60, 103.60, 102.60, 101.60, 100.60)
               for yh in (34.50, 33.00, 31.50, 36.00, 30.00, 38.00, 28.50)],
}
# Longest first: they are the ones with no alternative lane.
ORDER = ["CHASSIS", "USB_DP", "USB_DM", "ETH_CT_RD"]


def why_blocked(p, q, netcode, width, obs, clear=CLEAR):
    """Name the first obstacle a segment collides with, for diagnostics."""
    half = width / 2
    for kind, nc, g in obs:
        if nc == netcode:
            continue
        if kind == "circ":
            if seg_dist(g[0], g[1], p[0], p[1], q[0], q[1]) < half + g[2] + clear:
                return f"via/hole at ({g[0]:.2f},{g[1]:.2f}) r={g[2]:.2f} net={nc}"
        elif kind == "rect":
            if seg_rect_dist(p, q, *g) < half + clear:
                return (f"pad x{g[0]:.2f}..{g[2]:.2f} y{g[1]:.2f}..{g[3]:.2f} "
                        f"net={nc}")
        elif seg_seg_dist(p, q, (g[0], g[1]), (g[2], g[3])) < half + g[4] + clear:
            return f"track ({g[0]:.2f},{g[1]:.2f})-({g[2]:.2f},{g[3]:.2f}) net={nc}"
    return "board edge / isolation barrier"


def mm(v):
    return pcbnew.FromMM(v)


def tomm(v):
    return pcbnew.ToMM(v)


def seg_dist(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def seg_rect_dist(p, q, rx0, ry0, rx1, ry1):
    """
    Distance from segment p-q to an axis-aligned rectangle, mm; 0 if it enters.

    Pads must be treated as rectangles. Approximating them by a circle of
    max(w,h)/2 turned a 0.30 x 1.45 mm USB-C pad into a 0.72 mm-radius blob,
    which made the connector's own fanout look impossible.
    """
    for (px, py) in (p, q):
        if rx0 <= px <= rx1 and ry0 <= py <= ry1:
            return 0.0
    edges = (((rx0, ry0), (rx1, ry0)), ((rx1, ry0), (rx1, ry1)),
             ((rx1, ry1), (rx0, ry1)), ((rx0, ry1), (rx0, ry0)))
    return min(seg_seg_dist(p, q, a, b) for a, b in edges)


def _ccw(p, q, r):
    return (r[1] - p[1]) * (q[0] - p[0]) - (q[1] - p[1]) * (r[0] - p[0])


def seg_seg_dist(a, b, c, d):
    """
    Minimum distance between two segments, mm; 0 if they properly cross.

    The explicit crossing test matters. Distance-between-endpoints alone is
    blind to two segments that intersect in an X - every endpoint is far from
    the other segment, yet the tracks short. That produced 3 tracks_crossing
    violations before this was added.
    """
    if (_ccw(a, b, c) * _ccw(a, b, d) < 0) and (_ccw(c, d, a) * _ccw(c, d, b) < 0):
        return 0.0
    return min(seg_dist(a[0], a[1], c[0], c[1], d[0], d[1]),
               seg_dist(b[0], b[1], c[0], c[1], d[0], d[1]),
               seg_dist(c[0], c[1], a[0], a[1], b[0], b[1]),
               seg_dist(d[0], d[1], a[0], a[1], b[0], b[1]))


def collect(board, layer, include_inner=False):
    """
    Obstacles blocking `layer`.

    include_inner adds In1/In2 tracks. A THROUGH via passes through every layer,
    so placing one only against F.Cu and B.Cu is not enough - the USB_DP
    transition via landed 0.09 mm from a USB_CC2 track on In2 and shorted.

    Must be per-layer. An earlier version checked the short pad->via stubs on
    F.Cu against the B.Cu obstacle set, which is nearly empty - so the stubs were
    laid straight across F.Cu copper and DRC reported shorts. Vias and
    through-hole pads block every layer; SMD pads and tracks block only their own.
    """
    obs = []
    for fp in board.GetFootprints():
        for p in fp.Pads():
            smd = p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD
            if smd and not p.IsOnLayer(layer):
                continue
            bb = p.GetBoundingBox()
            obs.append(("rect", p.GetNetCode(),
                        (tomm(bb.GetLeft()), tomm(bb.GetTop()),
                         tomm(bb.GetRight()), tomm(bb.GetBottom()))))
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            pos = t.GetPosition()
            obs.append(("circ", t.GetNetCode(),
                        (tomm(pos.x), tomm(pos.y), VIA_DIA / 2)))
        elif t.GetLayer() == layer or (
                include_inner and t.GetLayer() in (pcbnew.In1_Cu, pcbnew.In2_Cu)):
            s, e = t.GetStart(), t.GetEnd()
            obs.append(("seg", t.GetNetCode(),
                        (tomm(s.x), tomm(s.y), tomm(e.x), tomm(e.y),
                         tomm(t.GetWidth()) / 2)))
    return obs


def net_endpoints(board, pad, netcode):
    """
    Places a transition via may sprout from: the pad itself, plus the far end of
    any F.Cu track already on this net that touches it.

    J102 is a USB-C connector on 0.5 mm pitch - there is simply no room for a via
    beside pad A7. But the autorouter already ran a short stub off it, and the
    end of that stub is in open space.
    """
    pos = pad.GetPosition()
    px, py = tomm(pos.x), tomm(pos.y)
    pts = [(px, py)]
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA" or t.GetNetCode() != netcode:
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = tomm(s.x), tomm(s.y), tomm(e.x), tomm(e.y)
        if math.hypot(sx - px, sy - py) < 0.3:
            pts.append((ex, ey))
        elif math.hypot(ex - px, ey - py) < 0.3:
            pts.append((sx, sy))
    return pts


def seg_ok(p, q, netcode, width, obs, clear=CLEAR):
    half = width / 2
    x0, y0, x1, y1 = BOARD_BOX
    for (px, py) in (p, q):
        if not (x0 + EDGE < px < x1 - EDGE and y0 + EDGE < py < y1 - EDGE):
            return False
    bx0, by0, bx1, by1 = BARRIER
    for (px, py) in (p, q):
        if bx0 < px < bx1 and by0 < py < by1:
            return False
    for kind, nc, g in obs:
        if nc == netcode:
            continue
        if kind == "circ":
            if seg_dist(g[0], g[1], p[0], p[1], q[0], q[1]) < half + g[2] + clear:
                return False
        elif kind == "rect":
            if seg_rect_dist(p, q, *g) < half + clear:
                return False
        else:
            if seg_seg_dist(p, q, (g[0], g[1]), (g[2], g[3])) < half + g[4] + clear:
                return False
    return True


def path_ok(pts, netcode, width, obs):
    return all(seg_ok(pts[i], pts[i + 1], netcode, width, obs)
               for i in range(len(pts) - 1))


def candidates(a, b):
    """Straight, then both L-shapes, then Z-shapes swept across the span."""
    yield [a, b]
    yield [a, (b[0], a[1]), b]
    yield [a, (a[0], b[1]), b]
    for f in (0.5, 0.35, 0.65, 0.2, 0.8, 0.1, 0.9):
        mx = a[0] + (b[0] - a[0]) * f
        my = a[1] + (b[1] - a[1]) * f
        yield [a, (mx, a[1]), (mx, b[1]), b]
        yield [a, (a[0], my), (b[0], my), b]


def find_pad(board, spec):
    ref, name = spec.split(".")
    for fp in board.GetFootprints():
        if fp.GetReference() != ref:
            continue
        for p in fp.Pads():
            if p.GetPadName() == name:
                return fp, p
    return None, None


def place_via(board, net, x, y, obs):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
    v.SetWidth(mm(VIA_DIA))
    v.SetDrill(mm(VIA_DRILL))
    v.SetViaType(pcbnew.VIATYPE_THROUGH)
    v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
    v.SetNet(net)
    board.Add(v)
    obs.append(("circ", net.GetNetCode(), (x, y, VIA_DIA / 2)))
    return v


def add_track(board, net, p, q, width, layer):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(pcbnew.VECTOR2I(mm(p[0]), mm(p[1])))
    t.SetEnd(pcbnew.VECTOR2I(mm(q[0]), mm(q[1])))
    t.SetWidth(mm(width))
    t.SetLayer(layer)
    t.SetNet(net)
    board.Add(t)


def via_spot(board, pad, netcode, obs_f, obs_b):
    """A via next to the pad (or off existing net copper); THT pads need none."""
    pos = pad.GetPosition()
    px, py = tomm(pos.x), tomm(pos.y)
    if pad.GetAttribute() != pcbnew.PAD_ATTRIB_SMD:
        return px, py, True, None         # THT pad already reaches B.Cu
    for ox, oy in net_endpoints(board, pad, netcode):
        for r in (0.8, 1.0, 1.25, 1.5, 1.8, 2.2, 2.8, 3.4, 4.0):
            for k in range(48):
                a = 2 * math.pi * k / 48
                cx, cy = ox + r * math.cos(a), oy + r * math.sin(a)
                if (seg_ok((cx, cy), (cx, cy), netcode, VIA_DIA, obs_b) and
                        seg_ok((cx, cy), (cx, cy), netcode, VIA_DIA, obs_f) and
                        seg_ok((ox, oy), (cx, cy), netcode, 0.25, obs_f)):
                    return cx, cy, False, (ox, oy)
    return None, None, False, None


def main():
    board = pcbnew.LoadBoard(BOARD)
    obs_b = collect(board, pcbnew.B_Cu)
    obs_f = collect(board, pcbnew.F_Cu)
    # A through via must clear copper on EVERY layer, not just the two it is
    # drawn on. Built once and grown as vias are placed.
    obs_via = collect(board, pcbnew.F_Cu, include_inner=True) + \
        [o for o in collect(board, pcbnew.B_Cu) if o[0] == "seg"]
    done, failed = [], []

    by_name = {c[0]: c for c in CONNECTIONS}
    for suffix in ORDER:
        _s, a_spec, b_spec, width, clear = by_name[suffix]
        fa, pa = find_pad(board, a_spec)
        fb, pb = find_pad(board, b_spec)
        net = pa.GetNet()
        nc = net.GetNetCode()
        corridor, landing = CORRIDORS[suffix]
        escape = USB_ESCAPES.get(suffix)
        if escape:
            chosen, esc_why = None, None
            for cand_esc in [escape] + ALT_ESCAPES.get(suffix, []):
                vx, vy = cand_esc[-1]
                if not seg_ok((vx, vy), (vx, vy), nc, VIA_DIA, obs_via, clear):
                    if esc_why is None:
                        esc_why = ("via " + f"({vx:.2f},{vy:.2f}): " +
                                   why_blocked((vx, vy), (vx, vy), nc,
                                               VIA_DIA, obs_via, clear))
                    continue
                seg_bad = None
                for k in range(len(cand_esc) - 1):
                    if not seg_ok(cand_esc[k], cand_esc[k + 1], nc, width,
                                  obs_f, clear):
                        seg_bad = (f"F.Cu ({cand_esc[k][0]:.2f},"
                                   f"{cand_esc[k][1]:.2f})-"
                                   f"({cand_esc[k+1][0]:.2f},"
                                   f"{cand_esc[k+1][1]:.2f}): "
                                   + why_blocked(cand_esc[k], cand_esc[k + 1],
                                                 nc, width, obs_f, clear))
                        break
                if seg_bad is None:
                    chosen = cand_esc
                    break
                if esc_why is None:
                    esc_why = seg_bad
            if chosen is None:
                failed.append((suffix, f"no clear escape; 1st: {esc_why}"))
                continue
            if False:
                # Do NOT fall through to the primary. Silently reusing it is how
                # a via that overlapped a USB_CC2 track on In2 got placed anyway.
                failed.append((suffix, "no escape whose via clears all layers"))
                continue
            escape = chosen
            corridor = [escape[-1]] + list(corridor[1:])
        options = [corridor] + [[escape[-1]] + list(c[1:]) if escape else c
                                for c in ALT_CORRIDORS.get(suffix, [])]

        bad, polylines, first_bad = None, None, None
        for cand in options:
            polylines = []                   # (points, layer)
            if escape:
                polylines.append((escape, pcbnew.F_Cu))
            if landing:
                polylines.append((landing, pcbnew.F_Cu))
            polylines.append((cand, pcbnew.B_Cu))
            bad = None
            for pts, layer in polylines:
                obs = obs_f if layer == pcbnew.F_Cu else obs_b
                for k in range(len(pts) - 1):
                    if not seg_ok(pts[k], pts[k + 1], nc, width, obs, clear):
                        bad = (f"{'F.Cu' if layer == pcbnew.F_Cu else 'B.Cu'} "
                               f"({pts[k][0]:.2f},{pts[k][1]:.2f})-"
                               f"({pts[k+1][0]:.2f},{pts[k+1][1]:.2f}): "
                               + why_blocked(pts[k], pts[k + 1], nc, width, obs, clear))
                        break
                if bad:
                    break
            if not bad:
                corridor = cand
                break
            if first_bad is None:
                first_bad = bad
        if bad:
            bad = f"(1st candidate) {first_bad}"
            failed.append((suffix, bad))
            continue

        # Transition vias wherever an F.Cu polyline meets the B.Cu corridor.
        for pts, layer in polylines:
            obs = obs_f if layer == pcbnew.F_Cu else obs_b
            for k in range(len(pts) - 1):
                add_track(board, net, pts[k], pts[k + 1], width, layer)
                obs.append(("seg", nc, (pts[k][0], pts[k][1],
                                        pts[k + 1][0], pts[k + 1][1], width / 2)))
        for vx, vy in ([corridor[0]] if escape else []) + \
                      ([corridor[-1]] if landing else []):
            place_via(board, net, vx, vy, obs_b)
            obs_f.append(("circ", nc, (vx, vy, VIA_DIA / 2)))
            obs_via.append(("circ", nc, (vx, vy, VIA_DIA / 2)))

        length = sum(math.hypot(corridor[k + 1][0] - corridor[k][0],
                                corridor[k + 1][1] - corridor[k][1])
                     for k in range(len(corridor) - 1))
        done.append((suffix, a_spec, b_spec, len(corridor) - 1, length))

    pcbnew.SaveBoard(BOARD, board)
    for suffix, a, b, segs, length in done:
        print(f"  {suffix:<10} {a:<9} -> {b:<9} {segs} seg, {length:5.1f} mm on B.Cu")
    print(f"routed : {len(done)}/{len(CONNECTIONS)}")
    for f in failed:
        print(f"  FAILED {f[0]}: {f[1]}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
