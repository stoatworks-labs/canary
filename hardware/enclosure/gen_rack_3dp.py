#!/usr/bin/env python3
"""Build a 3D-printable rack panel for one CANary tube and export STEP/STL.

The tube (`gen_case_3dp.py --tube`) is 137 x 45 mm in section and 93.5 mm long, with flush
end plates screwed on by four M3 x 8 into heat-set inserts. The panel holds the whole unit,
front plate and all, in a collar round its body:

  * a RING that goes all the way round, D_RING deep behind the face;
  * behind the ring, a TROUGH: the same wall under the tube and over both curved
    shoulders, the tube's full length. It leaves the middle of the lid open, where the
    LED window, the service pinholes, the switch cover and the lettering are;
  * at the face, a LIP round the tube's front end and two CHEEKS over its left and right
    ends, where the front plate's four screws are. The tube slides in from behind until
    its front plate meets them, and four M3 x 12 go through the cheeks, the front plate
    and into the tube's own inserts, in place of its four M3 x 8. Between the cheeks the
    face is open: the three etherCONs and their labels are seen and reached as on a desk.

Why 2U: the tube is 45.0 mm tall and a 1U panel is 43.66 mm (44.45 less the EIA 0.8 mm
gap). So the panel is 2U, 88.1 mm, with the tube centred.

    19-inch  the unit in the middle and a flat blank to each side. 482.6 mm does not fit
             a 320 mm bed, so the panel is three pieces: the centre (the collar) and two
             wings carrying the ears. They bolt together through ribs behind each seam:
             2 x M3 x 12 and a nut per seam, the nut captive in the higher-x piece's pad.
             The front edges are chamfered, so a seam reads as a V-groove, not a crack.
    10-inch  the same collar with short wings, one piece, and the Stoatworks mark.

Every piece prints FACE DOWN: the front face on the plate, everything else growing up from
it. Nothing overhangs -- the collar, flanges, ribs and pads are vertical walls, the seam
bolts are teardrops pointing up and the nut traps stand on a vertex.

What is NOT verified: none of this has been printed. The collar fit (0.4 mm a side), the
seam bolts and the ear slots are numbers, not trials. In a rack the lid's LEDs face the
unit above, not the front.

Run:  <venv>/bin/python hardware/enclosure/gen_rack_3dp.py [outdir]
"""
import math
import pathlib
import sys

_ARGV = sys.argv[1:]
# The tube's geometry comes from the case generator itself, as the one-piece tube.
sys.argv = [sys.argv[0], "--tube"]
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cadquery as cq                                   # noqa: E402
import gen_case_3dp as case                             # noqa: E402

OUT = pathlib.Path(_ARGV[0] if _ARGV else "hardware/enclosure/rack")

# Frame: the tube generator's PHYSICAL frame (its export mirror applied). x across, y from
# back to front (the etherCON end is +y), z up, the tube centred on the origin. Read from
# the front, your right is -x.

# ---- the rack (EIA-310 / the common 10-inch size) ----------------------------
U = 44.45
UNITS = 2
PANEL_H = UNITS * U - 0.8                 # 88.1: n x U less the standard 0.8 mm gap
HOLE_Z = (-(U - 6.35), +(U - 6.35))       # +/-38.1: the outer hole of each U, 3 in apart
RACKS = {
    # width over the ears, ear-hole centres, clear opening between the rails
    "19": dict(width=482.6, holes=465.1, opening=450.85),
    "10": dict(width=254.0, holes=236.5, opening=222.25),
}
EAR_SLOT = (9.5, 6.5)                     # horizontal stadium: M5/M6/10-32 with play
W_CENTRE = 160.0                          # the 19-inch centre piece; the wings are the rest

# ---- the panel ----------------------------------------------------------------
T_FACE = 4.0                              # face = cheek: the screws grow by this, 8 -> 12
YR = case.OUTER_L / 2.0                   # back of the face = the tube's front face
YF = YR + T_FACE                          # front face
DEPTH = 16.0                              # flanges and ribs, back from YR
FLANGE_T = 3.0
RIB_T = 3.0
RIB_CLEAR = 0.75                          # side rib's outer face inside the clear opening
CHAMFER = 0.6                             # every front-face edge: seams become V-grooves

