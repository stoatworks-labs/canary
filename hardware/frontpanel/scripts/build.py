#!/usr/bin/env python3
"""
Build the front-panel board from its schematic: outline, placement, GND pours,
the panel drilling drawing, then routing (route.py) and DRC.

    <kicad python> hardware/frontpanel/scripts/build.py

The board is generated: GUI edits are overwritten by the next run.

Geometry (mm, board origin at its top-left corner, seen from the front):
an 84 x 26 board stood off 7 mm behind a 2 mm panel. LEDs and buttons on the
front face it; the ribbon header J1 is on the back. Heights, so the panel
works out: 3 mm LEDs raised to put the dome in the panel hole (4 mm spacers),
BOOT is a 9.5 mm switch (0.5 mm proud of the panel face), RESET a 7.3 mm one
(1.7 mm behind the face, so a pin or paperclip). The drilling drawing on
Dwgs.User carries every panel hole at its position.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
FP_DIR = os.path.normpath(os.path.join(HERE, ".."))
BOARD = os.path.join(FP_DIR, "canary-fp.kicad_pcb")
SCH = os.path.join(FP_DIR, "canary-fp.kicad_sch")
KICAD_CLI = os.environ.get("KICAD_CLI", "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli")
FP_ROOT = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"
MM = pcbnew.FromMM

OX, OY = 100.0, 100.0          # board origin on the KiCad sheet
W, H = 84.0, 26.0
LED_Y, ROW = 9.0, {"D1": 16.0, "D2": 26.0, "D3": 36.0, "D4": 46.0}   # LED centres
BUTTONS = {"SW2": 60.0, "SW1": 72.0}                                # switch centres
HOLES = {"H1": (4.0, 4.0), "H2": (80.0, 4.0), "H3": (4.0, 22.0), "H4": (80.0, 22.0)}
PANEL = {"LED": 3.2, "SW2": 4.0, "SW1": 2.5, "H": 3.2}   # panel hole diameters

# ref: (x, y, rotation, back side?) of the footprint origin, board coordinates
PLACE = {
    # LED_D3.0mm's origin is pad 1 (cathode); the body centre is 1.27 mm right
    **{r: (x - 1.27, LED_Y, 0, False) for r, x in ROW.items()},
    # SW_PUSH_6mm's origin is pad 1; the body centre is (3.25, 2.25) from it
    **{r: (x - 3.25, LED_Y - 2.25, 0, False) for r, x in BUTTONS.items()},
    "R1": (16.0, 13.0, 90, False), "R2": (26.0, 13.0, 90, False),
    "R3": (36.0, 13.0, 90, False), "R4": (46.0, 13.0, 90, False),
    # J1 on the back, horizontal and centred under the LEDs: pin 1 (FP_5V) at
    # the right, odd pins on the lower row
    "J1": (50.89, 20.44, 270, True),
    "C1": (54.5, 18.0, 0, False), "C2": (54.5, 22.5, 0, False),
    # J2 (DNP): a straight 1x6 row, 3V3 GND SDA SCL FN1 FN2 from the left
    "J2": (59.0, 21.0, 90, False),
    **{r: (x, y, 0, False) for r, (x, y) in HOLES.items()},
}
LABELS = {"D1": "ON", "D2": "LAN", "D3": "CAN", "D4": "ERR", "SW2": "BOOT", "SW1": "RESET"}


def done(code=0):
    sys.stdout.flush()
    os._exit(code)


def at(x, y):
    return pcbnew.VECTOR2I(MM(OX + x), MM(OY + y))


def netlist():
    out = tempfile.NamedTemporaryFile(suffix=".net", delete=False).name
    subprocess.run([KICAD_CLI, "sch", "export", "netlist", "--format", "kicadsexpr", "-o", out, SCH],
                   check=True, capture_output=True)
    text = open(out, encoding="utf-8").read()
    comps, pads = {}, {}
    for blk in re.split(r"\(comp\s", text[text.index("(components"):text.index("(libparts")])[1:]:
        ref = re.search(r'\(ref "([^"]+)"\)', blk).group(1)
        comps[ref] = (re.search(r'\(footprint "([^"]+)"\)', blk).group(1),
                      re.search(r'\(value "([^"]*)"\)', blk).group(1))
    for blk in re.split(r"\(net\s+\(code", text[text.index("(nets"):])[1:]:
        name = re.search(r'\(name "([^"]+)"\)', blk).group(1)
        for ref, pin in re.findall(r'\(node\s+\(ref "([^"]+)"\)\s+\(pin "([^"]+)"\)', blk):
            pads[(ref, pin)] = None if name.startswith("unconnected-") else name
    return comps, pads


def line(b, layer, x1, y1, x2, y2, w=0.1):
    s = pcbnew.PCB_SHAPE(b, pcbnew.SHAPE_T_SEGMENT)
    s.SetLayer(layer)
    s.SetWidth(MM(w))
    s.SetStart(at(x1, y1))
    s.SetEnd(at(x2, y2))
    b.Add(s)


def circle(b, layer, x, y, d, w=0.1):
    s = pcbnew.PCB_SHAPE(b, pcbnew.SHAPE_T_CIRCLE)
    s.SetLayer(layer)
    s.SetWidth(MM(w))
    s.SetCenter(at(x, y))
    s.SetEnd(at(x + d / 2, y))
    b.Add(s)


def text(b, layer, x, y, s, size=1.0, mirror=False):
    t = pcbnew.PCB_TEXT(b)
    t.SetText(s)
    t.SetLayer(layer)
    t.SetPosition(at(x, y))
    t.SetTextSize(pcbnew.VECTOR2I(MM(size), MM(size)))
    t.SetTextThickness(MM(size * 0.15))
    t.SetMirrored(mirror)
    b.Add(t)


def build():
    comps, pads = netlist()
    # Start from the blank board Konnect made (NewBoard() segfaults here), never
    # from the last build: loading that and adding parts stacks a second set.
    shutil.copy(os.path.join(HERE, "blank.kicad_pcb"), BOARD)
    b = pcbnew.LoadBoard(BOARD)
    io = pcbnew.PCB_IO_MGR.FindPlugin(pcbnew.PCB_IO_MGR.KICAD_SEXP)
    codes = {}
    for name in sorted({n for n in pads.values() if n}):
        b.Add(pcbnew.NETINFO_ITEM(b, name))
    for name in sorted({n for n in pads.values() if n}):
        codes[name] = b.FindNet(name).GetNetCode()
    for ref, (fpid, value) in sorted(comps.items()):
        lib, name = fpid.split(":", 1)
        f = io.FootprintLoad(os.path.join(FP_ROOT, lib + ".pretty"), name)
        f.SetReference(ref)
        f.SetValue(value)
        f.SetFPIDAsString(fpid)
        x, y, rot, back = PLACE[ref]
        f.SetPosition(at(x, y))
        f.SetOrientationDegrees(rot)
        b.Add(f)

    # Flip() segfaults on a footprint with no board yet: flip once it is on one.
    for ref, (x, y, rot, back) in PLACE.items():
        if back:
            f = b.FindFootprintByReference(ref)
            f.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
    for (x1, y1), (x2, y2) in (((0, 0), (W, 0)), ((W, 0), (W, H)), ((W, H), (0, H)), ((0, H), (0, 0))):
        line(b, pcbnew.Edge_Cuts, x1, y1, x2, y2, 0.05)

    # GND on both sides, kept off the mounting holes (standoffs may be metal)
    for layer, name in ((pcbnew.F_Cu, "GND_F"), (pcbnew.B_Cu, "GND_B")):
        z = pcbnew.ZONE(b)
        z.SetLayer(layer)
        z.SetZoneName(name)
        z.SetNetCode(codes["/GND"])   # root-sheet local labels are "/NAME"
        z.SetLocalClearance(MM(0.3))
        z.SetMinThickness(MM(0.25))
        # Solid, not thermal: a small board, and J1's GND pins sit between two
        # rows of tracks where a relief could only get one spoke in.
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
        poly = pcbnew.SHAPE_POLY_SET()
        poly.NewOutline()
        for x, y in ((0.3, 0.3), (W - 0.3, 0.3), (W - 0.3, H - 0.3), (0.3, H - 0.3)):
            poly.Append(MM(OX + x), MM(OY + y))
        poly.thisown = 0
        z.SetOutline(poly)
        b.Add(z)
    for ref, (x, y) in HOLES.items():
        z = pcbnew.ZONE(b)
        z.SetIsRuleArea(True)
        z.SetZoneName(f"KEEPOUT_{ref}")
        z.SetLayerSet(pcbnew.LSET.AllCuMask())
        for f in (z.SetDoNotAllowTracks, z.SetDoNotAllowVias, z.SetDoNotAllowZoneFills):
            f(True)
        z.SetDoNotAllowPads(False)
        z.SetDoNotAllowFootprints(False)
        poly = pcbnew.SHAPE_POLY_SET()
        poly.NewOutline()
        for dx, dy in ((-3.6, -3.6), (3.6, -3.6), (3.6, 3.6), (-3.6, 3.6)):
            poly.Append(MM(OX + x + dx), MM(OY + y + dy))
        poly.thisown = 0
        z.SetOutline(poly)
        b.Add(z)

    # Freerouting does not know the 0.5 mm edge clearance: keep tracks 0.6 mm in.
    for name, (x1, y1, x2, y2) in {"EDGE_T": (0, 0, W, 0.6), "EDGE_B": (0, H - 0.6, W, H),
                                   "EDGE_L": (0, 0, 0.6, H), "EDGE_R": (W - 0.6, 0, W, H)}.items():
        z = pcbnew.ZONE(b)
        z.SetIsRuleArea(True)
        z.SetZoneName(name)
        z.SetLayerSet(pcbnew.LSET.AllCuMask())
        z.SetDoNotAllowTracks(True)
        z.SetDoNotAllowVias(True)
        z.SetDoNotAllowZoneFills(False)
        z.SetDoNotAllowPads(False)
        z.SetDoNotAllowFootprints(False)
        poly = pcbnew.SHAPE_POLY_SET()
        poly.NewOutline()
        for x, y in ((x1, y1), (x2, y1), (x2, y2), (x1, y2)):
            poly.Append(MM(OX + x), MM(OY + y))
        poly.thisown = 0
        z.SetOutline(poly)
        b.Add(z)

    # Front legends (hidden behind the panel, there for assembly) ...
    for ref, s in LABELS.items():
        x = ROW.get(ref, BUTTONS.get(ref))
        text(b, pcbnew.F_SilkS, x, 3.3, s, 1.0)
    text(b, pcbnew.F_SilkS, 66.0, 24.6, "CANary front panel rev A", 0.8)
    text(b, pcbnew.B_SilkS, 42.0, 13.0, "J1: ribbon to main board J501, pin 1 = FP_5V", 0.8, mirror=True)
    # ... and the panel drilling drawing: every hole the panel needs, on Dwgs.User
    for ref, x in ROW.items():
        circle(b, pcbnew.Dwgs_User, x, LED_Y, PANEL["LED"])
        text(b, pcbnew.Dwgs_User, x, LED_Y + 3.6, LABELS[ref], 1.2)
    for ref, x in BUTTONS.items():
        circle(b, pcbnew.Dwgs_User, x, LED_Y, PANEL[ref])
        text(b, pcbnew.Dwgs_User, x, LED_Y + 4.2, LABELS[ref], 1.2)
    for x, y in HOLES.values():
        circle(b, pcbnew.Dwgs_User, x, y, PANEL["H"])
    text(b, pcbnew.Dwgs_User, W / 2, H + 3.0,
         "PANEL HOLES: LEDs 3.2, BOOT 4.0, RESET 2.5 (pin access), M3 standoffs 7 mm", 1.0)

    ds = b.GetDesignSettings()
    ds.SetCopperLayerCount(2)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(BOARD, b)
    print(f"built {len(comps)} footprints on an {W:g} x {H:g} board")


def assign():
    """Pad nets, in a process of their own: set before Add() they did not
    stick, and pcbnew's bindings go bad once a process has added footprints."""
    _, pads = netlist()
    b = pcbnew.LoadBoard(BOARD)
    bad = 0
    # A saved board drops nets nothing uses, so they are made here, read first.
    for n in sorted({n for n in pads.values() if n}):
        if b.FindNet(n) is None:
            b.Add(pcbnew.NETINFO_ITEM(b, n))
    codes = {n: b.FindNet(n).GetNetCode() for n in {n for n in pads.values() if n}}
    for f in b.GetFootprints():
        for p in f.Pads():
            n = pads.get((f.GetReference(), p.GetNumber()))
            p.SetNetCode(codes[n] if n else 0)
    for z in b.Zones():
        if not z.GetIsRuleArea():
            z.SetNetCode(codes["/GND"])
    # Attributes follow the schematic, so parity holds: its holes are "in the
    # BOM" (the stock footprint says otherwise) and nothing carries the DNP
    # flag, which Konnect cannot set. J2's fitting lives in a Fit=DNP field,
    # as on the main board; the fab step drops holes and Fit=DNP parts.
    for f in b.GetFootprints():
        ref = f.GetReference()
        if ref.startswith("H"):
            f.SetAttributes(f.GetAttributes() & ~pcbnew.FP_EXCLUDE_FROM_BOM)
            f.Reference().SetVisible(False)   # at the board edge, and a hole needs no name
        if ref == "J2":
            f.SetField("Fit", "DNP")
            for fld in f.GetFields():
                if fld.GetName() == "Fit":
                    fld.SetVisible(False)   # SetField() puts it on F.Silkscreen
                    fld.SetLayer(pcbnew.F_Fab)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(BOARD, b)
    b = pcbnew.LoadBoard(BOARD)
    for f in b.GetFootprints():
        for p in f.Pads():
            want = pads.get((f.GetReference(), p.GetNumber())) or ""
            if p.GetNetname() != want:
                print(f"FAIL {f.GetReference()}.{p.GetNumber()}: {p.GetNetname()!r}, schematic {want!r}")
                bad += 1
    print(f"{'FAIL' if bad else 'OK'}: pad nets match the schematic")
    return bad


