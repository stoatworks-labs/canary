#!/usr/bin/env python3
"""Build 3D-printable rack plates for the CANary one-piece tube and export STEP/STL.

The tube (`gen_case_3dp.py --tube`) is 137 x 45 mm in section and 93.5 mm long. Its front
end plate is a flat 2.5 mm slab that carries the three etherCONs and is screwed to the
body with four M3 into heat-set inserts. A rack plate takes that plate's place: the same
2.5 mm skin, with the same connector bores, panel-screw holes and body-screw holes made by
the same functions, at the floor of a pocket the tube's front end sits in. To rack a unit,
take its front plate off and screw the body and the three etherCONs to the rack plate
instead. Nothing on the tube or the board changes, and the plate it came with goes back
on when the unit goes back on a desk.

Why 2U: the tube is 45.0 mm tall and a 1U panel is 43.66 mm (44.45 less the EIA 0.8 mm
gap). So the panels are 2U, 88.1 mm, with the tube centred.

    19-inch  three slots on a 148 mm pitch. 482.6 mm does not fit a 320 mm bed, so the
             panel is three pieces, one slot each, the two end pieces carrying the ears.
             The pieces bolt together through ribs behind each seam: 2 x M3 x 12 and a
             nut per seam, the nut captive in the right-hand piece's pad. The front edges
             are chamfered, so each seam reads as a V-groove rather than a crack.
    10-inch  one slot, one piece, with the Stoatworks mark beside it.

Every piece prints FACE DOWN: the front face on the plate, everything else growing up
from it. Nothing overhangs -- the pocket opens upward, the flanges, ribs and pads are
vertical walls, the seam bolts are teardrops pointing up and the nut traps stand on a
vertex. Blanks (same pieces, no slot) close an empty position.

Behind the face each piece is a shallow tray: return flanges along the top and bottom
edge, a rib at each seam and at each side of the rack opening. Nothing behind the face
reaches past the rack's clear opening, so the ears sit flat on the rails.

What is NOT verified: none of this has been printed. The pocket fit (0.35 mm a side) and
the seam bolts are numbers, not trials. The tube is cantilevered off the panel on its
four M3 screws, which is fine for a ~250 g unit in a static rack and has not been tried
in a touring one. In a rack the lid's LEDs face the unit above, not the front.

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
# back to front (the etherCON end is +y), z up. Read from the front, your right is -x, so
# unit 1 -- the left-hand slot as you face the rack -- is at +x.

# ---- the rack (EIA-310 / the common 10-inch size) ----------------------------
U = 44.45
UNITS = 2
PANEL_H = UNITS * U - 0.8                 # 88.1: n x U less the standard 0.8 mm gap
HOLE_Z = (-(U - 6.35), +(U - 6.35))       # +/-38.1: the outer hole of each U, 3 in apart
RACKS = {
    # width over the ears, ear-hole centres, clear opening between the rails
    "19": dict(width=482.6, holes=465.1, opening=450.85,
               slots=(+148.0, 0.0, -148.0), seams=(+74.0, -74.0)),
    "10": dict(width=254.0, holes=236.5, opening=222.25,
               slots=(0.0,), seams=()),
}
EAR_SLOT = (9.5, 6.5)                     # horizontal stadium: M5/M6/10-32 with play

# ---- the panel ----------------------------------------------------------------
T_FACE = 5.0                              # face thickness outside the pockets
SKIN = case.END_T                         # = the front plate it replaces: 2.5
POCKET_FIT = 0.35                         # per side, tube outline vs pocket
YF = case.OUTER_L / 2.0                   # front face: where the plate's outer face was
YR = YF - T_FACE                          # back of the face
Y_SKIN = YF - SKIN                        # pocket floor = the tube's front end face
DEPTH = 16.0                              # flanges and ribs, back from YR
FLANGE_T = 3.0
RIB_T = 3.0
RIB_CLEAR = 0.75                          # side rib's outer face inside the clear opening
CHAMFER = 0.6                             # every front-face edge: seams become V-grooves

# ---- the seam bolts -----------------------------------------------------------
SEAM_BOLT_Z = 33.0                        # above and below the tube (its top is z 22.5)
PAD_T = 3.0                               # pad on the rib round each bolt
PAD_Z0 = 28.0                             # pad from here out to the flange
BOLT_D = 3.4                              # M3 clearance
NUT_AF = 5.5 + 0.35                       # M3 nut, 5.5 across flats, + print clearance
NUT_DEPTH = 2.6                           # nut 2.4 thick
BOLT_Y = YR - DEPTH / 2.0

# ---- lettering ----------------------------------------------------------------
LABEL_CAP = 5.0                           # "CANary 1" above each slot
LABEL_BASE = 28.5
MARK_W = 30.0                             # the mark on the 10-inch panel
MARK_X = 92.0                             # its centre, physical x (your left of the slot)


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


def on_face(solid, u0, x_origin):
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


# ===========================================================================
# The slot: what the tube's front plate carried, at the floor of a pocket
# ===========================================================================
def slot_holes(xs):
    """The front plate's through-holes, built as the plate's are, mirrored as it is."""
    y0, y1 = Y_SKIN - 1.0, YF + 1.0
    c = None
    for x in case.ETHERCON_X:
        n = case.neutrik_cut(case.bx(x), case.Z_AXIS, y0, y1, diag=case.ETHERCON_DIAG)
        c = n if c is None else c.union(n)
    for (x, z) in case.tube_screws():
        c = c.union(case.ybore(case.SCREW_CLEAR_D, x, z, y0, y1))
    return c.mirror("YZ").translate((xs, 0, 0))


def slot_pocket(xs):
    y0, y1 = YR - 1.0, Y_SKIN
    return case.section_prism(case.OUTER_A + POCKET_FIT, case.OUTER_B + POCKET_FIT,
                              y1 - y0, (y0 + y1) / 2.0).translate((xs, 0, 0))


def slot_lettering(xs, unit):
    """CAN 1 / CAN 2 / ETH where the front plate has them, and the unit's number above."""
    h = 10.0
    s = None
    for x, label in zip(case.ETHERCON_X, case.PORT_LABELS):
        t = case.text_page(label, case.PORT_CAP, case.FONT_BOLD, case.bx(x),
                           case.PORT_LABEL_Z - case.PORT_CAP / 2.0, h)
        s = t if s is None else s.union(t)
    if unit is not None:
        s = s.union(case.text_page(f"{case.NAME} {unit}".strip(), LABEL_CAP,
                                   case.FONT_BOLD, 0.0, LABEL_BASE, h))
    return on_face(s, 0.0, xs)