# ---- the collar ---------------------------------------------------------------
FIT = 0.4                                 # per side, tube outline vs collar
WALL_C = 3.0                              # collar wall (7 lines at 0.42)
D_RING = 12.0                             # full ring, back from the face; the lid's
                                          # lettering starts 14.4 mm back, its switch
                                          # pocket's notch 17 mm
D_TROUGH = case.OUTER_L                   # the trough runs the tube's whole length
X_SHOULDER = 54.0                         # the trough covers the lid only outboard of
                                          # this; the LED window's rebate ends at 48.5
LIP = 1.5                                 # face over the front end, inside the outline
X_CHEEK = 44.0                            # the face is open between +/- this; the
                                          # etherCON flanges reach 40.5, the screws 47

# ---- fasteners ----------------------------------------------------------------
SCREW_STOCK = 8.0                         # the tube's own end-plate screws, M3 x 8
SCREW_RACK = SCREW_STOCK + T_FACE         # = 12: same thread engagement through a cheek
HEAD_D = case.SCREW_HEAD_D                # 6.2: button head 5.7 with margin
SEAM_BOLT_Z = 33.0                        # above and below the collar (its top is 25.9)
PAD_T = 3.0                               # pad on the rib round each bolt
PAD_Z0 = 28.0                             # pad from here out to the flange
BOLT_D = 3.4                              # M3 clearance
NUT_AF = 5.5 + 0.35                       # M3 nut, 5.5 across flats, + print clearance
NUT_DEPTH = 2.6                           # nut 2.4 thick
BOLT_Y = YR - DEPTH / 2.0

# ---- lettering ----------------------------------------------------------------
LABEL_CAP = 5.0                           # the name above the unit
LABEL_BASE = 28.5
MARK_W = 30.0
MARK_X = {"19": 110.0, "10": 92.0}        # physical x, your left of the unit


# ===========================================================================
# Primitives
# ===========================================================================
def box(x0, x1, y0, y1, z0, z1):
    return cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0).translate(
        ((x0 + x1) / 2.0, (y0 + y1) / 2.0, (z0 + z1) / 2.0))


def xteardrop(d, y, z, x0, x1):
    """A bore along X with its point at -Y, which is UP as the piece prints."""
    r = d / 2.0
    k = r / math.sqrt(2.0)
    wp = cq.Workplane("YZ", origin=(x0, 0, 0))     # local x = y, local y = z, normal +x
    disc = wp.center(y, z).circle(r).extrude(x1 - x0)
    tip = (cq.Workplane("YZ", origin=(x0, 0, 0))
           .polyline([(y - k, z + k), (y - r * math.sqrt(2.0), z), (y - k, z - k)]).close()
           .extrude(x1 - x0))
    return disc.union(tip)


def xhex(af, y, z, x0, x1):
    """A hex pocket along X, a vertex at -Y (up as printed) so its roof is self-supporting."""
    return (cq.Workplane("YZ", origin=(x0, 0, 0)).center(y, z)
            .polygon(6, 2.0 * af / math.sqrt(3.0)).extrude(x1 - x0))


def ystadium(w, h, x, z, y0, y1):
    return (cq.Workplane("XY", origin=(x, y0, z)).transformed(rotate=(-90, 0, 0))
            .slot2D(w, h).extrude(y1 - y0))


def on_face(solid, x_origin):
    """Place a page-frame solid (u right, v up, extruded +z) on the front face.

    Read from the front, u runs to -x and v up z; the page's +z goes out through the face.
    The page is set LETTER_DEPTH behind the face, so a cut with it is that deep.
    """
    plane = cq.Plane(origin=(x_origin, YF - case.LETTER_DEPTH, 0.0),
                     xDir=(-1, 0, 0), normal=(0, 1, 0))
    return cq.Workplane("XY").add(solid.val().moved(cq.Location(plane)))


def face_slab(outside):
    d = case.LETTER_DEPTH
    return box(-400, 400, YF - d, YF + outside, -100, 100)


