#!/usr/bin/env python3
"""Rotate the four case parts from MODEL orientation into PRINT orientation.

Model orientation is the assembled one: Z 0 is the parting line, Y 0 the case mid,
X 0 the etherCON cluster centre. None of the four parts sits on a flat face there.

    shell_top      already dome-up; parting plane is its z=0 face      -> as-is
    shell_bottom   dome-DOWN, curved outer face on the plate           -> flip 180 about X
    end_front      a plate standing in XZ, 2.3 mm thick in Y           -> lay flat, outer face up
    end_rear       same, but its USB-C well stands off the INNER face  -> lay flat, outer face DOWN
                   -- the well goes up, its floor bridges the cavity,
                   and the lead-in chamfer is a 45 deg overhang at
                   the plate. The other way up the well hangs in air.

Each part is then dropped so its lowest point sits on z = 0.

    --flat   the flat-section case (gen_case_3dp.py --flat): both shells print OUTER
             face down, so it is the TOP shell that flips and the bottom that stays.
             Reads hardware/enclosure/3dp-flat, writes hardware/enclosure/bambu/print-flat.
    --tube   the one-piece body (gen_case_3dp.py --tube): the tube stands on its REAR
             end face, front end up, so the guide-tube fins hang toward the plate. The
             two end plates lie flat as before. Reads 3dp-tube, writes print-tube.
"""
import pathlib
import sys

import numpy as np
import trimesh

FLAT = "--flat" in sys.argv
TUBE = "--tube" in sys.argv
_args = [a for a in sys.argv[1:] if not a.startswith("--")]
_suffix = ("-flat" if FLAT else "") + ("-tube" if TUBE else "")
SRC = pathlib.Path(_args[0] if len(_args) > 0 else "hardware/enclosure/3dp" + _suffix)
DST = pathlib.Path(_args[1] if len(_args) > 1 else "hardware/enclosure/bambu/print" + _suffix)

# part -> (axis, degrees). +90 about X sends model +Y to print +Z: the front piece's
# OUTER face (+Y) points at the sky, and the rear piece's INNER face (+Y, the one its
# USB-C well stands on) does too, so the well prints standing up on the plate.
ROT = {
    "dbcanary_shell_top": None,
    "dbcanary_shell_bottom": ("x", 180.0),
    "dbcanary_end_front": ("x", 90.0),
    "dbcanary_end_rear": ("x", 90.0),
    "dbcanary_led_insert": ("x", 180.0),     # tile face on the plate, pillars up
    "dbcanary_switch_cover": ("x", 180.0),   # flat top on the plate, pegs up
}
if FLAT:
    # Flat section: the bottom shell is already floor-down; the top shell goes
    # top-face-down, hold-down rails and guide tubes pointing at the sky.
    ROT["dbcanary_shell_top"] = ("x", 180.0)
    ROT["dbcanary_shell_bottom"] = None
if TUBE:
    # One piece: no shells. +90 about X sends model +Y (front) to print +Z, so the
    # tube stands on its rear end and the teardrop fins point at the plate.
    for k in ("dbcanary_shell_top", "dbcanary_shell_bottom"):
        del ROT[k]
    ROT = {"dbcanary_tube": ("x", 90.0), **ROT}
AXES = {"x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}


def main():
    DST.mkdir(parents=True, exist_ok=True)
    print(f"{'part':28s} {'footprint mm':>18s} {'height':>7s} {'plate contact':>14s}")
    total = 0.0
    for name, rot in ROT.items():
        m = trimesh.load_mesh(SRC / f"{name}.stl")
        if rot is not None:
            axis, deg = rot
            m.apply_transform(trimesh.transformations.rotation_matrix(
                np.radians(deg), AXES[axis]))
        # drop onto the plate and centre in XY
        b = m.bounds
        m.apply_translation([-(b[0][0] + b[1][0]) / 2.0,
                             -(b[0][1] + b[1][1]) / 2.0,
                             -b[0][2]])
        e = m.extents
        # how much of the part actually touches z=0 (first-layer area)
        z0 = m.vertices[:, 2].min()
        touching = m.vertices[np.isclose(m.vertices[:, 2], z0, atol=1e-6)]
        span = (f"{np.ptp(touching[:, 0]):.0f} x {np.ptp(touching[:, 1]):.0f} mm"
                if len(touching) else "point/line")
        total += m.volume / 1000.0
        m.export(DST / f"{name}.stl")
        print(f"{name:28s} {e[0]:8.1f} x {e[1]:6.1f} {e[2]:7.1f} {span:>14s}")
        if not m.is_watertight:
            print(f"  ! {name} lost watertightness in the transform")
    print(f"\n  {len(ROT)} parts -> {DST}   total {total:.1f} cm3")


if __name__ == "__main__":
    main()
