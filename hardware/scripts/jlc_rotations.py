#!/usr/bin/env python3
"""
Apply JLCPCB pick-and-place rotation corrections to the CPL.

WHY THIS EXISTS
---------------
KiCad's footprint orientation and JLCPCB's pick-and-place convention disagree
for a number of package families. Getting one wrong places the part rotated,
which for an IC means a dead board. The fab package previously exported KiCad's
rotations verbatim and left a note in REVIEW.txt saying "check these at
JLCPCB's review step" - honest, but it pushed a solvable problem onto a human.

WHERE THE DATA COMES FROM
-------------------------
The corrections database shipped with the kicad-jlcpcb-tools plugin
(com_github_bouni_kicad-jlcpcb-tools), which is maintained against real JLCPCB
orders. That is a far better source than a generic "typical offsets" table -
and the two disagree: generic tables say SOT-23 is +180, this database says
-90.

This script deliberately REPLICATES the plugin's own algorithm rather than
inventing one, so results match what the plugin would produce:

  1. try to match, in order: the footprint's REFERENCE, then its VALUE, then
     its library item name;
  2. for each of those, try every correction regex ANCHORED ('(?:re)$') before
     falling back to unanchored, so 'SOT-23-3' beats 'SOT-23';
  3. corrected = (kicad_rotation + correction) % 360;
  4. footprints on the bottom layer are mirrored first: (180 - rot) % 360.

Run with KiCad's bundled Python so pcbnew is importable.
"""
import os as _os
_REPO = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import csv
import os
import re
import sqlite3
import sys

import pcbnew

HW = _REPO + "/hardware"
BOARD = f"{HW}/dbcanary.kicad_pcb"
CPL = f"{HW}/fab/jlcpcb/dbcanary-jlcpcb-cpl.csv"
PLUGIN = os.path.expanduser(
    "~/Documents/KiCad/10.0/3rdparty/plugins/com_github_bouni_kicad-jlcpcb-tools")
CORRECTIONS_DB = f"{PLUGIN}/jlcpcb/corrections.db"


def load_corrections():
    if not os.path.exists(CORRECTIONS_DB):
        raise SystemExit(f"corrections database not found: {CORRECTIONS_DB}\n"
                         "Install the kicad-jlcpcb-tools plugin via KiCad's "
                         "Plugin and Content Manager.")
    con = sqlite3.connect(f"file:{CORRECTIONS_DB}?mode=ro", uri=True)
    rows = [(r[0], r[1], (r[2], r[3])) for r in con.execute(
        "SELECT regex, rotation, offset_x, offset_y FROM correction")]
    con.close()
    return rows


def find_correction(corrections, value):
    """The plugin's _find_correction: anchored patterns win over unanchored."""
    for regex, rotation, offset in corrections:
        if re.search(f"(?:{regex})$", value):
            return regex, rotation, offset
    for regex, rotation, offset in corrections:
        if re.search(regex, value):
            return regex, rotation, offset
    return None


def main():
    corrections = load_corrections()
    board = pcbnew.LoadBoard(BOARD)

    fps = {}
    for fp in board.GetFootprints():
        fps[fp.GetReference()] = (
            fp.GetOrientationDegrees() % 360,
            fp.GetLayer() != pcbnew.F_Cu,
            str(fp.GetValue()),
            str(fp.GetFPID().GetLibItemName()),
        )

    rows = list(csv.DictReader(open(CPL)))
    changed, unchanged, missing = [], 0, []

    for row in rows:
        ref = row["Designator"]
        if ref not in fps:
            missing.append(ref)
            continue
        kicad_rot, flipped, value, fpname = fps[ref]
        rot = (180 - kicad_rot) % 360 if flipped else kicad_rot

        hit = None
        for candidate in (ref, value, fpname):
            hit = find_correction(corrections, candidate)
            if hit:
                break
        if hit is None:
            unchanged += 1
            continue

        regex, correction, offset = hit
        new = (rot + int(correction)) % 360
        old = float(row["Rotation"])
        row["Rotation"] = f"{new:.2f}"
        if offset[0] or offset[1]:
            row["Mid X"] = f"{float(row['Mid X']) + offset[0]:.4f}"
            row["Mid Y"] = f"{float(row['Mid Y']) + offset[1]:.4f}"
        if abs(new - old) > 0.01 or offset[0] or offset[1]:
            changed.append((ref, fpname, regex, correction, old, new, offset))

    with open(CPL, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["Designator", "Mid X", "Mid Y",
                                          "Layer", "Rotation"])
        w.writeheader()
        w.writerows(rows)

    print(f"corrections in database : {len(corrections)}")
    print(f"placements              : {len(rows)}")
    print(f"corrected               : {len(changed)}")
    print(f"no correction needed    : {unchanged}")
    if missing:
        print(f"NOT ON BOARD            : {missing}")
    if changed:
        print(f"\n  {'ref':<7} {'footprint':<34} {'matched':<22} "
              f"{'corr':>5} {'was':>7} {'now':>7}")
        for ref, fpname, regex, corr, old, new, off in changed:
            extra = f"  offset {off}" if (off[0] or off[1]) else ""
            print(f"  {ref:<7} {fpname[:34]:<34} {regex[:22]:<22} "
                  f"{corr:>5} {old:>7.1f} {new:>7.1f}{extra}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