def screws_physical():
    """[(x, z)] of the tube's front-plate screws, in this (mirrored) frame."""
    return [(-x, z) for (x, z) in case.tube_screws()]


# ===========================================================================
# The collar
# ===========================================================================
def collar():
    """Ring + trough, rooted 0.5 mm into the face so the union is a real overlap."""
    a, b = case.OUTER_A + FIT, case.OUTER_B + FIT
    y0, y1 = YR - D_TROUGH, YR + 0.5
    yc, L = (y0 + y1) / 2.0, y1 - y0
    shell = case.section_prism(a + WALL_C, b + WALL_C, L, yc).cut(
        case.section_prism(a, b, L + 2.0, yc))
    # Behind the ring, open the lid between the shoulders. The cutter's floor at z 0 is in
    # air (the wall there is at |x| > 68), so it shares no face with the shell.
    return shell.cut(box(-X_SHOULDER, X_SHOULDER, y0 - 1.0, YR - D_RING, 0.0, 60.0))


def aperture():
    """The window in the face: inside the lip, between the cheeks, through the face."""
    y0, y1 = YR - 1.0, YF + 1.0
    return case.section_prism(case.OUTER_A - LIP, case.OUTER_B - LIP, y1 - y0,
                              (y0 + y1) / 2.0).intersect(
        box(-X_CHEEK, X_CHEEK, y0 - 1.0, y1 + 1.0, -50.0, 50.0))


def cheek_holes():
    c = None
    for (x, z) in screws_physical():
        h = case.ybore(case.SCREW_CLEAR_D, x, z, YR - 1.0, YF + 1.0)
        c = h if c is None else c.union(h)
    return c


# ===========================================================================
# A piece
# ===========================================================================
def build_piece(rack, x0, x1, unit):
    """The panel between x0 and x1, with the collar if unit."""
    r = RACKS[rack]
    W = r["width"] / 2.0
    oh = r["opening"] / 2.0 - RIB_CLEAR          # nothing behind the face past this
    h2 = PANEL_H / 2.0
    seam_lo = x0 > -W + 1e-6                     # is the low-x edge a seam?
    seam_hi = x1 < W - 1e-6

    # The envelope: face + everything behind it, front edges chamfered first, while it is
    # still a plain box and the chamfer cannot meet a feature.
    part = box(x0, x1, YR - DEPTH, YF, -h2, h2).faces(">Y").edges().chamfer(CHAMFER)

    # Hollow it from behind, leaving flanges, ribs and the seam pads standing. Every cutter
    # runs past the envelope where it ends, so no cut shares a face with what it cuts.
    cx0 = (x0 + RIB_T) if seam_lo else (-oh + RIB_T)
    cx1 = (x1 - RIB_T) if seam_hi else (oh - RIB_T)
    cavity = box(cx0, cx1, YR - DEPTH - 1.0, YR, -h2 + FLANGE_T, h2 - FLANGE_T)
    for xs, sx, is_seam in ((x0, +1, seam_lo), (x1, -1, seam_hi)):
        if not is_seam:
            continue
        xa, xb = sorted((xs + sx * RIB_T, xs + sx * (RIB_T + PAD_T)))
        for sz in (-1, 1):
            za, zb = sorted((sz * PAD_Z0, sz * (h2 + 1.0)))
            cavity = cavity.cut(box(xa, xb, YR - DEPTH - 2.0, YR + 1.0, za, zb))
    part = part.cut(cavity)
    # The ears: nothing behind the face beyond the opening, so they sit flat on the rails.
    for sx in (-1, 1):
        lo, hi = sorted((sx * oh, sx * (W + 1.0)))
        if hi > x0 and lo < x1:
            part = part.cut(box(lo, hi, YR - DEPTH - 1.0, YR, -h2 - 1.0, h2 + 1.0))
            for z in HOLE_Z:
                xh = sx * r["holes"] / 2.0
                if x0 < xh < x1:
                    part = part.cut(ystadium(EAR_SLOT[0], EAR_SLOT[1], xh, z,
                                             YR - 1.0, YF + 1.0))

    # The seam bolts: through rib and pad, the nut captive in the high-x piece's pad.
    for xs, sx, is_seam in ((x0, +1, seam_lo), (x1, -1, seam_hi)):
        if not is_seam:
            continue
        reach = RIB_T + PAD_T
        for z in (-SEAM_BOLT_Z, SEAM_BOLT_Z):
            part = part.cut(xteardrop(BOLT_D, BOLT_Y, z, xs - reach - 1.0, xs + reach + 1.0))
            if sx > 0:                       # this piece is on the high-x side: the nut
                xp = xs + reach
                part = part.cut(xhex(NUT_AF, BOLT_Y, z, xp - NUT_DEPTH, xp + 1.0))

    if unit:
        part = part.union(collar()).cut(aperture()).cut(cheek_holes())
    return part