def mark_lettering():
    m, _ = case.mark_page(MARK_W, -MARK_X, 0.0, 10.0)
    bb = m.val().BoundingBox()
    m = m.translate((0, -(bb.ymin + bb.ymax) / 2.0, 0))       # centred on z 0
    return on_face(m, 0.0, 0.0)


# ===========================================================================
# A piece
# ===========================================================================
def build_piece(rack, x0, x1, slots, units, mark=False):
    """The panel between x0 and x1 (x0 > x1 is not allowed), with the given slots."""
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

    # The slots.
    for xs in slots:
        part = part.cut(slot_pocket(xs)).cut(slot_holes(xs))
    return part


def lettering_for(slots, units, mark):
    s = None
    for xs, u in zip(slots, units):
        t = slot_lettering(xs, u)
        s = t if s is None else s.union(t)
    if mark:
        m = mark_lettering()
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
    """[(name, rack, x0, x1, slots, units, mark)] for every piece written."""
    out = []
    r = RACKS["19"]
    W = r["width"] / 2.0
    edges = [W] + list(r["seams"]) + [-W]        # from your left (+x) to your right
    names = ("left", "centre", "right")
    for i, (hi, lo) in enumerate(zip(edges, edges[1:])):
        xs = r["slots"][i]
        out.append((f"canary_rack19_{names[i]}", "19", lo, hi, (xs,), (i + 1,), False))
        out.append((f"canary_rack19_{names[i]}_blank", "19", lo, hi, (), (), False))
    W10 = RACKS["10"]["width"] / 2.0
    out.append(("canary_rack10", "10", -W10, W10, (0.0,), ("",), True))
    out.append(("canary_rack10_blank", "10", -W10, W10, (), (), False))
    return out


# ===========================================================================
# Verification
# ===========================================================================
def tube_physical():
    return case.build_tube().mirror("YZ")


def front_plate_physical(xs):
    return case.build_end("front").mirror("YZ").translate((xs, YF - SKIN / 2.0, 0))


def vol(a, b):
    try:
        return a.intersect(b).val().Volume()
    except Exception:
        return 0.0


def verify_slot(name, part, xs, tube, errs, step=1.0):
    """The slot IS the front plate, the tube sits on the pocket floor, and nothing else."""
    # 1. Point for point across the outline, at mid-skin: material in the piece exactly
    #    where the front plate has material. Lettering is 0.6 deep and does not reach
    #    mid-skin, so the two must agree everywhere.
    plate = front_plate_physical(xs).val()
    local = part.intersect(box(xs - case.OUTER_A, xs + case.OUTER_A, Y_SKIN + 0.3,
                               YF - 0.3, -case.OUTER_B, case.OUTER_B)).val()
    y = YF - SKIN / 2.0
    a, b = case.OUTER_A - 0.6, case.OUTER_B - 0.6
    n = bad = 0
    z = -b
    while z <= b:
        x = -a
        while x <= a:
            if case.inside(x, z, a, b):
                p = cq.Vector(xs + x, y, z)
                n += 1
                if local.isInside(p, 1e-4) != plate.isInside(p, 1e-4):
                    bad += 1
            x += step
        z += step
    if bad:
        errs.append(f"{name}: slot at x {xs:+.0f} differs from the tube's front plate at "
                    f"{bad} of {n} points")
    # 2. The tube, posed in the slot: no interference, and its front end on the floor.
    posed = tube.translate((xs, 0, 0))
    v = vol(part, posed)
    if v > 0.5:
        errs.append(f"{name}: the tube runs into the panel ({v:.1f} mm3)")
    for dx, dz in ((0.25, 0), (-0.25, 0), (0, 0.25), (0, -0.25)):
        v = vol(part, posed.translate((dx, 0, dz)))
        if v > 0.5:
            errs.append(f"{name}: under 0.25 mm of pocket clearance toward "
                        f"({dx:+.2f}, {dz:+.2f}) ({v:.1f} mm3)")
    v = vol(part, posed.translate((0, 0.3, 0)))
    if v < 50.0:
        errs.append(f"{name}: the tube's end is not on the pocket floor "
                    f"(0.3 mm further forward overlaps only {v:.1f} mm3)")
    return n


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
        v = vol(part, box(lo, hi, YR - DEPTH - 5.0, YR - 0.01, -60, 60))
        if v > 0.01:
            errs.append(f"{name}: {v:.1f} mm3 behind the ear, where the rail is")
    if not part.val().isValid() or len(part.val().Solids()) != 1:
        errs.append(f"{name}: not one valid solid")