FREEROUTING = os.environ.get(
    "FREEROUTING", os.path.expanduser("~/.local/share/freerouting/2.5.0/freerouting-2.5.0.jar"))
WORK = os.path.join(FP_DIR, "route")   # git-ignored


def route():
    """Freerouting on both layers. The board starts with no tracks, so the
    session goes straight in; GND is routed too, then the pours join it."""
    os.makedirs(WORK, exist_ok=True)
    dsn, ses = os.path.join(WORK, "canary-fp.dsn"), os.path.join(WORK, "canary-fp.ses")
    for p in (dsn, ses):
        if os.path.exists(p):
            os.remove(p)
    b = pcbnew.LoadBoard(BOARD)
    if not pcbnew.ExportSpecctraDSN(b, dsn):
        sys.exit("DSN export failed")
    with open(os.path.join(WORK, "freerouting.log"), "w") as log:
        subprocess.run(["java", "-jar", FREEROUTING, "-de", dsn, "-do", ses, "-mp", "20",
                        "--gui.enabled=false", "--router.automatic_neckdown=false"],
                       stdout=log, stderr=subprocess.STDOUT)
    if not os.path.exists(ses) or not pcbnew.ImportSpecctraSES(b, ses):
        sys.exit("no session: see route/freerouting.log")
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(BOARD, b)
    print(f"routed: {len(list(b.GetTracks()))} tracks and vias")