def lettering_for(rack, unit, mark):
    s = None
    if unit:
        s = on_face(case.text_page(case.NAME, LABEL_CAP, case.FONT_BOLD, 0.0, LABEL_BASE,
                                   10.0), 0.0)
    if mark:
        m, _ = case.mark_page(MARK_W, -MARK_X[rack], 0.0, 10.0)
        bb = m.val().BoundingBox()
        m = on_face(m.translate((0, -(bb.ymin + bb.ymax) / 2.0, 0)), 0.0)   # on z 0
        s = m if s is None else s.union(m)
    return s


def engrave(name, part, letters, errs):
    """Cut the lettering and prove it landed wholly in material, as the case does."""
    if letters is None:
        return part
    cut = letters.intersect(face_slab(1.0))
    exact = letters.intersect(face_slab(0.0))
    v_cut = exact.val().Volume()
    v_in = part.intersect(cut).val().Volume()
    if v_cut < 1.0:
        errs.append(f"{name}: lettering is empty")
    elif abs(v_in - v_cut) > 0.03 * v_cut:
        errs.append(f"{name}: only {v_in:.1f} of {v_cut:.1f} mm3 of lettering is in "
                    f"material -- it runs into a hole, a seam or off the face")
    after = part.cut(cut)
    if not after.val().isValid() or len(after.val().Solids()) != 1:
        errs.append(f"{name}: not one valid solid after lettering")
    return after


# ===========================================================================
# Layouts
# ===========================================================================
def pieces():
    """[(name, rack, x0, x1, unit, mark)] for every piece written."""
    W = RACKS["19"]["width"] / 2.0
    c = W_CENTRE / 2.0
    W10 = RACKS["10"]["width"] / 2.0
    return [
        # your left as you face the rack is +x
        ("canary_rack19_left", "19", c, W, False, True),
        ("canary_rack19_centre", "19", -c, c, True, False),
        ("canary_rack19_right", "19", -W, -c, False, False),
        ("canary_rack10", "10", -W10, W10, True, True),
    ]


# ===========================================================================
# Verification
# ===========================================================================
def unit_physical():
    """The tube with both end plates on, as it goes into the collar."""
    y = case.TUBE_L / 2.0 + case.END_T / 2.0
    tube = case.build_tube().mirror("YZ")
    front = case.build_end("front").mirror("YZ").translate((0, +y, 0))
    rear = case.build_end("rear").mirror("YZ").translate((0, -y, 0))
    return tube, front, rear


def vol(a, b):
    try:
        return a.intersect(b).val().Volume()
    except Exception:
        return 0.0