def verify_layout(built, errs):
    # the 19-inch pieces meet and do not overlap, and together are the full panel
    p19 = [(n, p) for (n, rk, *_), p in built if rk == "19" and not n.endswith("_blank")]
    for i in range(len(p19)):
        for j in range(i + 1, len(p19)):
            v = vol(p19[i][1], p19[j][1])
            if v > 0.01:
                errs.append(f"{p19[i][0]} and {p19[j][0]} overlap by {v:.2f} mm3")
    xs = sorted(p.val().BoundingBox().xmin for _, p in p19)
    xe = sorted(p.val().BoundingBox().xmax for _, p in p19)
    if abs(xe[-1] - xs[0] - RACKS["19"]["width"]) > 0.01:
        errs.append(f"19-inch panel is {xe[-1] - xs[0]:.2f} wide")
    # every unit's etherCON flanges (25 x 25.6) sit on one piece's face, clear of a seam
    for (n, rk, x0, x1, slots, *_), _ in built:
        for xs in slots:
            for x in case.ETHERCON_X:
                cx = xs - case.bx(x)
                if not (x0 + CHAMFER < cx - case.NE8FBH_PLATE_W / 2.0 and
                        cx + case.NE8FBH_PLATE_W / 2.0 < x1 - CHAMFER):
                    errs.append(f"{n}: an etherCON flange at x {cx:.1f} crosses an edge")
    # the outer tubes pass between the rails, with the side ribs
    oh = RACKS["19"]["opening"] / 2.0
    reach = max(abs(s) for s in RACKS["19"]["slots"]) + case.OUTER_A
    if reach > oh - RIB_CLEAR - RIB_T - 1.0:
        errs.append(f"the outer tubes reach x {reach:.1f}: too near the opening ({oh:.1f})")


def print_pose(part):
    """Face down: the front face (+y) onto the plate (z 0)."""
    return part.rotate((0, 0, 0), (1, 0, 0), -90).translate((0, 0, YF))


def main():
    print(f"CANary rack plates -- 2U ({PANEL_H:.1f} mm), tube "
          f"{2 * case.OUTER_A:.0f} x {2 * case.OUTER_B:.0f} in section")
    errs = []
    assert abs(Y_SKIN - case.TUBE_L / 2.0) < 1e-9, "pocket floor is not the tube's end"
    tube = tube_physical()
    built = []
    for spec in pieces():
        name, rack, x0, x1, slots, units, mark = spec
        part = build_piece(rack, x0, x1, slots, units, mark)
        verify_piece(name, rack, x0, x1, part, errs)
        pts = 0
        for xs in slots:
            pts += verify_slot(name, part, xs, tube, errs)
        part = engrave(name, part, lettering_for(slots, units, mark), errs)
        built.append((spec, part))
        print(f"  {name:28s} x {x0:+7.2f} .. {x1:+7.2f}"
              + (f"  slot checked at {pts} points" if pts else ""))
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
        print(f"  {name:28s} {bb.xlen:6.1f} x {bb.ylen:5.1f} x {bb.zlen:4.1f} mm (as printed)"
              f"  {solid.val().Volume() / 1000.0:6.1f} cm3")

    # The assembled 19-inch panel with its three tubes, in rack orientation, for reference.
    asm = cq.Assembly(name="canary_rack19")
    rear = case.build_end("rear").mirror("YZ").translate((0, -YF + SKIN / 2.0, 0))
    for (name, rack, x0, x1, slots, *_), part in built:
        if rack != "19" or name.endswith("_blank"):
            continue
        asm.add(part, name=name, color=cq.Color(0.15, 0.15, 0.16))
        for xs in slots:
            asm.add(tube.translate((xs, 0, 0)), name=f"tube_{xs:+.0f}",
                    color=cq.Color(0.93, 0.45, 0.12))
            asm.add(rear.translate((xs, 0, 0)), name=f"rear_{xs:+.0f}",
                    color=cq.Color(0.93, 0.45, 0.12))
    asm.export(str(OUT / "canary_rack19_assembly.step"))
    print(f"  wrote {len(built)} pieces + canary_rack19_assembly.step -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
