#!/usr/bin/env python3
"""
Write the verified LCSC part numbers onto the board as footprint fields.

WHY
---
Until now the part numbers existed only in a CSV this repo generated. That made
them invisible to every other tool: the JLCPCB Fabrication Toolkit, PCBWay's
toolkit and InteractiveHtmlBOM all read a supplier field off the footprint and
emitted an empty "LCSC Part #" column because none was set.

Putting them on the board makes them board data. Any plugin, now or later,
picks them up without being told about our CSVs.

Field name is `LCSC`, which is the first name the Fabrication Toolkit looks for
(`supplier_names = ['LCSC', 'JLCPCB']`, then fallbacks `LCSC/JLC/MPN/Mpn/mpn`).
`MPN` and `Manufacturer` are written too, for PCBWay - it is turnkey and sources
by manufacturer part number, not by LCSC code.

CAVEAT: the schematic remains the real source of truth for the netlist, and
these fields live only on the PCB because the Konnect MCP server (the sanctioned
way to edit a .kicad_sch here) is unavailable. scripts/sync_pcb.py only ever
rewrites Value and net assignments, so it will not clobber them - but a full
"Update PCB from Schematic" in the GUI could. If that happens, re-run this.
"""
import os as _os
_REPO = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import csv
import json
import os
import sys

import pcbnew

HW = _REPO + "/hardware"
BOARD = f"{HW}/dbcanary.kicad_pcb"
BOM = f"{HW}/fab/jlcpcb/dbcanary-jlcpcb-bom.csv"
MASTER = f"{HW}/fab/parts-master.json"


def main():
    master = json.load(open(MASTER))
    by_ref = {}
    for row in csv.DictReader(open(BOM, encoding="utf-8-sig")):
        code = (row.get("LCSC Part #") or "").strip()
        if not code:
            continue
        for ref in row["Designator"].split(","):
            by_ref[ref.strip()] = code

    board = pcbnew.LoadBoard(BOARD)
    written, skipped, unknown = 0, 0, []
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        code = by_ref.get(ref)
        if code is None:
            skipped += 1                      # hand-soldered parts, by design
            continue
        rec = master.get(code, {})
        fields = {"LCSC": code}
        if rec.get("mpn"):
            fields["MPN"] = rec["mpn"]
        if rec.get("brand"):
            fields["Manufacturer"] = rec["brand"]
        for name, text in fields.items():
            fp.SetField(name, text)
            # SetField() creates the field VISIBLE and on F.Silkscreen. These
            # are sourcing metadata, not board markings - left visible they get
            # PLOTTED, so every board would carry "C25744 / 0402WGF1002TCE /
            # UNI-ROYAL(Uniroyal Elec)" beside every part. It also took the
            # silkscreen DRC count from 36 to 433. Hide them and move them off
            # the silk layer.
            f = fp.GetFieldByName(name) if hasattr(fp, "GetFieldByName") else None
            if f is None:
                for cand in fp.GetFields():
                    if cand.GetName() == name:
                        f = cand
                        break
            if f is not None:
                f.SetVisible(False)
                f.SetLayer(pcbnew.F_Fab)
        if not rec:
            unknown.append(code)
        written += 1

    pcbnew.SaveBoard(BOARD, board)
    print(f"footprints given an LCSC field : {written}")
    print(f"skipped (no part assigned)     : {skipped}  (hand-soldered)")
    if unknown:
        print(f"codes missing from parts-master: {sorted(set(unknown))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