def verify_unit(name, part, unit, errs):
    tube, front, rear = unit
    whole = tube.union(front).union(rear)
    # 1. The unit in the collar: no interference, still none 0.3 mm off in any direction
    #    across the section, and its front plate against the lip and cheeks.
    v = vol(part, whole)
    if v > 0.01:
        errs.append(f"{name}: the unit runs into the panel ({v:.2f} mm3)")
    d, k = 0.3, 0.3 / math.sqrt(2.0)
    for dx, dz in ((d, 0), (-d, 0), (0, d), (0, -d), (k, k), (k, -k), (-k, k), (-k, -k)):
        v = vol(part, whole.translate((dx, 0, dz)))
        if v > 0.01:
            errs.append(f"{name}: under 0.3 mm of collar clearance toward "
                        f"({dx:+.2f}, {dz:+.2f}) ({v:.2f} mm3)")
    v = vol(part, whole.translate((0, 0.3, 0)))
    if v < 50.0:
        errs.append(f"{name}: the front plate is not against the lip and cheeks "
                    f"(0.3 mm further forward overlaps only {v:.1f} mm3)")
    # 2. Each M3 x 12, through cheek, front plate and into the tube's insert pilot: a
    #    3.0 mm rod down its axis meets no material, so the holes line up.
    for (x, z) in screws_physical():
        rod = case.ybore(3.0, x, z, YF - SCREW_RACK, YF + 2.0)
        for what, s in (("panel", part), ("front plate", front), ("tube", tube)):
            v = vol(s, rod)
            if v > 0.01:
                errs.append(f"{name}: the screw at ({x:+.1f}, {z:+.1f}) hits the {what} "
                            f"({v:.2f} mm3)")
        # and its head lands wholly on the cheek
        head = case.ybore(HEAD_D, x, z, YF - 0.5, YF).cut(
            case.ybore(case.SCREW_CLEAR_D + 0.2, x, z, YF - 1.0, YF + 1.0))
        v_h = head.val().Volume()
        v_in = vol(part, head)
        if v_in < v_h - 0.05:
            errs.append(f"{name}: the screw head at ({x:+.1f}, {z:+.1f}) overhangs the "
                        f"cheek ({v_in:.2f} of {v_h:.2f} mm3 on material)")
    engage = SCREW_RACK - T_FACE - case.END_T
    if engage > case.INSERT_DEPTH - 1.0 or engage < case.INSERT_LEN:
        errs.append(f"{name}: M3 x {SCREW_RACK:.0f} engages {engage:.1f} mm in the tube")
    # 3. The lid stays clear: no collar over any lid opening or the lid's lettering. Up to
    #    the collar's top only: the panel's top flange is 18 mm above the lid and its
    #    rear edge is over the lettering's front end, which hides nothing.
    cuts, _ = case.lettering_cuts()
    bb = cuts["canary_tube"][0].val().BoundingBox()
    lid = [(o, "a lid opening") for o in case.lid_openings()]
    lid.append(((bb.xmin, bb.xmax, bb.ymin, bb.ymax), "the lid's lettering"))
    z_top = case.OUTER_B + FIT + WALL_C + 1.0
    for (bx0, bx1, by0, by1), what in lid:
        prism = box(-bx1, -bx0, by0, by1, 0.0, z_top)           # board x -> physical
        v = vol(part, prism)
        if v > 0.01:
            errs.append(f"{name}: the collar covers {what} at y {by0:+.1f}..{by1:+.1f} "
                        f"({v:.1f} mm3)")
    # 4. The front stays clear: nothing in front of an etherCON flange (1 mm round it) or
    #    the front plate's labels.
    fr = []
    for x in case.ETHERCON_X:
        cx = -case.bx(x)
        w = case.NE8FBH_PLATE_W / 2.0 + 1.0
        fr.append(((cx - w, cx + w, case.Z_AXIS - case.NE8FBH_PLATE_BELOW - 1.0,
                    case.Z_AXIS + case.NE8FBH_PLATE_ABOVE + 1.0), "an etherCON flange"))
    bb = cuts["canary_end_front"][0].val().BoundingBox()
    fr.append(((-bb.xmax, -bb.xmin, bb.zmin, bb.zmax), "the front plate's labels"))
    for (fx0, fx1, fz0, fz1), what in fr:
        v = vol(part, box(fx0, fx1, YR - 1.0, YF + 5.0, fz0, fz1))
        if v > 0.01:
            errs.append(f"{name}: the face covers {what} at x {fx0:+.1f}..{fx1:+.1f} "
                        f"({v:.1f} mm3)")


