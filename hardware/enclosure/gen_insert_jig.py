#!/usr/bin/env python3
"""Build the heat-set insert jig for the CANary one-piece case and export STEP/STL.

The press is duck.knapp's "Heat Set Insert Press (99% 3D-Printed)" (MakerWorld, CC BY-NC-SA;
none of its geometry is in this repo, only the measurements below). Its base is a 240 mm
square bed with a wall along two edges -- an L, its inside corner an R50 arc -- and a tower
at each end of the L. The linkage between the towers is symmetric, so the iron comes down
on the L's diagonal; how far along it depends on the iron in the clamp.

The case's eight M3 inserts go in along the tube's axis, four into each end face, so the
tube has to stand on end under the tip and be moved until each pilot is under it in turn.
Three parts:

    plate   sits on the bed with two straight edges against the inside faces of the L,
            which fixes it; carries a square socket for every position the nest takes,
            and a countersunk hole exactly under the tip for checking the setting
    nest    a cradle the tube stands in, end down, 3 mm floor and a 12 mm collar; relief
            holes under the lower end's pilots so inserts already in it cannot rock it;
            two keyed holes, F and R, for the peg
    peg     one loose keyed peg: in the nest's F hole with the FRONT end up, in its R hole
            with the REAR end up. It drops into a plate socket and locates the nest.

Using it: stand the tube in the nest with the end you are doing UP and the insert you want
at the nest's NOTCHED end (toward the L's corner) -- only one of the two ways round puts
it there. Peg in F (front up) or R (rear up). Drop the peg into the socket named for that
insert (plate legend and README), lower the cold tip onto the pilot to check, then press.
The front end is the etherCON end; the rear end is the one nearest the LED window.

Always pressing at the corner end is what makes this fit: the tube is 137 mm long and its
pilots sit up to 60 mm off centre, so whichever end is under the tip the other end reaches
~130 mm away. Toward the L's corner there is only ~100 mm; toward the open side of the bed
there is room. The tube therefore always hangs forward, toward the open side.

TIP_FROM_WALL is a MEASUREMENT, not a derived number: with the press built, lower the tip
to the bed and measure from the tip's axis to the inside face of each wall. The default is
an estimate from the model and the designer's photos (iron ~24 mm in front of the arm
plane). Rebuild with `--tip X Y` once measured; the countersunk hole under the tip shows at
a glance whether the plate is right.

Run:  <venv>/bin/python hardware/enclosure/gen_insert_jig.py [--tip X Y] [outdir]
"""
import math
import pathlib
import sys

_ARGV = sys.argv[1:]
_TIP = None
if "--tip" in _ARGV:
    i = _ARGV.index("--tip")
    _TIP = (float(_ARGV[i + 1]), float(_ARGV[i + 2]))
    del _ARGV[i:i + 3]
# The case geometry comes from the case generator itself, as the one-piece tube.
sys.argv = [sys.argv[0], "--tube"]
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cadquery as cq                                   # noqa: E402
import gen_case_3dp as case                             # noqa: E402

OUT = pathlib.Path(_ARGV[0] if _ARGV else "hardware/enclosure/jig")

# ---- the press, measured from its model (main_V3) ---------------------------
# Frame: origin at the TIP's axis on the bed surface, X and Y along the two walls, Z up.
# Wall inside faces at x = -TIP_FROM_WALL[0] and y = -TIP_FROM_WALL[1]; the inside corner
# is an R50 arc centred 50 mm in from both faces, so it meets them 50 mm from the corner.
TIP_FROM_WALL = _TIP or (86.7, 86.7)        # MEASURE ME -- see the docstring
CORNER_R = 50.0
WALL_ROOT = 0.7             # fillet at the wall's foot; the plate's lower edge clears it
WALL_STRAIGHT = 120.0       # straight inside face beyond the arc, before the tower
BED_HALF = 120.0            # the bed is 240 square, centred 90 + 30 in from each wall face
BED_EDGE = 2.0              # keep the plate this far inside the bed's far edges