def drc():
    out = os.path.join(WORK, "drc.json")
    subprocess.run([KICAD_CLI, "pcb", "drc", "--format", "json", "--severity-all", "--refill-zones",
                    "--schematic-parity", "-o", out, BOARD], capture_output=True)
    import collections
    import json
    d = json.load(open(out))
    c = collections.Counter((v["severity"], v["type"]) for v in d["violations"])
    c[("error", "unconnected_items")] = len(d.get("unconnected_items", []))
    c[("error", "schematic_parity")] = len(d.get("schematic_parity", []))
    for k, n in sorted(c.items()):
        if n:
            print(f"DRC {k[0]:8} {k[1]:28} {n}")
    return sum(n for (sev, _), n in c.items() if sev == "error")


def stage(name, fatal=True):
    r = subprocess.run([sys.executable, os.path.abspath(__file__), name], capture_output=True, text=True)
    print("\n".join(l for l in r.stdout.splitlines()
                    if not re.search("wxApp|traits|Debug:|memory leak", l)))
    if r.returncode and fatal:
        print(r.stderr[-1500:])
        done(r.returncode)
    return r.returncode


if __name__ == "__main__":
    if "--nets" in sys.argv:
        done(1 if assign() else 0)
    if "--route" in sys.argv:
        route()
        done()
    if "--drc" in sys.argv:
        done(1 if drc() else 0)
    if "--build" in sys.argv:
        build()
        done()
    # Freerouting is not deterministic: build again until DRC is clean.
    for attempt in range(1, 6):
        stage("--build")
        stage("--nets")
        stage("--route")
        if stage("--drc", fatal=False) == 0:
            print(f"attempt {attempt}: DRC clean")
            done()
        print(f"attempt {attempt}: DRC errors, building again")
    done(1)
