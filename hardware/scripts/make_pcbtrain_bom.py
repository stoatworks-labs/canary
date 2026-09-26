#!/usr/bin/env python3
"""
Generate a PCB Train (Newbury Electronics) format BOM.

WHY THIS IS NOT JUST A COLUMN RENAME
------------------------------------
PCB Train's own template states:

    "Only the Manufacturer Name and Manufacturer Part Number will be used for
     costings and subsequent materials procurement."
    "Please note that the Description field will NOT be checked."

So the MPN column IS the order. Every part in this design was chosen from
JLCPCB's library, which means a good number of them are China-domestic parts
(UNI-ROYAL resistors, Fenghua caps, KENTO LEDs, BHFUSE PTC, WCH, Hroparts) that
a UK house cannot buy at any price. Handing those MPNs to PCB Train would come
back as a quote full of holes.

This script therefore carries an explicit UK sourcing map. Every substitute in
it was checked against DigiKey UK on 2026-07-26 - manufacturer, value, voltage,
dielectric, package and stock - and the evidence is recorded per line in the
Notes column so the reader can audit it rather than trust it.

RULES THE MAP FOLLOWS
  keep      the designed part is UK-stocked. Nothing changes.
  sub       not UK-sourceable; a verified equivalent goes in the MPN column and
            the original is recorded in Notes. Same footprint in every case -
            substitutions here never change a land pattern.
  derate    a substitute that does NOT fully meet the original spec. Called out
            in Notes in capitals, because this is the designer's call, not this
            script's.
  free      no western source exists. Supplier Name is set to "Free issued",
            which is PCB Train's own convention for a client-supplied part.
  dnf       Do Not Fit.

Regenerate:  python3 hardware/scripts/make_pcbtrain_bom.py
"""
import csv
import re
import sys
from pathlib import Path

HW = Path(__file__).resolve().parent.parent
SRC = HW / "fab" / "pcbway" / "dbcanary-pcbway-bom.csv"
OUT_DIR = HW / "fab" / "pcbtrain"
VERIFIED = "2026-07-26"

# Total placements on the board. Asserted so that a stale or half-regenerated
# input BOM fails loudly instead of quietly under-ordering.
EXPECTED_PLACEMENTS = 76

# ---------------------------------------------------------------------------
# The sourcing map, keyed by designator.
#
#   mfr, mpn   what PCB Train will actually buy
#   desc       human description (they do not check it, but a person reads it)
#   action     keep | sub | derate | free | dnf
#   note       evidence and/or what the designer needs to decide
# ---------------------------------------------------------------------------
KEEP = "keep"; SUB = "sub"; DERATE = "derate"; FREE = "free"
DNF = "dnf"; RISK = "risk"   # RISK: MPN unchanged, but availability is a problem

P = lambda mfr, mpn, desc, action, note: dict(
    mfr=mfr, mpn=mpn, desc=desc, action=action, note=note)

# --- passives that survive unchanged --------------------------------------
C_100N = P("Samsung Electro-Mechanics", "CL05B104KO5NNNC",
           "CAP CER 100nF 16V X7R 0402", KEEP,
           f"DigiKey UK 8,392,367 in stock {VERIFIED}")
C_1U = P("Samsung Electro-Mechanics", "CL05A105KA5NQNC",
         "CAP CER 1uF 25V X5R 0402", KEEP,
         f"DigiKey UK 1,871,894 in stock {VERIFIED}")
C_4U7 = P("Samsung Electro-Mechanics", "CL10A475KO8NNNC",
          "CAP CER 4.7uF 16V X5R 0603", KEEP,
          f"DigiKey UK 118,638 in stock {VERIFIED}")
C_10N = P("Samsung Electro-Mechanics", "CL05B103KB5NNNC",
          "CAP CER 10nF 50V X7R 0402", KEEP,
          f"DigiKey UK 6,151,308 in stock {VERIFIED}")
C_6N8 = P("YAGEO", "CC0402KRX7R9BB682",
          "CAP CER 6.8nF 50V X7R 0402", KEEP,
          f"DigiKey UK 76,814 in stock {VERIFIED}")