# ---- the jig -----------------------------------------------------------------
PLATE_T = 4.0
PLATE_WALL_CLEAR = 0.3      # plate edge vs wall face: it is pushed against them in use
PLATE_CHAMFER = 1.0         # 45-deg on the plate's lower edges, over WALL_ROOT
NEST_FLOOR = 3.0
NEST_WALL = 3.0
NEST_COLLAR = 12.0          # collar height above the floor
NEST_CLEAR = 0.3            # per side, tube vs collar
NEST_NOTCH = (8.0, 3.0)     # V notch in the collar rim at the press end: width, depth
RELIEF_D = 7.0              # under the lower end's pilots: a proud insert sits in it
PEG = 5.0                   # peg section, square, one corner chamfered as the key
PEG_KEY = 1.8               # that corner's chamfer leg
PEG_CLEAR = 0.15            # per side, peg vs nest hole and vs plate socket
PEG_CAP = (9.0, 1.0)        # cap on the peg's top: stops it dropping through the nest
PEG_BELOW = PLATE_T - 0.5   # how far the peg reaches down into the plate socket
PEG_F_U, PEG_R_U = -10.0, 10.0      # the two peg holes, nest frame, on the tube's axis line
TIP_CHECK_D, TIP_CHECK_CSK = 2.5, 7.0
LABEL_CAP, LABEL_DEPTH = 4.0, 0.6
SOCKET_WEB_MIN = 2.0       # plastic left between two sockets
LABEL_OFF = 7.5            # socket centre to its label's centre, first try
LABEL_KEEP = 1.0           # label box vs any socket, and vs another label
LEGEND_CAP = 3.5
LEGEND_UV = (-40.0, 0.0)   # the legend's first line, nest plan: toward the corner

L = case.TUBE_L
A, B = case.OUTER_A, case.OUTER_B
SQ2 = math.sqrt(2.0)


def to_xy(u, v):
    """Nest-plan (u toward the open side of the bed, v across) -> press XY."""
    return ((u - v) / SQ2, (u + v) / SQ2)


# ---- where every pilot is, and where the nest has to be for it -----------------
# Physical tube frame: x across (exported mirror of the board frame), y along (front +),
# z toward the lid. Stood on end and seen from above, a pilot at (x, z) of the UP end
# lands at plan (u, v) = (-x, z) with the front end up and (x, z) with the rear end up
# (the viewer's right is -x at the front face and +x at the rear). The case generator
# works in the board frame, where x_phys = -x_board.
def pilots():
    """[(label, end, u, v, rot)] -- one per insert, rot 180 when the tube goes in turned."""
    out = []
    names = {}
    for (xb, z) in case.tube_screws():
        side = "boss" if z > 0 else "rail"
        for end in ("F", "R"):
            xp = -xb
            u = -xp if end == "F" else xp
            # Seen from outside this end with the lid up, is the insert on the left or
            # the right? Right = +u in both cases, by the plan mapping above.
            lr = "right" if u > 0 else "left"
            rot = u > 0                              # turn the tube so it is at -u
            uu, vv = (-u, -z) if rot else (u, z)
            names.setdefault(end, []).append((f"{lr} {side}", uu, vv, rot))
    for end in ("F", "R"):
        for i, (nm, u, v, rot) in enumerate(sorted(names[end], key=lambda t: (t[1], t[2]))):
            out.append((f"{end}{i + 1}", nm, u, v, rot))
    return out


def sockets():
    """[(label, name, S_xy, C_uv, rot, end)]: socket centre in press XY, nest centre."""
    out = []
    for (label, name, u, v, rot) in pilots():
        cu, cv = -u, -v                              # nest centre puts that pilot at 0,0
        pu = PEG_F_U if label[0] == "F" else PEG_R_U
        out.append((label, name, to_xy(cu + pu, cv), (cu, cv), rot, label[0]))
    return out


# ---- solids ------------------------------------------------------------------
def peg_profile(w):
    """The keyed peg section, w square, corner (+,+) chamfered, centred on 0,0."""
    h, k = w / 2.0, PEG_KEY + (w - PEG) / 2.0 * (2.0 - SQ2)
    return [(-h, -h), (h, -h), (h, h - k), (h - k, h), (-h, h)]


def keyed(w, z0, z1, u, v, rot_deg=0.0):
    """A keyed prism in the NEST's plan frame at (u, v)."""
    return (cq.Workplane("XY").polyline(peg_profile(w)).close().extrude(z1 - z0)
            .rotate((0, 0, 0), (0, 0, 1), rot_deg)
            .translate((u, v, z0)))


def section_uv(a, b, h, z0=0.0):
    """The tube's outer section as a prism in the nest's plan frame (u = x, v = z)."""
    pts = case.se_points(a, b, 128)
    return cq.Workplane("XY").polyline(pts).close().extrude(h).translate((0, 0, z0))


