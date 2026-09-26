#!/usr/bin/env python3
"""
Normalise a KiCad project's fabrication outputs onto the house layout.

    fab/
      generic/     vendor-neutral: loose gerbers + zip, full BOM, CPL, IPC-D-356,
                   interactive BOM.  The source of truth; convert from here.
      jlcpcb/      gerber zip + BOM + CPL in that fab's own upload format
      pcbway/        "
      pcbtrain/      "

Only the *generic* set is generated from the board.  Vendor BOMs and CPLs are
hand-curated (different part numbers, different stock, different assembly
capability) and are never overwritten here - they are only renamed onto the
common convention and, where a vendor folder has no gerber archive of its own,
given a copy of the generic one.

Usage:
    fab_package.py <project.kicad_pcb> [--slug NAME]
"""
import argparse
import csv
import io
import os
import re
import shutil
import subprocess
import sys
import zipfile

KICAD_CLI = shutil.which("kicad-cli") or "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"

GERBER_LAYERS = (
    "F.Cu,In1.Cu,In2.Cu,B.Cu,"
    "F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts"
)

VENDORS = ("jlcpcb", "pcbway", "pcbtrain")


def run(*args):
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"FAILED: {' '.join(args)}\n{r.stdout}\n{r.stderr}")
    return r.stdout


# ---------------------------------------------------------------- designators

_REF = re.compile(r"^([A-Za-z_#]+)(\d+)$")


def expand_refs(field):
    """'C1, C3-C5, R2' -> ['C1','C3','C4','C5','R2'].

    Vendor BOMs disagree on whether they collapse runs into ranges; this
    accepts either form so the same merge code reads all of them.
    """
    out = []
    for chunk in re.split(r"[,\s]+", (field or "").strip()):
        if not chunk:
            continue
        if "-" in chunk:
            lo, _, hi = chunk.partition("-")
            m1, m2 = _REF.match(lo.strip()), _REF.match(hi.strip())
            if m1 and m2 and m1.group(1) == m2.group(1):
                out += [f"{m1.group(1)}{n}" for n in range(int(m1.group(2)), int(m2.group(2)) + 1)]
                continue
        out.append(chunk)
    return out


def ref_key(ref):
    m = _REF.match(ref)
    return (m.group(1), int(m.group(2))) if m else (ref, 0)


def collapse_refs(refs):
    """Inverse of expand_refs, for readable output."""
    refs = sorted(set(refs), key=ref_key)
    out, i = [], 0
    while i < len(refs):
        j = i
        pre, num = ref_key(refs[i])
        while (j + 1 < len(refs) and ref_key(refs[j + 1]) == (pre, num + (j + 1 - i))):
            j += 1
        if j - i >= 2:            # C1-C4
            out.append(f"{refs[i]}-{refs[j]}")
        else:                     # a run of one or two is written out in full
            out += refs[i:j + 1]
        i = j + 1
    return ",".join(out)


def read_csv(path):
    if not os.path.isfile(path):
        return []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def pick(row, *names):
    """First non-empty value among several possible column spellings."""
    for n in names:
        for k, v in row.items():
            if k and k.strip().lower() == n.lower() and (v or "").strip():
                return v.strip()
    return ""


# ------------------------------------------------------------------ generic