# --- passives that had to change ------------------------------------------
C_10U = P("Taiyo Yuden", "TMK212BBJ106KGHT",
          "CAP CER 10uF 25V X5R 0805", SUB,
          "was CL21A106KAYNNNE (Samsung): 0 stock at DigiKey UK, 49-week "
          f"factory lead time. Substitute 275,536 in stock {VERIFIED}. "
          "Same 0805 land pattern, same 25V X5R.")
C_22U = P("KYOCERA AVX", "KGM21AR51E226MU",
          "CAP CER 22uF 25V X5R 0805", SUB,
          "was CL21A226MAQNNNE (Samsung): OBSOLETE, no longer manufactured; "
          "even Samsung's own CL21A226MAYNNNE replacement is out of stock. "
          f"Substitute 55,097 in stock {VERIFIED}. Same 0805, 25V X5R.")
C_4N7 = P("Samsung Electro-Mechanics", "CL10B472KB8NNNC",
          "CAP CER 4.7nF 50V X7R 0603", SUB,
          "was 0603B472K500NT (Fenghua): China-domestic, not stocked in the "
          f"West. Substitute 3,125,426 in stock {VERIFIED}.")
C_18P = P("Samsung Electro-Mechanics", "CL05C180JB5NNNC",
          "CAP CER 18pF 50V C0G/NP0 0402", SUB,
          "was 0402CG180J500NT (Fenghua): China-domestic. Substitute 542,765 "
          f"in stock {VERIFIED}. C0G confirmed - these are the crystal load "
          "caps, so the dielectric matters.")
C_1N_2KV = P("YAGEO", "CC1206KKX7RDBB102",
             "CAP CER 1nF 2kV X7R 1206", SUB,
             "was 1206B102K202NT (Fenghua): China-domestic. Substitute "
             f"confirmed 2000V X7R 1206, 295,090 in stock {VERIFIED}. "
             "SAFETY-RELEVANT: this is the capacitor bridging the CAN "
             "isolation barrier - the 2kV rating is the reason it is a 1206.")

# --- resistors: whole family moved to Yageo RC, every value verified ------
def R(mpn, val, stock, pkg="0402", tol="1%"):
    return P("YAGEO", mpn, f"RES {val} {tol} {pkg}", SUB,
             "was UNI-ROYAL (China-domestic, not stocked in the West). "
             f"DigiKey UK {stock} in stock {VERIFIED}.")

R_31K6 = R("RC0402FR-0731K6L", "31.6k", "1,526,832")
R_10K = P("YAGEO", "RC0402FR-1310KL", "RES 10k 1% 0402", SUB,
          "was UNI-ROYAL (China-domestic). NOTE the -13 series code, not -07: "
          "RC0402FR-0710KL is the same value but had only 762 in stock, "
          f"whereas -13 had 79,602 {VERIFIED}. Electrically identical.")
R_1K = R("RC0402FR-071KL", "1k", "11,751,037")
R_100K = R("RC0402FR-07100KL", "100k", "8,435,644")
R_0R = P("YAGEO", "RC0402JR-070RL", "RES 0 ohm jumper 0402", SUB,
         "was UNI-ROYAL (China-domestic). DigiKey UK 10,726,477 in stock "
         f"{VERIFIED}. J-series because a jumper has no meaningful tolerance.")
R_62R = R("RC0603FR-0762RL", "62R", "51,612", pkg="0603")
R_12K4 = R("RC0402FR-0712K4L", "12.4k", "582,138")
R_75R = R("RC0603FR-0775RL", "75R", "254,084", pkg="0603")
R_49R9 = R("RC0402FR-0749R9L", "49.9R", "1,249,726")
R_10R = R("RC0402FR-0710RL", "10R", "3,567,505")
R_1M = R("RC0402FR-071ML", "1M", "1,711,666")

# --- everything else ------------------------------------------------------
LED_G = P("Lite-On Inc.", "LTST-C190KGKT", "LED GREEN CLEAR 0603 SMD", SUB,
          "was KT-0603G (Hubei KENTO): China-domestic. Substitute 1,892,900 "
          f"in stock {VERIFIED}. Active low, 1k series resistor - forward "
          "voltage is not critical.")