def verify_piece(name, rack, x0, x1, part, errs):
    r = RACKS[rack]
    bb = part.val().BoundingBox()
    if abs(bb.zlen - PANEL_H) > 0.01 or abs(bb.xlen - (x1 - x0)) > 0.01:
        errs.append(f"{name}: {bb.xlen:.2f} x {bb.zlen:.2f}, expected "
                    f"{x1 - x0:.2f} x {PANEL_H:.2f}")
    # nothing behind the face outside the clear opening
    oh = r["opening"] / 2.0
    for sx in (-1, 1):
        lo, hi = sorted((sx * oh, sx * 400.0))
        v = vol(part, box(lo, hi, YR - D_TROUGH - 5.0, YR - 0.01, -60, 60))
        if v > 0.01:
            errs.append(f"{name}: {v:.1f} mm3 behind the ear, where the rail is")
    if not part.val().isValid() or len(part.val().Solids()) != 1:
        errs.append(f"{name}: not one valid solid")


def verify_layout(built, errs):
    # the 19-inch pieces meet and do not overlap, and together are the full panel
    p19 = [(n, p) for (n, rk, *_), p in built if rk == "19"]
    for i in range(len(p19)):
        for j in range(i + 1, len(p19)):
            v = vol(p19[i][1], p19[j][1])
            if v > 0.01:
                errs.append(f"{p19[i][0]} and {p19[j][0]} overlap by {v:.2f} mm3")
    xs = sorted(p.val().BoundingBox().xmin for _, p in p19)
    xe = sorted(p.val().BoundingBox().xmax for _, p in p19)
    if abs(xe[-1] - xs[0] - RACKS["19"]["width"]) > 0.01:
        errs.append(f"19-inch panel is {xe[-1] - xs[0]:.2f} wide")
    # the collar stands clear of the seam ribs and pads
    reach = case.OUTER_A + FIT + WALL_C
    if reach > W_CENTRE / 2.0 - RIB_T - 1.0:
        errs.append(f"the collar reaches x {reach:.1f}: into the seam ribs")


def print_pose(part):
    """Face down: the front face (+y) onto the plate (z 0)."""
    return part.rotate((0, 0, 0), (1, 0, 0), -90).translate((0, 0, YF))


def main():
    print(f"CANary rack panel -- 2U ({PANEL_H:.1f} mm), one tube "
          f"{2 * case.OUTER_A:.0f} x {2 * case.OUTER_B:.0f} x {case.OUTER_L:.1f} mm, "
          f"held by M3 x {SCREW_RACK:.0f}")
    errs = []
    unit = unit_physical()
    built = []
    for spec in pieces():
        name, rack, x0, x1, has_unit, mark = spec
        part = build_piece(rack, x0, x1, has_unit)
        verify_piece(name, rack, x0, x1, part, errs)
        if has_unit:
            verify_unit(name, part, unit, errs)
        part = engrave(name, part, lettering_for(rack, has_unit, mark), errs)
        built.append((spec, part))
        print(f"  {name:24s} x {x0:+7.2f} .. {x1:+7.2f}" + ("  unit checked" if has_unit
                                                            else ""))
    verify_layout(built, errs)
    for e in errs:
        print(f"  ! {e}")
    if errs:
        print("\nRACK VERIFICATION FAILED -- nothing written")
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    for (name, *_), part in built:
        solid = print_pose(part)
        cq.exporters.export(solid, str(OUT / f"{name}.step"))
        cq.exporters.export(solid, str(OUT / f"{name}.stl"),
                            tolerance=0.01, angularTolerance=0.1)
        leak = case.mesh_leaks(OUT / f"{name}.stl")
        if leak:
            print(f"  ! {name}.stl {leak}")
            return 1
        bb = solid.val().BoundingBox()
        print(f"  {name:24s} {bb.xlen:6.1f} x {bb.ylen:5.1f} x {bb.zlen:4.1f} mm (as printed)"
              f"  {solid.val().Volume() / 1000.0:6.1f} cm3")

    # The assembled 19-inch panel with its tube, in rack orientation, for reference.
    tube, front, rear = unit
    asm = cq.Assembly(name="canary_rack19")
    for (name, rack, *_), part in built:
        if rack == "19":
            asm.add(part, name=name, color=cq.Color(0.15, 0.15, 0.16))
    for n, s in (("tube", tube), ("end_front", front), ("end_rear", rear)):
        asm.add(s, name=n, color=cq.Color(0.93, 0.45, 0.12))
    asm.export(str(OUT / "canary_rack19_assembly.step"))
    print(f"  wrote {len(built)} pieces + canary_rack19_assembly.step -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
