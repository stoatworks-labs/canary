#!/usr/bin/env python3
"""
Rev B fabrication package, from the routed board: hardware/rev-b/fab/.

    <kicad python> hardware/rev-b/scripts/fab.py       # after build.sh route

  fab/generic/  gerbers + drill (loose and zipped), IPC-D-356 netlist, CPL and
                BOM: every placed part, one line per orderable part
  fab/jlcpcb/   gerber zip, BOM and CPL in JLCPCB's upload format

The gerbers, drill and netlist use rev A's fab_package.py settings (same
layers, same drill options). The JLC BOM and CPL come from the JLC
Fabrication Toolkit's own CLI, as rev A's did, run on a scratch copy of the
board because it fills zones and saves. Its CPL then gets the rotation
corrections from kicad-jlcpcb-tools' database by the algorithm rev A's
jlc_rotations.py replicates. Sourcing is the board's own LCSC / MPN /
Manufacturer fields: rev A's on rev A's parts, plan.py's on the rest.
DNP parts (the Fit=DNP pads) stay out of both BOMs and both CPLs.
"""
import collections
import csv
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
REVB = os.path.normpath(os.path.join(HERE, ".."))
BOARD = os.path.join(REVB, "canary.kicad_pcb")
FAB = os.path.join(REVB, "fab")
SLUG = "canary-revb"
sys.path.insert(0, os.path.normpath(os.path.join(REVB, "..", "scripts")))
import fab_package as rev_a  # noqa: E402  (pure Python: kicad-cli and csv)
import jlc_rotations  # noqa: E402

PLUGINS = os.path.expanduser("~/Documents/KiCad/10.0/3rdparty/plugins")
JLC_TOOLKIT = os.path.join(PLUGINS, "com_github_bennymeg_JLC-Plugin-for-KiCad")


def done(code=0):
    sys.stdout.flush()
    os._exit(code)


def generic(board):
    gdir = os.path.join(FAB, "generic")
    shutil.rmtree(gdir, ignore_errors=True)
    os.makedirs(gdir)
    gerbers = os.path.join(gdir, "gerbers")
    os.makedirs(gerbers)
    cli = rev_a.KICAD_CLI
    rev_a.run(cli, "pcb", "export", "gerbers", "-o", gerbers, "--layers", rev_a.GERBER_LAYERS,
              "--no-x2", BOARD)
    rev_a.run(cli, "pcb", "export", "drill", "-o", gerbers, "--format", "excellon",
              "--drill-origin", "absolute", "--excellon-units", "mm", "--excellon-separate-th",
              "--generate-map", "--map-format", "gerberx2", BOARD)
    zip_path = os.path.join(gdir, f"{SLUG}-gerbers.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(gerbers)):
            z.write(os.path.join(gerbers, f), f)
    rev_a.run(cli, "pcb", "export", "ipcd356", "-o", os.path.join(gdir, f"{SLUG}-netlist.ipc"), BOARD)
    raw = os.path.join(gdir, ".pos.csv")
    rev_a.run(cli, "pcb", "export", "pos", "-o", raw, "--format", "csv", "--units", "mm",
              "--side", "both", "--exclude-dnp", BOARD)
    rev_a.normalise_cpl(raw, os.path.join(gdir, f"{SLUG}-cpl.csv"))
    os.remove(raw)

    # BOM straight from the board's footprints
    groups = collections.OrderedDict()
    for f in sorted(board.GetFootprints(), key=lambda f: rev_a.ref_key(f.GetReference())):
        if f.IsExcludedFromBOM():
            continue
        fields = {c.GetName(): c.GetText() for c in f.GetFields()}
        lcsc, mpn = fields.get("LCSC", ""), fields.get("MPN", "")
        fp = str(f.GetFPID().GetLibItemName())
        key = (lcsc or mpn or f.GetValue(), fp, f.IsDNP())
        g = groups.setdefault(key, {"refs": [], "values": [], "fp": fp, "lcsc": lcsc, "mpn": mpn,
                                    "maker": fields.get("Manufacturer", ""), "dnp": f.IsDNP()})
        g["refs"].append(f.GetReference())
        if f.GetValue() not in g["values"]:
            g["values"].append(f.GetValue())
    out = os.path.join(gdir, f"{SLUG}-bom.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Item", "Qty", "References", "Value", "Footprint", "Manufacturer", "MPN",
                    "LCSC", "DNP", "Notes"])
        rows = sorted(groups.values(), key=lambda g: (g["dnp"], rev_a.ref_key(g["refs"][0])))
        for i, g in enumerate(rows, 1):
            note = "" if g["lcsc"] or g["dnp"] else "no LCSC part: hand-fit or customer-supplied"
            w.writerow([i, len(g["refs"]), rev_a.collapse_refs(g["refs"]), " / ".join(g["values"]),
                        g["fp"], g["maker"], g["mpn"], g["lcsc"], "DNP" if g["dnp"] else "", note])
    fitted = [g for g in groups.values() if not g["dnp"]]
    print(f"generic: {len(os.listdir(gerbers))} gerber/drill files, BOM {len(fitted)} lines "
          f"({sum(len(g['refs']) for g in fitted)} parts), "
          f"{sum(1 for g in fitted if not g['lcsc'])} without an LCSC part")
    return zip_path


