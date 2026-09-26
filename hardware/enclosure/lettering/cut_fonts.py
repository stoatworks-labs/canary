#!/usr/bin/env python3
"""Cut the static Montserrat weights the case lettering uses, overlaps removed.

Montserrat ships as a variable font, and a variable font's glyphs are built from
OVERLAPPING contours (the A's crossbar crosses its legs, the N's diagonal its stems).
Instanced as-is, OCC turns each such glyph into a self-intersecting face and an invalid
solid, and a boolean against it quietly removes the wrong volume -- the first lettered
case lost 11 cm3 from a front plate to 35 mm3 of text. So the instances here are merged
to one outline per glyph before they are written.

Needs fontTools + skia-pathops (pip install skia-pathops into the CAD venv).

Run:  <venv>/bin/python hardware/enclosure/lettering/cut_fonts.py [Montserrat[wght].ttf]
"""
import pathlib
import sys

from fontTools import ttLib
from fontTools.ttLib.removeOverlaps import removeOverlaps
from fontTools.varLib import instancer

HERE = pathlib.Path(__file__).resolve().parent
SRC = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else
                   pathlib.Path.home()
                   / "Library/Fonts/google-fonts/ofl/montserrat/Montserrat[wght].ttf")
WEIGHTS = {"Bold": 700, "ExtraBold": 800}


def main():
    for name, wght in WEIGHTS.items():
        font = instancer.instantiateVariableFont(ttLib.TTFont(SRC), {"wght": wght})
        removeOverlaps(font)
        out = HERE / f"Montserrat-{name}.ttf"
        font.save(out)
        print(f"{out.name}: wght {wght}, overlaps removed, from {SRC.name}")


if __name__ == "__main__":
    main()
