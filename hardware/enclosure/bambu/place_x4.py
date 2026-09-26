#!/usr/bin/env python3
"""Pre-position the twelve parts of a `tube-x4` plate, so the CLI needs no arranging.

Studio's arranger, given four bodies and eight end plates with a 3 mm brim, turns some of
them, wastes the bed and spills the twelfth onto a second plate; and a 3mf whose build
items have been re-positioned by hand after the export, Studio refuses to slice at all.
So the layout is done BEFORE the export, in the STLs themselves: each part is turned 90
degrees (long side along Y) and translated onto a 6 x 2 grid of the H2C's 330 x 320 bed --
six columns of 45 + 2 x 3 brim + 3 gap, two rows of 137 + 6 + 10 -- and the CLI is run
with --arrange 0, which keeps mesh coordinates as bed coordinates. Tubes at the back
of the bed, plates in front. Writes work/x4-stls/NN/<part>.stl, one directory per copy
so that the object names (which the CLI takes from the file name) stay the part names.
"""
import pathlib
import shutil
import sys

import numpy as np
import trimesh

SRC = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "print-tube")
OUT = pathlib.Path("work/x4-stls")
BED = (330.0, 320.0)
BRIM, GAP_X, GAP_Y = 3.0, 3.0, 10.0
W, L = 45.0, 137.0                      # footprint after the turn: W along X, L along Y
PARTS = ["dbcanary_tube"] * 4 + ["dbcanary_end_front"] * 4 + ["dbcanary_end_rear"] * 4


def main():
    pitch_x = W + 2 * BRIM + GAP_X
    x0 = (BED[0] - (6 * (W + 2 * BRIM) + 5 * GAP_X)) / 2.0 + BRIM + W / 2.0
    pitch_y = L + 2 * BRIM + GAP_Y
    y0 = (BED[1] - (2 * (L + 2 * BRIM) + GAP_Y)) / 2.0 + BRIM + L / 2.0
    slots = [(x0 + c * pitch_x, y0 + pitch_y) for c in range(6)] + \
            [(x0 + c * pitch_x, y0) for c in range(6)]
    shutil.rmtree(OUT, ignore_errors=True)
    for i, (name, (cx, cy)) in enumerate(zip(PARTS, slots)):
        m = trimesh.load_mesh(SRC / f"{name}.stl")
        m.apply_transform(trimesh.transformations.rotation_matrix(np.radians(90), [0, 0, 1]))
        b = m.bounds
        m.apply_translation([cx - (b[0][0] + b[1][0]) / 2.0,
                             cy - (b[0][1] + b[1][1]) / 2.0, -b[0][2]])
        e = m.bounds
        assert e[0][0] >= BRIM and e[1][0] <= BED[0] - BRIM and e[0][1] >= BRIM \
            and e[1][1] <= BED[1] - BRIM, f"{name} #{i + 1} leaves the bed: {e}"
        d = OUT / f"{i + 1:02d}"
        d.mkdir(parents=True)
        m.export(d / f"{name}.stl")
        print(f"  {i + 1:2d} {name:20s} x {e[0][0]:6.1f}..{e[1][0]:6.1f}  "
              f"y {e[0][1]:6.1f}..{e[1][1]:6.1f}")
    print(f"  12 parts -> {OUT}  (6 x 2 grid, {BRIM:.0f} mm brim allowed for)")


if __name__ == "__main__":
    main()