def build_nest():
    """Nest in its own frame: plan (u, v), floor on z = 0."""
    h = NEST_FLOOR + NEST_COLLAR
    nest = section_uv(A + NEST_CLEAR + NEST_WALL, B + NEST_CLEAR + NEST_WALL, h)
    nest = nest.cut(section_uv(A + NEST_CLEAR, B + NEST_CLEAR, h + 1.0, NEST_FLOOR))
    # Relief under every pilot position either end can present, both ways round.
    for (xb, z) in case.tube_screws():
        for su in (-1, 1):
            for sv in (-1, 1):
                nest = nest.cut(cq.Workplane("XY").circle(RELIEF_D / 2.0).extrude(h)
                                .translate((su * xb, sv * z, -0.5)))
    # The press end (-u): a V notch in the collar's rim.
    w, d = NEST_NOTCH
    notch = (cq.Workplane("YZ").polyline([(-w / 2.0, h + 1.0), (w / 2.0, h + 1.0),
                                          (0.0, h - d)]).close()
             .extrude(4 * NEST_WALL).translate((-(A + NEST_CLEAR + 2 * NEST_WALL), 0, 0)))
    nest = nest.cut(notch)
    # The two peg holes, and their letters engraved in the floor's top beside them.
    for pu, letter in ((PEG_F_U, "F"), (PEG_R_U, "R")):
        nest = nest.cut(keyed(PEG + 2 * PEG_CLEAR, -1.0, NEST_FLOOR + 1.0, pu, 0.0))
        t = (reading(case.text_page(letter, LABEL_CAP * 1.5, case.FONT_BOLD, 0.0, 0.0,
                                    LABEL_DEPTH + 1.0))
             .translate((pu, -(PEG / 2.0 + 2.0 + LABEL_CAP), NEST_FLOOR - LABEL_DEPTH)))
        nest = nest.cut(t)
    return nest


def build_peg():
    """The loose peg, in the nest frame at the origin: cap on top of the floor."""
    # the prism runs 0.5 mm up into the cap, so the union overlaps rather than touches;
    # the cap's underside sits ON the floor
    peg = keyed(PEG, -PEG_BELOW, NEST_FLOOR + 0.5, 0.0, 0.0)
    cap = (cq.Workplane("XY").rect(*[PEG_CAP[0]] * 2).extrude(PEG_CAP[1])
           .edges("|Z").fillet(1.0).translate((0, 0, NEST_FLOOR)))
    return peg.union(cap)


def nest_to_press(solid, cu, cv, z0):
    """Place a nest-frame solid: centre at (cu, cv), u along the bed's diagonal."""
    return (solid.translate((cu, cv, 0))
            .rotate((0, 0, 0), (0, 0, 1), 45.0)
            .translate((0, 0, z0)))


def press_free():
    """The bed's free area inside the L, as a solid slab (for containment checks)."""
    wx, wy = TIP_FROM_WALL
    # the bed runs from 30 mm behind the wall faces to 210 mm in front of them
    far_x, far_y = -wx + 2 * BED_HALF - 30.0 - BED_EDGE, -wy + 2 * BED_HALF - 30.0 - BED_EDGE
    c = PLATE_WALL_CLEAR
    box = (cq.Workplane("XY").box(far_x + wx - c, far_y + wy - c, 400.0,
                                  centered=(False, False, False))
           .translate((-wx + c, -wy + c, -1.0)))
    # the corner arc: outside the R50 circle but in its square is wall
    cx, cy = -wx + CORNER_R, -wy + CORNER_R
    corner = (cq.Workplane("XY").box(CORNER_R + 1.0, CORNER_R + 1.0, 402.0,
                                     centered=(False, False, False))
              .translate((-wx - 1.0, -wy - 1.0, -2.0)))
    disc = (cq.Workplane("XY").circle(CORNER_R - c).extrude(404.0)
            .translate((cx, cy, -3.0)))
    return box.cut(corner.cut(disc))