LED_R = P("Lite-On Inc.", "LTST-C190KRKT", "LED RED CLEAR 0603 SMD", SUB,
          "was KT-0603R (Hubei KENTO): China-domestic. Substitute 1,033,054 "
          f"in stock {VERIFIED}. Same Lite-On family as the greens, so one "
          "series and one datasheet covers all four LEDs.")

MAP = {
    # capacitors
    "C105": C_100N, "C108": C_100N, "C201": C_100N, "C203": C_100N,
    "C204": C_100N, "C206": C_100N, "C302": C_100N, "C303": C_100N,
    "C304": C_100N, "C404": C_100N, "C405": C_100N, "C406": C_100N,
    "C407": C_100N, "C409": C_100N,
    "C106": C_22U, "C301": C_22U,
    "C107": C_10U, "C202": C_10U, "C205": C_10U, "C403": C_10U,
    "C109": C_1U,
    "C207": C_4N7,
    "C401": C_18P, "C402": C_18P,
    "C408": C_4U7, "C410": C_4U7,
    "C411": C_1N_2KV,
    "C412": C_10N,
    "C413": C_6N8,

    # diodes / LEDs
    "D201": P("onsemi", "NUP2105LT1G", "TVS DIODE 24VWM 44VC SOT-23", KEEP,
              "MANUFACTURER CORRECTED: the JLCPCB BOM credited this to 'TECH "
              "PUBLIC', which is a clone house. onsemi is the originator and "
              f"DigiKey UK stocks it at GBP 0.33 {VERIFIED}. Buy the onsemi "
              "part - it is an ESD device on an isolated bus."),
    "D301": LED_G, "D303": LED_G, "D304": LED_G,
    "D302": LED_R,

    # protection / magnetics
    "F101": P("Bourns Inc.", "MF-NSMF110/16X-2",
              "PTC RESETTABLE FUSE 1.1A HOLD 16V 1206", DERATE,
              "was BSMD1206-110-30V (BHFUSE): China-domestic, rated 30V. "
              "**THE 30V RATING CANNOT BE MET IN 1206.** A survey of DigiKey "
              "UK's 1206 PPTCs at 1.1A hold found 16V to be the highest "
              "available (this part, 3,066 in stock); everything else was 6V. "
              "16V is comfortable for the 5V VBUS this board actually runs on "
              "- CH224K is configured for a 5V contract - but it does NOT "
              "cover the 20V a PD supply could present if that ever changed. "
              "DESIGNER TO CONFIRM. The alternative is a larger package in "
              f"rev B. Verified {VERIFIED}."),
    "FB201": P("Murata Electronics", "BLM18AG601SN1D",
               "FERRITE BEAD 600 OHM @ 100MHz 0603", KEEP,
               f"DigiKey UK 2,148,543 in stock {VERIFIED}"),
    "L102": P("Bourns Inc.", "SRN4018-2R2M",
              "INDUCTOR 2.2uH 2.9A SHIELDED DRUM", KEEP,
              f"DigiKey UK 86,769 in stock {VERIFIED}"),
    "T401": P("Bourns Inc.", "PT61017PEL",
              "XFMR LAN 10/100 BASE-T 350uH 1CT:1CT SMD", KEEP,
              f"DigiKey UK 7,881 in stock {VERIFIED}"),

    # connectors
    "J102": P("Korean Hroparts Elec", "TYPE-C-31-M-12",
              "CONN RCPT USB-C 16P SMD", FREE,
              "China-domestic, and the KiCad land pattern "
              "(USB_C_Receptacle_HRO_TYPE-C-31-M-12) is drawn for THIS part. "
              "Western 16-pin USB-C receptacles exist but pin and shell "
              "geometry vary between makers, so a swap cannot be assumed to "
              "drop in. FREE ISSUE is the low-risk route: buy from LCSC and "
              "send them in. If PCB Train are to source it, they must confirm "
              "the mechanical drawing against the footprint first."),
    "J201": P("Neutrik", "NE8FBH", "CONN RCPT ETHERCON CAT5 B-SERIES PCB", KEEP,
              "MPN ADDED - this line was blank on the JLCPCB BOM because JLC "
              "cannot hand-fit it. PCB Train do through-hole assembly, so "
              f"unlike JLCPCB they CAN fit these. DigiKey UK GBP 6.31 {VERIFIED}."),
    "J301": P("DO NOT FIT", "DO NOT FIT",
              "HEADER 1x6 1.27mm PITCH VERTICAL THROUGH-HOLE - NOT FITTED", DNF,
              "DO NOT FIT. A 1x6 1.27mm SINGLE-ROW THROUGH-HOLE header is an "
              "awkward part - the 1.27mm parts carried by DigiKey UK are all "
              "either dual-row or SMD (M50-3600642, 20021121-00006T4LF, "
              "FTSH-106-01-L-DV all checked and all wrong). This is only a "
              "UART/debug header and the ESP32-S3's native USB already gives "
              "console access, so it is not needed to bring the board up. "
              "Leave the holes empty and fit a header by hand if ever wanted."),

    # switches
    "SW201": P("CTS Electrocomponents", "206-2ST",
               "SWITCH DIP SLIDE SPST x2 2.54mm", SUB,
               "was unspecified on the JLCPCB BOM. 206-2ST is a 2-position "
               f"SPST slide DIP switch, DigiKey UK 12,933 in stock {VERIFIED}. "
               "CHECK THE FOOTPRINT: the board uses "
               "SW_DIP_SPSTx02_Slide_9.78x7.26mm_W7.62mm_P2.54mm and this "
               "part's body/row spacing needs confirming against it. This is "
               "the CAN bus termination switch - a passive mechanical switch, "
               "so getting it wrong costs a rework, not a redesign."),
    "SW301": P("C&K", "PTS645SK43SMTR92LFS", "SWITCH TACTILE SPST-NO 6mm SMD",
               KEEP, f"DigiKey UK 103,472 in stock {VERIFIED}"),

    # actives
    "U103": P("Diodes Incorporated", "AP63200WU-7",
              "IC REG BUCK ADJ 2A TSOT-23-6", RISK,
              "**SUPPLY RISK.** DigiKey UK showed 0 stock and a 40-WEEK "
              f"manufacturer lead time {VERIFIED}; the AP63201/03/05 siblings "
              "were also at zero. It IS plentiful at LCSC (C2071868). Ask PCB "
              "Train to check their own channels (Mouser/RS were unreachable "
              "from here so are unchecked) and be ready to free-issue this "
              "one too. Do NOT let a substitute buck be chosen for you: the "
              "output is set by an external divider (R103/R401) and a "
              "fixed-output sibling would silently ignore it."),
    "U104": P("WCH(Jiangsu Qin Heng)", "CH224K",
              "IC USB PD SINK CONTROLLER SSOP-10", FREE,
              "**NO WESTERN SOURCE EXISTS.** DigiKey UK returns no results "
              f"for CH224K at all {VERIFIED} - WCH sell through Chinese "
              "channels only. There is no cross-reference to give PCB Train, "
              "so FREE ISSUE is the only option short of redesigning the "
              "power input around a western PD controller. Buy from LCSC "
              "(C970725) and send them in with the boards."),
    "U201": P("Analog Devices Inc.", "ADM3053BRWZ",
              "IC TXRX CAN ISOLATED w/ isoPower SOIC-20W", SUB,
              "MPN shortened from ADM3053BRWZ-REEL7: '-REEL7' only specifies "
              "a 7-inch reel, and DigiKey UK lists the plain part (GBP 11.91) "
              f"rather than that suffix {VERIFIED}. Let the supplier choose "
              "packaging. Most expensive part on the board - check its price "
              "on the quote."),
    "U301": P("Espressif Systems", "ESP32-S3-WROOM-1-N8",
              "MODULE ESP32-S3 WIFI/BT 8MB FLASH", KEEP,
              f"DigiKey UK GBP 4.29, in stock {VERIFIED}"),
    "U401": P("WIZnet", "W5500",
              "IC ETHERNET MAC+PHY SPI LQFP-48", KEEP,
              f"DigiKey UK GBP 2.87, in stock {VERIFIED}"),

    # crystal
    "Y401": P("Abracon LLC", "ABM8-25.000MHZ-12-R40-D3Y-T",
              "CRYSTAL 25MHz 12pF 3.2x2.5mm 4-SMD", DERATE,
              "was X322525MOB4SI (YXC): China-domestic. "
              "LOAD CAPACITANCE PRESERVED at 12pF, which is the number that "
              "matters - C401/C402 are 18pF precisely because CL is 12pF, so "
              "a CL=18pF crystal would need those changed to ~30pF and that "
              "is a schematic edit, not a substitution. "
              "STABILITY IS RELAXED: +/-30ppm against the original +/-10ppm. "
              "IEEE 802.3 allows +/-100ppm on 100BASE-TX, so 30ppm is "
              "comfortably inside what the W5500 needs - but it is a "
              "relaxation of a stated spec, so DESIGNER TO CONFIRM. "
              f"Only 723 in stock {VERIFIED}: fine for a handful of "
              "prototypes, reserve early for a run."),
}
# Designators sharing a part with one already listed.
MAP["J202"] = MAP["J401"] = MAP["J201"]
MAP["SW302"] = MAP["SW301"]
for d in ("R103",): MAP[d] = R_31K6
# R107 moved 100k -> 10k: WCH's CH224 datasheet reference schematics (6.1/6.2/
# 6.3) all put 10k in series into the VBUS sense pin. That retires R_100K, which
# had no other user.
for d in ("R104", "R107", "R301"): MAP[d] = R_10K
for d in ("R106", "R302", "R303", "R304", "R305"): MAP[d] = R_1K
for d in ("R201", "R412"): MAP[d] = R_0R
for d in ("R202", "R203"): MAP[d] = R_62R
for d in ("R401",): MAP[d] = R_12K4
for d in ("R402", "R403", "R404", "R405"): MAP[d] = R_75R
for d in ("R406", "R407", "R408", "R409"): MAP[d] = R_49R9
for d in ("R410",): MAP[d] = R_10R
for d in ("R411",): MAP[d] = R_1M


