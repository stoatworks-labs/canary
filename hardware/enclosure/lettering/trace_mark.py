#!/usr/bin/env python3
"""Trace the Stoatworks Labs mark into polygons the case generator can engrave.

The mark only exists as a raster (the website's 778 x 602 brand master), so this turns its
INK -- the navy bow-tie and the stoat's black outline -- into closed polygons and writes
them to stoatworks-mark.geojson beside this file. gen_case_3dp.py reads that file; it never
touches the master, so the case builds without the website checkout.

The ink is thickened by one pixel each side before tracing. Engraved at MARK_W (48 mm) the
stoat's outline is 0.55 mm as drawn, under a 0.4 mm nozzle's two-line minimum; one pixel
brings it to ~0.7 mm without closing the eye or the ear.

Needs Pillow + numpy (the CAD venv has both) and potrace on PATH.

Run:  <venv>/bin/python hardware/enclosure/lettering/trace_mark.py [master.png]
"""
import json
import pathlib
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageFilter

HERE = pathlib.Path(__file__).resolve().parent
MASTER = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else
                      pathlib.Path.home()
                      / "Projects/infrastructure/stoatworks-website/brand/mark-navy.png")
OUT = HERE / "stoatworks-mark.geojson"


def main():
    im = Image.open(MASTER).convert("RGBA")
    a = np.asarray(im).astype(float)
    alpha = a[..., 3] / 255.0
    luma = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    luma = luma * alpha + 255.0 * (1.0 - alpha)             # over white
    paper = Image.fromarray(np.where(luma < 128, 0, 255).astype("uint8"))
    paper = paper.filter(ImageFilter.MinFilter(3))          # grow the ink 1 px
    with tempfile.TemporaryDirectory() as tmp:
        bmp = pathlib.Path(tmp) / "mark.bmp"
        paper.convert("1").save(bmp)
        # -t 20 drops anti-aliasing specks; -O 0.4 lets potrace merge curve segments
        subprocess.run(["potrace", "-b", "geojson", "-t", "20", "-O", "0.4",
                        "-o", str(OUT), str(bmp)], check=True)
    doc = json.loads(OUT.read_text())
    doc["source"] = {"master": MASTER.name, "size": list(im.size),
                     "note": "pixel coordinates, y UP from the bottom edge (potrace's frame); ink traced, grown 1 px"}
    OUT.write_text(json.dumps(doc))
    rings = sum(len(f["geometry"]["coordinates"]) for f in doc["features"])
    print(f"{OUT.name}: {len(doc['features'])} polygons, {rings} rings from {MASTER}")


if __name__ == "__main__":
    main()