def plate_outline(socks):
    """The plate's outline, solid: every nest footprint plus two pads on the walls."""
    wx, wy = TIP_FROM_WALL
    c = PLATE_WALL_CLEAR
    # Outline = convex hull of every nest footprint plus two pads along the walls.
    na, nb = A + NEST_CLEAR + NEST_WALL, B + NEST_CLEAR + NEST_WALL
    pts = []
    for (_, _, _, (cu, cv), _, _) in socks:
        for su in (-1, 1):
            for sv in (-1, 1):
                pts.append(to_xy(cu + su * (na + 1.0), cv + sv * (nb + 1.0)))
    # the straight part of each wall starts CORNER_R from the corner
    pts += [(-wx + c, -wy + CORNER_R + 1.0), (-wx + c, 25.0),
            (-wx + CORNER_R + 1.0, -wy + c), (25.0, -wy + c)]
    hull = convex_hull(pts)
    return (cq.Workplane("XY").polyline(hull).close().extrude(PLATE_T)
            .intersect(press_free()))


def build_plate(socks):
    """The index plate, press frame, bottom on z = 0."""
    plate = plate_outline(socks).faces("<Z").edges().chamfer(PLATE_CHAMFER)
    boxes = label_boxes(socks)
    # sockets and their labels
    for (label, name, (sx, sy), (cu, cv), rot, end) in socks:
        plate = plate.cut(nest_to_press(keyed(PEG + 2 * PEG_CLEAR, -1.0, PLATE_T + 1.0,
                                              0.0, 0.0), 0, 0, 0)
                          .translate((sx, sy, 0)))
        # label beside its socket (label_boxes() finds the spot)
        if label not in boxes:
            continue
        u0, u1, v0, v1 = boxes[label]
        lu, lv = (u0 + u1) / 2.0, (v0 + v1) / 2.0
        t = reading(case.text_page(label, LABEL_CAP, case.FONT_BOLD, 0.0, -LABEL_CAP / 2.0,
                                   LABEL_DEPTH + 1.0))
        plate = plate.cut(nest_to_press(t, lu, lv, PLATE_T - LABEL_DEPTH))
    # the legend, in the corner no nest ever covers
    lines = ("F  FRONT END UP", "R  REAR END UP", "INSERT AT THE NOTCH")
    for i, txt in enumerate(lines):
        t = reading(case.text_page(txt, LEGEND_CAP, case.FONT_BOLD, 0.0,
                                   -i * LEGEND_CAP * 1.8, LABEL_DEPTH + 1.0))
        plate = plate.cut(nest_to_press(t, *LEGEND_UV, PLATE_T - LABEL_DEPTH))
    # the tip check: a countersunk hole exactly under the tip
    plate = plate.cut(cq.Workplane("XY").circle(TIP_CHECK_D / 2.0).extrude(PLATE_T + 2.0)
                      .translate((0, 0, -1.0)))
    csk = TIP_CHECK_CSK / 2.0
    plate = plate.cut(cq.Solid.makeCone(0.0, csk + 1.0, csk + 1.0,
                                        pnt=cq.Vector(0, 0, PLATE_T - csk)))
    return plate


def reading(page):
    """Turn a text page (x along the line, y up the letters) into the nest plan so it
    reads left to right for someone at the open side of the bed, facing the L's corner:
    their right is +v and the tops of the letters point away from them, to -u."""
    return page.rotate((0, 0, 0), (0, 0, 1), 90.0)


def label_width(label):
    return case.text_page(label, LABEL_CAP, case.FONT_BOLD, 0, 0, 1).val().BoundingBox().xlen


def label_boxes(socks):
    """{label: (u0, u1, v0, v1)} in the nest plan: each label placed next to its socket.

    Tried outward from the cluster first, then round the socket in 45-degree steps and
    further out, taking the first spot clear of every socket and every label already
    placed and nearer its own socket than any other -- the sockets are only ~9 mm apart.
    """
    hw = (PEG + 2 * PEG_CLEAR) / 2.0
    pts = {sk[0]: rotate_uv(*sk[2]) for sk in socks}
    cu = sum(u for u, v in pts.values()) / len(pts)
    cv = sum(v for u, v in pts.values()) / len(pts)
    placed = {}

    def clear(box, name):
        u0, u1, v0, v1 = box
        for n, (su, sv) in pts.items():
            if (u0 - LABEL_KEEP < su + hw and u1 + LABEL_KEEP > su - hw
                    and v0 - LABEL_KEEP < sv + hw and v1 + LABEL_KEEP > sv - hw):
                return False
        for (a0, a1, b0, b1) in placed.values():
            if u0 - LABEL_KEEP < a1 and u1 + LABEL_KEEP > a0 \
                    and v0 - LABEL_KEEP < b1 and v1 + LABEL_KEEP > b0:
                return False
        mid = ((u0 + u1) / 2, (v0 + v1) / 2)
        return min(pts, key=lambda n: math.dist(mid, pts[n])) == name

    for name, (u, v) in sorted(pts.items(), key=lambda t: -math.dist(t[1], (cu, cv))):
        w = label_width(name)
        out = math.atan2(v - cv, u - cu)
        for r in (LABEL_OFF, LABEL_OFF + 2.0, LABEL_OFF + 4.0):
            for k in (0, 1, -1, 2, -2, 3, -3, 4):
                a = out + k * math.pi / 4.0
                lu, lv = u + r * math.cos(a), v + r * math.sin(a)
                box = (lu - LABEL_CAP / 2, lu + LABEL_CAP / 2, lv - w / 2, lv + w / 2)
                if clear(box, name):
                    placed[name] = box
                    break
            if name in placed:
                break
    return placed