def natural(des):
    """Sort R2 before R10, and group by prefix."""
    m = re.match(r"([A-Za-z]+)(\d+)", des)
    return (m.group(1), int(m.group(2))) if m else (des, 0)


def collapse(designators):
    """C1, C2, C3, C7 -> 'C1-C3, C7'. PCB Train's own sample uses ranges."""
    out, run = [], []

    def flush():
        if not run:
            return
        if len(run) == 1:
            out.append(run[0])
        elif len(run) == 2:
            out.extend(run)
        else:
            out.append(f"{run[0]}-{run[-1]}")
        run.clear()

    prev = None
    for d in designators:
        p, n = natural(d)
        if prev and p == prev[0] and n == prev[1] + 1:
            run.append(d)
        else:
            flush()
            run.append(d)
        prev = (p, n)
    flush()
    return ", ".join(out)


def write_xlsx(path, header, body, lines):
    """PCB Train's template is an .xlsx, so ship one - but their own note says
    'Formatting / order of columns not critical', so this stays plain: no merged
    cells, no macros, nothing an importer can trip over. The colour key is a
    reading aid for the human doing the quote, not data."""
    try:
        import openpyxl
        from openpyxl.styles import Alignment, Font, PatternFill
    except ImportError:
        print("  (openpyxl not installed - .xlsx skipped, .csv is complete)")
        return

    FILLS = {
        DERATE: "FFF2CC",   # amber - a spec was relaxed
        RISK:   "FFF2CC",
        FREE:   "DDEBF7",   # blue  - client supplies
        DNF:    "F2F2F2",   # grey  - not fitted
    }

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "BOM"
    ws.append(header)
    for c in ws[1]:
        c.font = Font(bold=True)
    for row, (part, _) in zip(body, lines):
        ws.append(row)
        fill = FILLS.get(part["action"])
        if fill:
            for c in ws[ws.max_row]:
                c.fill = PatternFill("solid", fgColor=fill)

    for col, width in zip("ABCDEFGHI",
                          (6, 42, 9, 26, 30, 13, 22, 30, 100)):
        ws.column_dimensions[col].width = width
    for r in ws.iter_rows(min_row=2):
        r[1].alignment = Alignment(vertical="top")
        r[7].alignment = Alignment(vertical="top", wrap_text=True)
        r[8].alignment = Alignment(vertical="top", wrap_text=True)
    ws.freeze_panes = "A2"

    n = ws.max_row + 2
    notes = [
        ("Key", None),
        ("amber", "Substitute does NOT fully meet the original specification, "
                  "or availability is a problem. DESIGNER MUST CONFIRM before "
                  "this is ordered."),
        ("blue", "Free issued - no Western source exists. We supply these "
                 "parts; please do not attempt to procure them."),
        ("grey", "Do not fit. Leave the pads/holes empty."),
        (None, None),
        ("Note on manufacturer part numbers", None),
        (None, "This board was originally costed through JLCPCB, so a number of "
               "the designed parts were China-domestic and cannot be bought in "
               "the UK. Those lines have been re-specified against UK stock and "
               "the original part is recorded in the Notes column. Every "
               "substitution keeps the same land pattern - no footprint "
               f"changes. Stock figures were checked on {VERIFIED}."),
        (None, "Two lines need a decision from us before you order: F101 "
               "(PTC voltage rating) and Y401 (crystal stability). Both are "
               "marked amber and explained in Notes."),
    ]
    for i, (label, text) in enumerate(notes):
        if label:
            ws.cell(row=n + i, column=1, value=label).font = Font(bold=True)
        if text:
            c = ws.cell(row=n + i, column=2, value=text)
            c.alignment = Alignment(wrap_text=True, vertical="top")
            ws.merge_cells(start_row=n + i, start_column=2,
                           end_row=n + i, end_column=9)
    wb.save(path)
    print(f"wrote {path.relative_to(HW.parent)}")


