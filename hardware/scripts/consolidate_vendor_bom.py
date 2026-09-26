#!/usr/bin/env python3
"""
Consolidate a vendor Fabrication Toolkit BOM onto one line per orderable part.

WHY
---
Both vendors' plugins group BOM lines by the schematic Value string rather than
by part number. Ours carry net annotations - "100nF (BST)", "100nF (VBG)" and
plain "100nF" are all CL05B104KO5NNNC - so what should be one 14-piece line
arrives at the quoting desk as three lines of 1, 12 and 1.

That is not free. On the rev A PCBWay quote the two-piece
CL21A226MAQNNNE line was priced as two separate 1-piece lines at USD 1.727
each: USD 17.27 for ten 22uF capacitors LCSC sells at USD 0.33.

The fix belongs here and not in the schematic. Those annotations are the only
record of which pin each part serves - (BST) is the AP63200 bootstrap,
(VBG)/(TOCAP)/(TCT)/(RCT) are W5500 pin names, LAN/CAN/ERR/ON are the LED
functions - and deleting real documentation to satisfy a CSV grouping quirk is
the wrong trade.

fab_package.py already applies this rule when it builds the generic BOM (see
build_generic_bom: "One purchase line per orderable part"). This applies the
same rule to the plugin-generated vendor BOMs, which fab_package deliberately
never overwrites. Its helpers are imported rather than reimplemented.

Parts the plugins cannot source - the through-hole ones, which carry no LCSC
field on the board - are refilled from fab/hand-fit-parts.json, keyed by
designator. Without that they arrive at the quoting desk blank, which is how
PCBWay came back asking for J301 and SW201 by hand.

Usage:
    consolidate_vendor_bom.py <bom.csv> [<bom.csv> ...] [--dnp REF,REF]
                              [-o OUT] [--dry-run]

    # this order: consolidate, and drop the etherCONs we hand-fit ourselves
    consolidate_vendor_bom.py fab/pcbway/dbcanary-pcbway-bom.csv \
        --dnp J201,J202,J401
"""
import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fab_package import collapse_refs, expand_refs, ref_key  # noqa: E402

HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAND_FIT = os.path.join(HW, "fab", "hand-fit-parts.json")

# Column spellings the two plugins disagree about.
REF_COLS = ("Designator", "Reference Designators", "Designators", "Refs", "Reference")
QTY_COLS = ("Quantity", "Qty")
VAL_COLS = ("Value", "Comment")
MPN_COLS = ("MPN", "Manufacturer Part Number", "Mfg Part #")
LCSC_COLS = ("LCSC", "LCSC Part #", "Supplier Part Number")
FP_COLS = ("Footprint", "Package")
MFR_COLS = ("Manufacturer", "Manufacturer Name")
DNP_COLS = ("DNP",)


def col(fieldnames, *names):
    """The actual header key matching any of `names`, or None."""
    for n in names:
        for f in fieldnames:
            if f and f.strip().lower() == n.lower():
                return f
    return None


def get(row, key):
    return (row.get(key) or "").strip() if key else ""


def load_assignments():
    """designator -> {mpn, brand, lcsc} for parts the plugins cannot source."""
    if not os.path.isfile(HAND_FIT):
        return {}
    return {ref: rec for ref, rec in json.load(open(HAND_FIT, encoding="utf-8")).items()
            if not ref.startswith("_")}