def outside(solid, region):
    """Volume of solid NOT inside region, mm3 (0 when the cut leaves nothing)."""
    try:
        return solid.cut(region).val().Volume()
    except Exception:
        return 0.0


def rotate_uv(x, y):
    """Press XY -> nest-plan (u, v)."""
    return ((x + y) / SQ2, (y - x) / SQ2)


def convex_hull(pts):
    pts = sorted(set((round(x, 4), round(y, 4)) for x, y in pts))

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, hi = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(hi) >= 2 and cross(hi[-2], hi[-1], p) <= 0:
            hi.pop()
        hi.append(p)
    return lo[:-1] + hi[:-1]


# ---- the tube, posed -------------------------------------------------------
def tube_physical():
    """The built tube in its physical frame (the case generator's export mirror)."""
    return case.build_tube().mirror("YZ")


def pose_tube(tube, end, rot, cu, cv, z0):
    """Stand the physical tube on end in the nest and put the nest at (cu, cv)."""
    if end == "F":
        # (x, y, z) -> (u, v, Z) = (-x, z, y): front end up
        t = tube.rotate((0, 0, 0), (1, 0, 0), 90).rotate((0, 0, 0), (0, 0, 1), 180)
    else:
        # (x, y, z) -> (x, z, -y): rear end up
        t = tube.rotate((0, 0, 0), (1, 0, 0), -90)
    if rot:
        t = t.rotate((0, 0, 0), (0, 0, 1), 180)
    return nest_to_press(t.translate((0, 0, L / 2.0)), cu, cv, z0)


def probe(solid, x, y, z0, z1, d):
    try:
        return solid.intersect(cq.Workplane("XY").circle(d / 2.0).extrude(z1 - z0)
                               .translate((x, y, z0))).val().Volume()
    except Exception:
        return 0.0