def jlcpcb(zip_path):
    jdir = os.path.join(FAB, "jlcpcb")
    shutil.rmtree(jdir, ignore_errors=True)
    os.makedirs(jdir)
    scratch = tempfile.mkdtemp(prefix="revb-jlc-")
    for f in glob.glob(os.path.join(REVB, "canary.kicad_p*")):
        shutil.copy(f, scratch)
    alias = tempfile.mkdtemp(prefix="kicad-plugins-")   # the plugin dir's name is no module name
    os.symlink(JLC_TOOLKIT, os.path.join(alias, "fabtoolkit"))
    env = dict(os.environ, PYTHONPATH=alias)
    subprocess.run([sys.executable, "-m", "fabtoolkit.cli", "--path",
                    os.path.join(scratch, "canary.kicad_pcb"), "--autoFill", "--excludeDNP",
                    "--nonInteractive", "--noBackup"], env=env, capture_output=True, check=True)
    prod = os.path.join(scratch, "production")
    shutil.copy(os.path.join(prod, "bom.csv"), os.path.join(jdir, f"{SLUG}-jlcpcb-bom.csv"))
    shutil.copy(os.path.join(prod, "designators.csv"), os.path.join(jdir, f"{SLUG}-jlcpcb-designators.csv"))
    cpl = os.path.join(jdir, f"{SLUG}-jlcpcb-cpl.csv")
    shutil.copy(os.path.join(prod, "positions.csv"), cpl)
    # Rev A's gerbers, not the toolkit's: one set of plots for both packages
    shutil.copy(zip_path, os.path.join(jdir, f"{SLUG}-jlcpcb-gerbers.zip"))
    shutil.rmtree(scratch)
    shutil.rmtree(alias)

    # The toolkit writes a UTF-8 BOM, which jlc_rotations' csv reader would take
    # as part of the first column's name
    text = open(cpl, encoding="utf-8-sig").read()
    open(cpl, "w", encoding="utf-8").write(text)
    jlc_rotations.BOARD, jlc_rotations.CPL = BOARD, cpl
    jlc_rotations.main()
    rows = list(csv.DictReader(open(os.path.join(jdir, f"{SLUG}-jlcpcb-bom.csv"), encoding="utf-8-sig")))
    blank = [r for r in rows if not r.get("LCSC Part #")]
    print(f"jlcpcb: BOM {len(rows)} lines, {len(blank)} without an LCSC part: "
          + ", ".join(r["Designator"] for r in blank))


def main():
    board = pcbnew.LoadBoard(BOARD)
    zip_path = generic(board)
    jlcpcb(zip_path)
    done()


if __name__ == "__main__":
    main()