def main():
    if not SRC.exists():
        sys.exit(f"missing source BOM: {SRC}")

    # utf-8-sig: the vendor toolkit writes a UTF-8 BOM marker, which otherwise
    # corrupts the first column name.
    with SRC.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))

    designators = []
    for r in rows:
        designators += [d.strip() for d in r["Designator"].split(",") if d.strip()]

    if len(designators) != EXPECTED_PLACEMENTS:
        sys.exit(f"expected {EXPECTED_PLACEMENTS} placements, source has "
                 f"{len(designators)}. Source BOM changed - review the map.")

    missing = sorted(set(designators) - set(MAP), key=natural)
    if missing:
        sys.exit(f"no sourcing decision for: {', '.join(missing)}")

    # Group designators by the part they resolve to, so identical parts become
    # one purchasing line. id() works because the map shares dict objects.
    groups = {}
    for d in designators:
        groups.setdefault(id(MAP[d]), (MAP[d], []))[1].append(d)

    lines = []
    for part, des in groups.values():
        des.sort(key=natural)
        lines.append((part, des))
    lines.sort(key=lambda t: natural(t[1][0]))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    header = ["Item#", "Description", "Quantity", "Manufacturer Name",
              "Manufacturer Part Number", "Supplier Name",
              "Supplier Part Number", "Designator", "Notes"]

    body = []
    for i, (part, des) in enumerate(lines, 1):
        supplier = "Free issued" if part["action"] == FREE else ""
        note = part["note"]
        if part["action"] == DNF:
            note = note  # already leads with DO NOT FIT
        body.append([i, part["desc"], len(des), part["mfr"], part["mpn"],
                     supplier, part["mpn"] if supplier else "",
                     collapse(des), note])

    csv_path = OUT_DIR / "dbcanary-pcbtrain-bom.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(body)

    write_xlsx(OUT_DIR / "dbcanary-pcbtrain-bom.xlsx", header, body, lines)

    fitted = sum(r[2] for r, (p, d) in zip(body, lines) if p["action"] != DNF)
    print(f"wrote {csv_path.relative_to(HW.parent)}")
    print(f"  {len(body)} purchasing lines, {sum(r[2] for r in body)} "
          f"placements ({fitted} fitted, "
          f"{sum(r[2] for r in body) - fitted} do-not-fit)")
    for action, label in ((KEEP, "unchanged"), (SUB, "substituted"),
                          (DERATE, "SPEC RELAXED - confirm"),
                          (RISK, "SUPPLY RISK - confirm"),
                          (FREE, "free issue - no UK source"),
                          (DNF, "do not fit")):
        n = [d[0] for p, d in lines if p["action"] == action]
        if n:
            print(f"  {label:32} {len(n):2}  {', '.join(n)}")
    return body, lines, header


if __name__ == "__main__":
    main()