def verify(plate, nest, peg, socks):
    errs = []
    labels = [s[0] for s in socks]
    if len(set(labels)) != 8:
        errs.append(f"expected 8 distinct sockets, got {labels}")
    # sockets apart from each other: the web between two keyed holes. They are all square
    # to the nest's (u, v), so the web is the larger axis gap less one hole.
    for i, a in enumerate(socks):
        for b in socks[i + 1:]:
            (au, av), (bu, bv) = rotate_uv(*a[2]), rotate_uv(*b[2])
            web = max(abs(au - bu), abs(av - bv)) - (PEG + 2 * PEG_CLEAR)
            if web < SOCKET_WEB_MIN:
                errs.append(f"sockets {a[0]} and {b[0]} leave a {web:.1f} mm web")
    # label_boxes() only places a label where it is clear and unambiguous
    missing = [sk[0] for sk in socks if sk[0] not in label_boxes(socks)]
    if missing:
        errs.append(f"no clear spot for the label of socket(s) {', '.join(missing)}")
    free = press_free()
    if outside(plate, free) > 0.5:
        errs.append("the plate runs into the press's wall")
    tube = tube_physical()
    z_nest = PLATE_T
    z_tube = PLATE_T + NEST_FLOOR
    top = z_tube + L
    for (label, name, (sx, sy), (cu, cv), rot, end) in socks:
        posed = pose_tube(tube, end, rot, cu, cv, z_tube)
        # 1. the tip lands in an open pilot: nothing within 1.2 mm of the axis in the top
        #    3 mm, and material in a ring just outside the 3.7 mm pilot
        if probe(posed, 0, 0, top - 3.0, top - 0.2, 2.4) > 0.01:
            errs.append(f"{label} ({name}): no open pilot under the tip")
        ring = sum(probe(posed, 2.9 * math.cos(a), 2.9 * math.sin(a), top - 3.0,
                         top - 0.2, 0.6) for a in (0, math.pi / 2, math.pi, 1.5 * math.pi))
        if ring < 0.2:
            errs.append(f"{label} ({name}): no boss or rail around the tip")
        # 2. the tube stands inside the nest, the nest's peg hole is over this socket
        nb = nest_to_press(nest, cu, cv, z_nest)
        if posed.intersect(nb).val().Volume() > 0.5:
            errs.append(f"{label}: the tube hits the nest")
        pu = PEG_F_U if end == "F" else PEG_R_U
        px, py = to_xy(cu + pu, cv)
        if math.dist((px, py), (sx, sy)) > 0.01:
            errs.append(f"{label}: peg hole at {px:.2f},{py:.2f} is not over its socket")
        pegw = nest_to_press(peg.translate((pu, 0, 0)), cu, cv, z_nest)
        if pegw.intersect(plate).val().Volume() > 0.05:
            errs.append(f"{label}: the peg does not drop into its socket")
        if pegw.intersect(nb).val().Volume() > 0.05:
            errs.append(f"{label}: the peg does not fit the nest's {end} hole")
        if pegw.intersect(posed).val().Volume() > 0.05:
            errs.append(f"{label}: the peg's cap is under the tube's wall")
        # 3. nothing of tube or nest in the wall, and the nest wholly on the plate
        # (by what is left OUTSIDE, not by comparing whole volumes: OCC's Volume() on the
        # spline-sectioned tube wanders by more than the tolerance between two booleans)
        for what, s in (("tube", posed), ("nest", nb)):
            if outside(s, free) > 0.5:
                errs.append(f"{label}: the {what} runs into the press's wall")
        # the nest's foot wholly over the plate's outline (its holes do not count)
        foot = nb.intersect(cq.Workplane("XY").box(600, 600, 0.4)
                            .translate((0, 0, z_nest + 0.2)))
        off = outside(foot, plate_outline(socks).translate((0, 0, 0.4)))
        if off > 0.5:
            errs.append(f"{label}: {off / 0.4:.0f} mm2 of the nest's foot is off the plate")
    return errs


def main():
    socks = sockets()
    print("CANary insert jig -- tip "
          f"{TIP_FROM_WALL[0]:.1f} / {TIP_FROM_WALL[1]:.1f} mm from the wall faces")
    plate = build_plate(socks)
    nest = build_nest()
    peg = build_peg()
    errs = verify(plate, nest, peg, socks)
    for (label, name, (sx, sy), (cu, cv), rot, end) in socks:
        up = "front" if end == "F" else "rear"
        print(f"  {label}: {up} end up, {name:11s} (seen from outside that end, lid up)"
              f" -- socket at x {sx:+6.1f} y {sy:+6.1f}")
    for e in errs:
        print(f"  ! {e}")
    if errs:
        print("\nJIG VERIFICATION FAILED -- nothing written")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    top = PLATE_T + NEST_FLOOR + L
    print(f"  the tube's top face stands {top:.1f} mm above the bed: the tip, with its "
          f"insert on, has to clear that")
    # Exported in PRINT orientation, so bambu/build.sh can take them as they are: the
    # plate and nest already lie on their undersides; the peg goes cap-down.
    peg_print = peg.rotate((0, 0, 0), (1, 0, 0), 180.0)
    for name, solid in (("canary_jig_plate", plate), ("canary_jig_nest", nest),
                        ("canary_jig_peg", peg_print)):
        cq.exporters.export(solid, str(OUT / f"{name}.step"))
        cq.exporters.export(solid, str(OUT / f"{name}.stl"),
                            tolerance=0.01, angularTolerance=0.1)
        leak = case.mesh_leaks(OUT / f"{name}.stl")
        if leak:
            print(f"  ! {name}.stl {leak}")
            return 1
        bb = solid.val().BoundingBox()
        vol = solid.val().Volume() / 1000.0
        print(f"  {name:18s} {bb.xlen:6.1f} x {bb.ylen:6.1f} x {bb.zlen:5.1f} mm"
              f"  {vol:6.1f} cm3")
    print(f"  wrote 3 parts -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