def export_generic(board, sch, gdir, slug):
    gerbers = os.path.join(gdir, "gerbers")
    shutil.rmtree(gerbers, ignore_errors=True)
    os.makedirs(gerbers)

    # --no-x2 keeps the X2 attributes as G04 comments.  X2-native is cleaner but
    # older CAM front-ends choke on it, and this set exists to be portable.
    run(KICAD_CLI, "pcb", "export", "gerbers", "-o", gerbers,
        "--layers", GERBER_LAYERS, "--no-x2", board)
    run(KICAD_CLI, "pcb", "export", "drill", "-o", gerbers,
        "--format", "excellon", "--drill-origin", "absolute", "--excellon-units", "mm",
        "--excellon-separate-th", "--generate-map", "--map-format", "gerberx2", board)

    zip_path = os.path.join(gdir, f"{slug}-gerbers.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(gerbers)):
            z.write(os.path.join(gerbers, f), f)

    run(KICAD_CLI, "pcb", "export", "ipcd356",
        "-o", os.path.join(gdir, f"{slug}-netlist.ipc"), board)

    raw_pos = os.path.join(gdir, ".pos.csv")
    run(KICAD_CLI, "pcb", "export", "pos", "-o", raw_pos,
        "--format", "csv", "--units", "mm", "--side", "both", board)
    normalise_cpl(raw_pos, os.path.join(gdir, f"{slug}-cpl.csv"))
    os.remove(raw_pos)

    return gerbers, zip_path


def normalise_cpl(src, dst):
    """kicad-cli's own column names -> the house CPL header."""
    rows = read_csv(src)
    with open(dst, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Designator", "Value", "Package", "X (mm)", "Y (mm)", "Rotation", "Side"])
        for r in sorted(rows, key=lambda r: ref_key(pick(r, "Ref", "Designator"))):
            w.writerow([
                pick(r, "Ref", "Designator"),
                pick(r, "Val", "Value"),
                pick(r, "Package", "Footprint"),
                f'{float(pick(r, "PosX", "X") or 0):.4f}',
                f'{float(pick(r, "PosY", "Y") or 0):.4f}',
                f'{float(pick(r, "Rot", "Rotation") or 0):.1f}',
                pick(r, "Side", "Layer").lower(),
            ])


def board_designators(board, sch, gdir, slug):
    """Every placed part, from the board - not the schematic.

    The board is what gets built, and it is the only file that knows what is
    actually on the panel.
    """
    tmp = os.path.join(gdir, ".all.csv")
    run(KICAD_CLI, "pcb", "export", "pos", "-o", tmp,
        "--format", "csv", "--units", "mm", "--side", "both", board)
    rows = read_csv(tmp)
    os.remove(tmp)
    return {pick(r, "Ref"): (pick(r, "Val"), pick(r, "Package")) for r in rows}


def build_generic_bom(board, fab, gdir, slug):
    """Merge every vendor BOM's curation onto the full placed-part list.

    A vendor BOM only covers what that vendor will fit - JLCPCB's omits the
    through-hole connectors, PCB Train's omits nothing but re-sources half the
    passives to UK stock.  The generic BOM is the union: one row per part on the
    board, carrying whichever sourcing is known, and saying so when none is.
    """
    parts = board_designators(board, None, gdir, slug)

    # designator -> {field: value}, later vendors filling gaps left by earlier
    src = {}

    def absorb(rows, ref_cols, mapping, tag):
        for r in rows:
            refs = expand_refs(pick(r, *ref_cols))
            for ref in refs:
                d = src.setdefault(ref, {})
                for field, cols in mapping.items():
                    v = pick(r, *cols)
                    if v and not d.get(field):
                        d[field] = v
                d.setdefault("_seen", []).append(tag)

    common = {
        "mpn": ("Manufacturer Part Number", "MPN"),
        "manufacturer": ("Manufacturer", "Manufacturer Name"),
        "lcsc": ("LCSC Part #", "LCSC"),
        "description": ("Description",),
        "value": ("Value",),
        "footprint": ("Footprint", "Package"),
        "mount": ("Mount_Type",),
        "dnp": ("DNP",),
        "notes": ("Notes",),
    }
    refcols = ("Designator", "Reference Designators", "Designators", "Refs", "Reference")

    # PCBWay/JLC first: those carry the LCSC numbers the design was costed on.
    for vendor in ("pcbway", "jlcpcb", "pcbtrain"):
        for name in sorted(os.listdir(os.path.join(fab, vendor))) if os.path.isdir(os.path.join(fab, vendor)) else []:
            if name.endswith(".csv") and "bom" in name.lower():
                absorb(read_csv(os.path.join(fab, vendor, name)), refcols, common, vendor)

    # A PCB Train line whose MPN differs from the primary is a UK substitution,
    # and that is worth carrying into the generic BOM as a note rather than
    # silently preferring one over the other.
    alt = {}
    ptdir = os.path.join(fab, "pcbtrain")
    if os.path.isdir(ptdir):
        for name in os.listdir(ptdir):
            if name.endswith(".csv") and "bom" in name.lower():
                for r in read_csv(os.path.join(ptdir, name)):
                    mpn = pick(r, "Manufacturer Part Number", "MPN")
                    mfr = pick(r, "Manufacturer", "Manufacturer Name")
                    note = pick(r, "Notes")
                    for ref in expand_refs(pick(r, *refcols)):
                        alt[ref] = (mfr, mpn, note)

    groups = {}
    for ref, (value, footprint) in parts.items():
        d = src.get(ref, {})
        mpn = d.get("mpn", "")
        fp = d.get("footprint", footprint)
        # One purchase line per orderable part.  Two 100nF 0402s that differ only
        # in their schematic Value string ("100nF" vs "100nF (BST)") are the same
        # thing to buy, and splitting them makes the quantities wrong.
        key = (mpn, fp) if mpn else ("", d.get("value", value), fp)
        g = groups.setdefault(key, {
            "refs": [], "values": [], "footprint": fp,
            "mpn": mpn, "manufacturer": d.get("manufacturer", ""), "lcsc": d.get("lcsc", ""),
            "description": d.get("description", ""), "mount": d.get("mount", ""),
            "dnp": d.get("dnp", ""), "notes": d.get("notes", ""), "sourced": bool(d),
        })
        g["refs"].append(ref)
        v = d.get("value", value)
        if v and v not in g["values"]:
            g["values"].append(v)
        amfr, ampn, anote = alt.get(ref, ("", "", ""))
        if ampn and mpn and ampn != mpn:
            g["alt"] = f"PCB Train UK alternate: {amfr} {ampn}".strip()
            # The substitution rationale is usually already in Notes; don't say it twice.
            if anote and anote not in (g["notes"] or ""):
                g["alt"] += f" - {anote}"

    out = os.path.join(gdir, f"{slug}-bom.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Item", "Qty", "References", "Value", "Footprint", "Description",
                    "Manufacturer", "MPN", "LCSC", "Mount", "DNP", "Notes"])
        ordered = sorted(groups.values(), key=lambda g: ref_key(sorted(g["refs"], key=ref_key)[0]))
        for i, g in enumerate(ordered, 1):
            notes = g["notes"]
            if g.get("alt"):
                notes = f"{notes} | {g['alt']}" if notes else g["alt"]
            if not g["sourced"]:
                pre = "NOT ON ANY VENDOR BOM - hand-fit / source yourself"
                notes = f"{pre} | {notes}" if notes else pre
            w.writerow([i, len(g["refs"]), collapse_refs(g["refs"]),
                        " / ".join(g["values"]), g["footprint"],
                        g["description"], g["manufacturer"], g["mpn"], g["lcsc"],
                        g["mount"], g["dnp"], notes])
    return out, sum(1 for g in groups.values() if not g["sourced"])


def seed_pcbtrain_cpl(fab, gdir, slug):
    """PCB Train take a plain CSV, so build theirs from the generic CPL.

    Their BOM re-sources parts to UK stock, so the MPN column here must come
    from *their* BOM - a CPL that named the LCSC part would send the line
    operator looking for a part that is not in the kit.
    """
    ptdir = os.path.join(fab, "pcbtrain")
    dst = os.path.join(ptdir, f"{slug}-pcbtrain-cpl.csv")
    if not os.path.isdir(ptdir) or os.path.exists(dst):
        return None
    mpn = {}
    for name in os.listdir(ptdir):
        if name.endswith(".csv") and "bom" in name.lower():
            for r in read_csv(os.path.join(ptdir, name)):
                m = pick(r, "Manufacturer Part Number", "MPN")
                for ref in expand_refs(pick(r, "Designator", "Reference Designators", "Refs")):
                    mpn[ref] = m
    rows = read_csv(os.path.join(gdir, f"{slug}-cpl.csv"))
    with open(dst, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Designator", "Manufacturer Part Number", "Value", "Package",
                    "X (mm)", "Y (mm)", "Rotation", "Side"])
        for r in rows:
            d = r["Designator"]
            w.writerow([d, mpn.get(d, ""), r["Value"], r["Package"],
                        r["X (mm)"], r["Y (mm)"], r["Rotation"], r["Side"]])
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("board")
    ap.add_argument("--slug")
    a = ap.parse_args()

    board = os.path.abspath(a.board)
    hwdir = os.path.dirname(board)
    slug = a.slug or os.path.splitext(os.path.basename(board))[0]
    fab = os.path.join(hwdir, "fab")
    gdir = os.path.join(fab, "generic")
    os.makedirs(gdir, exist_ok=True)

    print(f"[{slug}] generic gerbers + drill")
    gerbers, zip_path = export_generic(board, None, gdir, slug)
    print(f"         {len(os.listdir(gerbers))} files -> {os.path.basename(zip_path)}")

    print(f"[{slug}] generic BOM")
    bom, unsourced = build_generic_bom(board, fab, gdir, slug)
    print(f"         {os.path.basename(bom)}"
          + (f"  ({unsourced} line(s) with no vendor sourcing)" if unsourced else ""))

    cpl = seed_pcbtrain_cpl(fab, gdir, slug)
    if cpl:
        print(f"[{slug}] pcbtrain: built CPL from the generic set + their re-sourced BOM")

    for v in VENDORS:
        vd = os.path.join(fab, v)
        if not os.path.isdir(vd):
            continue
        target = os.path.join(vd, f"{slug}-{v}-gerbers.zip")
        if not os.path.exists(target):
            shutil.copy2(zip_path, target)
            print(f"[{slug}] {v}: seeded gerber archive from the generic set")


if __name__ == "__main__":
    sys.exit(main())
