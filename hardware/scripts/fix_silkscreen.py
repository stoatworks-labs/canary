#!/usr/bin/env python3
"""
Clean up silkscreen reference designators.

THE PROBLEM
-----------
All 76 refdes were at KiCad's default 1.0 mm height with 0.15 mm stroke, and the
board has 0402 passives on a 3 mm pitch. The result, visible in
docs/renders/: 'D304D303D302D301' and 'R40640R408409' render as unreadable
blobs, and DRC reports 36 silkscreen violations - almost all of them refdes
overlapping the refdes of the part next door.

APPROACH - AND ONE THAT WAS TRIED AND REJECTED
---------------------------------------------
First attempt used the installed center-silk-ref plugin's approach: centre each
refdes on its footprint courtyard, shrink to fit, nudge clear of pads. That made
things WORSE - 36 violations became 206. For an 0402 the courtyard barely
exceeds the part, so "centred" means sitting on top of its own pads:
silk_over_copper went 14 -> 130. The original offset-beside-the-part placement
was correct; only the SIZE was wrong.

So this shrinks the text and leaves positions alone. Refdes were at KiCad's
default 1.0 mm height / 0.15 mm stroke, which for 4-character designators is
~2.4 mm wide - wider than the 3 mm pitch leaves room for once two sit side by
side. The plugin's _fit_text_to_courtyard is still used for the fitting maths.

THE FLOOR IS 0.8 mm, NOT SMALLER. JLCPCB state 0.8 mm height / 0.15 mm line
width as the minimum for readable silkscreen. Shrinking below that to satisfy
DRC would trade a geometry warning for text the fab cannot actually print - a
worse outcome. Where 0.8 mm still does not fit, the overlap is left and listed.

Run with KiCad's bundled Python.
"""
import os as _os
_REPO = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import sys

import pcbnew

HW = _REPO + "/hardware"
BOARD = f"{HW}/canary.kicad_pcb"
PLUGIN = os.path.expanduser(
    "~/Documents/KiCad/10.0/3rdparty/plugins/com_github_sijah_center-silk-ref")

MIN_HEIGHT_MM = 0.8      # JLCPCB minimum readable silkscreen height
STROKE_RATIO = 8         # height/8, matching the plugin's own choice
PAD_CLEARANCE_MM = 0.15


def load_helpers():
    """Import the plugin module for its geometry helpers."""
    sys.path.insert(0, PLUGIN)
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "center_silk_ref", os.path.join(PLUGIN, "center_silk_ref.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    csr = load_helpers()
    board = pcbnew.LoadBoard(BOARD)

    min_h = pcbnew.FromMM(MIN_HEIGHT_MM)
    clearance = pcbnew.FromMM(PAD_CLEARANCE_MM)
    resized = centred = nudged = 0

    for fp in board.GetFootprints():
        ref = fp.Reference()
        if not ref.IsVisible():
            continue
        silk = pcbnew.F_SilkS if fp.GetLayer() == pcbnew.F_Cu else pcbnew.B_SilkS

        # Prefer the courtyard; fall back to the footprint's own silk outline,
        # then to its overall bbox, so parts with no courtyard still get done.
        bb = fp.GetCourtyard(pcbnew.F_CrtYd).BBox()
        if not bb.GetWidth():
            bb = csr._courtyard_bbox(fp, silk)
        if bb is None or not bb.GetWidth():
            bb = fp.GetBoundingBox()

        # 1. shrink to fit, never below the fab's printable minimum
        before_h = ref.GetTextHeight()
        if csr._fit_text_to_courtyard(ref, bb, min_h):
            resized += 1
        # enforce a sane stroke for whatever height we ended at
        ref.SetTextThickness(max(pcbnew.FromMM(0.05),
                                 ref.GetTextHeight() // STROKE_RATIO))

    # ---- pass 2: nudge ONLY the refdes that still overlap -----------------
    # Wholesale repositioning was rejected above. This moves nothing unless it
    # is provably in collision, and tries offsets around the part rather than
    # centring on it.
    def silk_items(exclude):
        """(bbox, layer) for every silk feature except `exclude`."""
        out = []
        for f in board.GetFootprints():
            r = f.Reference()
            if r.IsVisible() and r is not exclude:
                out.append((r.GetBoundingBox(), r.GetLayer()))
            for it in f.GraphicalItems():
                if it.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS):
                    out.append((it.GetBoundingBox(), it.GetLayer()))
        return out

    def clashes(bb, layer, obstacles):
        for obb, olayer in obstacles:
            if olayer == layer and obb.Intersects(bb):
                return True
        return False

    STEP = pcbnew.FromMM(0.5)
    OFFSETS = [(0, -2), (0, 2), (-2, 0), (2, 0), (0, -3), (0, 3),
               (-3, 0), (3, 0), (-2, -2), (2, -2), (-2, 2), (2, 2),
               (0, -4), (0, 4), (-4, 0), (4, 0)]
    moved, stuck = 0, []
    for fp in board.GetFootprints():
        ref = fp.Reference()
        if not ref.IsVisible():
            continue
        obstacles = silk_items(ref)
        if not clashes(ref.GetBoundingBox(), ref.GetLayer(), obstacles):
            continue
        home = ref.GetPosition()
        placed = False
        for dx, dy in OFFSETS:
            ref.SetPosition(pcbnew.VECTOR2I(home.x + dx * STEP,
                                            home.y + dy * STEP))
            if not clashes(ref.GetBoundingBox(), ref.GetLayer(), obstacles):
                moved += 1
                placed = True
                break
        if not placed:
            ref.SetPosition(home)          # leave it where the designer had it
            stuck.append(fp.GetReference())

    pcbnew.SaveBoard(BOARD, board)
    print(f"refdes nudged out of collision: {moved}")
    if stuck:
        print(f"still colliding, left alone   : {sorted(stuck)}")
    print(f"refdes resized to fit      : {resized}")
    print(f"positions left untouched   : all {len(list(board.GetFootprints()))}")
    print(f"minimum height enforced    : {MIN_HEIGHT_MM} mm "
          f"(JLCPCB's readable floor)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