def consolidate(path, dnp_refs, assignments, fill=True):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    if not fieldnames:
        sys.exit(f"{path}: no header")

    c_ref = col(fieldnames, *REF_COLS)
    c_qty = col(fieldnames, *QTY_COLS)
    c_val = col(fieldnames, *VAL_COLS)
    c_mpn = col(fieldnames, *MPN_COLS)
    c_lcsc = col(fieldnames, *LCSC_COLS)
    c_fp = col(fieldnames, *FP_COLS)
    c_mfr = col(fieldnames, *MFR_COLS)
    c_dnp = col(fieldnames, *DNP_COLS)
    if not c_ref:
        sys.exit(f"{path}: no designator column in {fieldnames}")

    # Fill the hand-fit lines before grouping, so a part that the plugin left
    # blank can still merge with itself across rows.
    filled = []
    for row in rows:
        refs = expand_refs(get(row, c_ref))
        a = assignments.get(refs[0]) if fill and len(refs) == 1 else None
        if a:
            if c_mpn and not get(row, c_mpn):
                row[c_mpn] = a.get("mpn", "")
            if c_lcsc and not get(row, c_lcsc):
                row[c_lcsc] = a.get("lcsc", "")
            if c_mfr and not get(row, c_mfr):
                row[c_mfr] = a.get("brand", "")
            filled.append(refs[0])

    groups = {}
    order = []
    for i, row in enumerate(rows):
        ident = get(row, c_mpn) or get(row, c_lcsc)
        # No part number means nothing to merge on. Keep the row as its own
        # line rather than guessing from the value string - guessing from the
        # value string is the bug this script exists to undo.
        key = (ident, get(row, c_fp)) if ident else ("", i)
        if key not in groups:
            groups[key] = {"row": dict(row), "refs": [], "values": []}
            order.append(key)
        g = groups[key]
        g["refs"] += expand_refs(get(row, c_ref))
        v = get(row, c_val)
        if v and v not in g["values"]:
            g["values"].append(v)

    out_rows, marked = [], []
    for key in order:
        g = groups[key]
        row = g["row"]
        refs = sorted(set(g["refs"]), key=ref_key)
        row[c_ref] = collapse_refs(refs)
        if c_qty:
            row[c_qty] = str(len(refs))
        if c_val:
            # " / " is the join fab_package already uses in the generic BOM.
            row[c_val] = " / ".join(g["values"])
        if dnp_refs and set(refs) & dnp_refs:
            if not set(refs) <= dnp_refs:
                sys.exit(f"{path}: {row[c_ref]} is only partly marked DNP")
            if c_dnp:
                row[c_dnp] = "DNP"
                marked += refs
        out_rows.append(row)

    stats = {
        "lines_before": len(rows),
        "lines_after": len(out_rows),
        "designators": sum(len(expand_refs(get(r, c_ref))) for r in rows),
        "designators_after": sum(len(expand_refs(get(r, c_ref))) for r in out_rows),
        "filled": filled,
        "dnp": sorted(set(marked)),
        # Saying "DNP applied" when the format has no such column would be a lie
        # that costs money - those parts get built.
        "dnp_unsupported": bool(dnp_refs) and not c_dnp,
    }
    return fieldnames, out_rows, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bom", nargs="+")
    ap.add_argument("--dnp", default="", help="comma-separated designators to mark Do Not Place")
    ap.add_argument("--no-fill", action="store_true",
                    help="consolidate only; leave the hand-fit lines unsourced. Use for "
                         "JLCPCB, whose Economic tier is top-side SMD and which is meant "
                         "to see those five parts as Do Not Place, not as orderable lines.")
    ap.add_argument("-o", "--output", help="write here instead of in place (single input only)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.output and len(args.bom) > 1:
        sys.exit("-o takes a single input")

    dnp_refs = {r.strip() for r in args.dnp.split(",") if r.strip()}
    assignments = load_assignments()
    rc = 0

    for path in args.bom:
        fieldnames, rows, st = consolidate(path, dnp_refs, assignments, fill=not args.no_fill)

        if st["designators"] != st["designators_after"]:
            print(f"  {os.path.basename(path)}: REFUSED - designator count changed "
                  f"{st['designators']} -> {st['designators_after']}")
            rc = 1
            continue

        dest = args.output or path
        if not args.dry_run:
            with open(dest, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.DictWriter(fh, fieldnames=fieldnames)
                w.writeheader()
                w.writerows(rows)

        print(f"  {os.path.basename(path)}: {st['lines_before']} -> {st['lines_after']} lines, "
              f"{st['designators']} designators intact"
              + (f", filled {', '.join(st['filled'])}" if st["filled"] else "")
              + (f", DNP {', '.join(st['dnp'])}" if st["dnp"] else "")
              + ("  (dry run)" if args.dry_run else ""))
        if st["dnp_unsupported"]:
            print(f"      NOTE: this format has no DNP column - {args.dnp} NOT marked. "
                  f"Exclude them in the order form instead.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
