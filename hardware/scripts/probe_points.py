#!/usr/bin/env python3
"""
Generate the bring-up probe-point catalogue and its annotated board drawings.

Everything here is derived from dbcanary.kicad_pcb, so a probe point can never
drift away from the board: the table below names a designator and a pad, and
the coordinates, layer and net come out of the board file at run time. If a pad
is renamed or a part moves, this script fails loudly rather than printing a
stale coordinate into a document that someone then probes.

Outputs (all regenerated, none hand-edited):

    hardware/fab/test/PROBE-POINTS.json    machine-readable catalogue
    hardware/fab/test/PROBE-POINTS.csv     the same, for a test-record sheet
    docs/renders/probe-overview.svg        whole board, every point
    docs/renders/probe-power.svg           power corner
    docs/renders/probe-mcu.svg             MCU, LEDs, switches, debug header
    docs/renders/probe-ethernet.svg        W5500, magnetics, LAN jack
    docs/renders/probe-can.svg             isolated CAN domain

The board artwork inside each SVG is exported by `kicad-cli pcb export svg`,
which emits 1 mm : 1 user unit with the origin at the board outline's top-left
CENTRELINE corner (20.00, 19.00 in board coordinates). That mapping is asserted
at run time against a known pad, so a future KiCad release that changes it is
caught here instead of silently shifting every marker.

Run:  hardware/scripts/probe_points.py
"""
from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pcbnew

HERE = Path(__file__).resolve().parent
HW = HERE.parent
REPO = HW.parent
BOARD_FILE = HW / "dbcanary.kicad_pcb"
TEST_DIR = HW / "fab" / "test"
RENDER_DIR = REPO / "docs" / "renders"

# The SVG exporter puts the board outline's top-left CENTRELINE corner at the
# SVG origin, and sizes the page from the outline rather than from the plotted
# content (verified: F.Cu-only and F.Mask-only exports produce an identical
# viewBox). Both values are derived from the board file in calibrate() and then
# checked against the exporter's own viewBox, so this is never a magic number.
SVG_ORIGIN_X = 0.0
SVG_ORIGIN_Y = 0.0

# Nets that put a part on the isolated side of the ADM3053 barrier.
ISOLATED_NETS = {
    "CAN_GND", "VISO", "VISO_RAW", "CANH", "CANL",
    "CAN_RS", "TERM_A", "TERM_B", "TERM_MID",
}


@dataclass
class Probe:
    """One thing a person puts a probe on, and what they should see there."""

    pid: str            # P1, E3, C5 ... printed on the drawing
    pad: str            # "C107.1" - resolved against the board file
    net: str            # expected net name (asserted, not just documented)
    signal: str         # short human name
    instrument: str     # DMM-V | DMM-R | DMM-CONT | SCOPE | LA | VISUAL
    expect: str         # what a good board shows
    why: str            # what a failure here means
    group: str          # PWR | MCU | ETH | CAN
    confidence: str = "predicted"   # predicted | derived | spec
    # Badge offset from the pad, in units of ~2 badge radii. Hand-tuned, and
    # not always +/-1: the four SPI pins sit on 0.5 mm QFN pitch, so their
    # badges have to be fanned out or they merge into an unreadable blob.
    label_dir: tuple = (1, -1)
    x: float = 0.0
    y: float = 0.0
    side: str = "F"
    footprint: str = ""


# ---------------------------------------------------------------------------
# The catalogue.
#
# `expect` values are computed from the schematic where the arithmetic is ours
# (marked derived) and taken from a datasheet where it is the vendor's (spec).
# Anything marked `predicted` has never been measured on a board and is a
# starting hypothesis, not an acceptance limit. Do not tighten a predicted
# limit until at least three boards have been measured.
# ---------------------------------------------------------------------------
PROBES: list[Probe] = [
    # ---- Power ----------------------------------------------------------
    Probe("P1", "F101.1", "VBUS_RAW", "USB-C VBUS, before the PTC", "DMM-V",
          "4.75 - 5.25 V", "no volts here = cable, connector or source, not the board",
          "PWR", "spec", (-1, -1)),
    Probe("P2", "C107.1", "VCC_5V", "5 V rail, after the PTC", "DMM-V",
          "4.70 - 5.25 V; must be within 100 mV of P1 at idle",
          "a big P1-P2 gap means F101 is warm and current-limiting - look for a short",
          "PWR", "derived", (1, -1)),
    Probe("P3", "C301.1", "VCC_3V3", "3.3 V rail at the MCU", "DMM-V",
          "3.23 - 3.43 V (nominal 3.33 V)",
          "out of range = AP63200 feedback network or the buck itself",
          "PWR", "derived", (-1, 1)),
    Probe("P4", "U103.1", "FB2", "AP63200 feedback node", "DMM-V",
          "0.784 - 0.816 V (0.8 V reference)",
          "0.8 V here with a wrong P3 means R103/R104 are wrong or misplaced",
          "PWR", "spec", (1, 1)),
    Probe("P5", "C109.1", "PD_VDD", "CH224K supply, fed through R106 1k", "DMM-V",
          "3.3 - 5.1 V",
          "0 V = R106 open or U104 shorted; the exact value depends on CH224K Iq, which we have not measured",
          "PWR", "predicted", (1, -1)),
    Probe("P6", "U104.10", "PD_PG", "CH224K power-good to GPIO18", "DMM-V",
          "logic level, stable; note which level a good board shows",
          "the polarity is unverified - record it on board #1 and make that the limit",
          "PWR", "predicted", (1, 1)),
    Probe("P7", "U103.5", "SW2", "buck switching node", "SCOPE",
          "0 -> 5 V square, 500 kHz +/- 20 %, duty 62 - 72 %",
          "no switching = buck not enabled; wrong duty = wrong input or feedback",
          "PWR", "derived", (-1, 1)),
    Probe("P8", "C105.2", "BST2", "bootstrap cap, high side", "SCOPE",
          "SW2 waveform offset up by ~4.5 - 5 V",
          "flat = C105 open, and the high-side FET will not turn on properly",
          "PWR", "derived", (1, -1)),
    Probe("P9", "C107.2", "GND", "SYSTEM GROUND reference", "VISUAL",
          "clip every system-side ground lead here and nowhere else",
          "grounding to the CAN side defeats the isolation barrier under test",
          "PWR", "derived", (1, 1)),
    Probe("P10", "L102.2", "VCC_3V3", "3.3 V at the inductor output", "DMM-V",
          "same as P3 within 20 mV",
          "a difference means a resistive joint between the buck and the load",
          "PWR", "derived", (1, -1)),

    # ---- MCU ------------------------------------------------------------
    Probe("M1", "R301.2", "EN", "ESP32-S3 enable", "DMM-V",
          "3.23 - 3.43 V after ~10 ms",
          "stuck low = the S3 is held in reset; check R301, C304 and SW301",
          "MCU", "derived", (-1, -1)),
    Probe("M2", "J301.1", "VCC_3V3", "debug header pin 1", "DMM-V",
          "3.23 - 3.43 V",
          "the header is the fallback console when USB will not enumerate",
          "MCU", "derived", (1, -1)),
    Probe("M3", "J301.3", "UART0_TXD", "debug header pin 3, board -> host", "SCOPE",
          "idle high 3.3 V, 115200 baud bursts at reset",
          "silent at reset = the S3 is not running its ROM bootloader",
          "MCU", "derived", (1, 1)),
    Probe("M4", "U301.11", "PD_PG", "PD power-good at the MCU", "DMM-CONT",
          "continuous with P6",
          "open = the PD_PG track or a module pad joint",
          "MCU", "derived", (1, -1)),
    Probe("M5", "R305.1", "VCC_3V3", "D304 'ON' LED feed", "DMM-V",
          "3.23 - 3.43 V, and D304 lit",
          "rail present but D304 dark = LED fitted backwards or R305 open",
          "MCU", "derived", (-1, 1)),
    Probe("M6", "R302.1", "LED_LAN", "D301 drive from GPIO15", "DMM-V",
          "ACTIVE HIGH: ~3.3 V when lit, ~0 V when dark",
          "see the polarity note in BENCH-BRINGUP.md - the schematic is active high",
          "MCU", "derived", (-1, -1)),

    # ---- Ethernet -------------------------------------------------------
    Probe("E1", "C408.1", "ETH_1V2", "W5500 internal 1.2 V regulator", "DMM-V",
          "1.08 - 1.32 V",
          "0 V = W5500 unpowered or 1V2O shorted; the chip cannot work without it",
          "ETH", "spec", (-1, -1)),
    Probe("E2", "C409.1", "ETH_VBG", "W5500 bandgap decoupling", "DMM-V",
          "1.1 - 1.4 V",
          "informational; the datasheet does not publish a limit",
          "ETH", "predicted", (1, -1)),
    Probe("E3", "C410.1", "ETH_TOCAP", "W5500 TX driver reservoir", "DMM-V",
          "1.0 - 1.4 V",
          "informational; do not fail a board on this alone",
          "ETH", "predicted", (-1, 1)),
    Probe("E4", "R401.1", "ETH_EXRES", "W5500 bias resistor, 12.4k to GND", "DMM-R",
          "12.28 - 12.52 kohm, POWER OFF",
          "wrong value skews every analogue bias in the PHY - link may come up and still fail",
          "ETH", "spec", (1, 1)),
    Probe("E5", "R412.1", "ETH_XO_DRV", "25 MHz crystal driver, chip side", "SCOPE",
          "25.000 MHz +/- 250 Hz, roughly sinusoidal, 0.8 - 2.0 Vpp",
          "probe capacitance can stop the oscillator - only probe this if E1 or the VERSIONR read has already failed",
          "ETH", "derived", (-1, 1)),
    Probe("E6", "U401.32", "ETH_CSn", "W5500 chip select", "LA",
          "idle high, one low pulse per SPI transaction",
          "stuck low or stuck high = the SPI bus is dead in one direction",
          "ETH", "derived", (2.6, 3.0)),
    Probe("E7", "U401.33", "SPI_SCK", "SPI clock", "LA",
          "20 MHz +/- 5 % while CSn is low",
          "no clock = the S3 SPI peripheral or the track",
          "ETH", "derived", (2.6, 1.0)),
    Probe("E8", "U401.35", "SPI_MOSI", "SPI host -> W5500", "LA",
          "first transaction after reset is 00 39 00 - the VERSIONR address",
          "the address phase proves the driver is configured 16/8 bits",
          "ETH", "derived", (2.6, -3.0)),
    Probe("E9", "U401.34", "SPI_MISO", "SPI W5500 -> host", "LA",
          "0x04 in the 4th byte of that transaction",
          "0x00 or 0xFF = W5500 not answering: supply, crystal or reset",
          "ETH", "spec", (2.6, -1.0)),
    Probe("E10", "U401.37", "ETH_RSTn", "W5500 reset, from GPIO9", "DMM-V",
          "3.23 - 3.43 V once firmware has run",
          "low = held in reset, and every SPI read returns 0x00",
          "ETH", "derived", (-1, -1)),
    Probe("E11", "R410.2", "ETH_TCT", "transmit centre tap, PHY side of R410 10R", "DMM-V",
          "20 - 120 mV BELOW the 3V3 rail with the link up; equal to it with no link",
          "no drop across R410 with a link means the PHY transmitter is not driving",
          "ETH", "derived", (1, -1)),
    Probe("E12", "C411.1", "BOB_SMITH", "Bob Smith termination node", "DMM-V",
          "under 0.5 V DC referenced to GND",
          "volts here means something is feeding the spare pairs - suspect a PoE port",
          "ETH", "derived", (-1, 1)),

    # ---- Isolated CAN ---------------------------------------------------
    Probe("K1", "C204.1", "VISO_RAW", "ADM3053 isoPower output", "DMM-V",
          "4.5 - 5.5 V, measured to CAN_GND (K3), NOT to GND",
          "0 V = the isolated DC-DC has not started; nothing on the CAN side can work",
          "CAN", "spec", (-1, -1)),
    Probe("K2", "C206.1", "VISO", "isolated 5 V after FB201", "DMM-V",
          "within 100 mV of K1",
          "a gap across FB201 means it is drawing far more than expected",
          "CAN", "derived", (1, -1)),
    Probe("K3", "C206.2", "CAN_GND", "ISOLATED GROUND reference", "VISUAL",
          "every CAN-side lead clips here; NEVER share a clip with P9",
          "one shared clip and the isolation test passes on a board that is not isolated",
          "CAN", "derived", (1, 1)),
    Probe("K4", "R201.1", "CAN_RS", "ADM3053 slope control", "DMM-V",
          "under 0.3 V to CAN_GND - R201 is 0R, so high-speed mode",
          "volts here = R201 missing, and the transceiver drops to standby",
          "CAN", "spec", (1, -1)),
    Probe("K5", "J201.4", "CANH", "bus high, at CAN jack A (pin 4)", "DMM-V",
          "idle 2.3 - 2.7 V to CAN_GND; K5-K6 reads 118-130 ohm with SW201 IN, "
          "over 10 kohm with it OUT",
          "0 V or 5 V = the transceiver is stuck dominant, which jams the whole bus",
          "CAN", "spec", (-1, -1)),
    Probe("K6", "J201.5", "CANL", "bus low, at CAN jack A (pin 5)", "DMM-V",
          "idle 2.3 - 2.7 V to CAN_GND, within 100 mV of K5",
          "the K5-K6 resistance also tells a CAN jack from the LAN jack when the "
          "silkscreen is unreadable: only J201/J202 show 124 ohm",
          "CAN", "spec", (1, 1)),
    Probe("K7", "R202.2", "TERM_A", "SW201 pole A", "DMM-R",
          "K7 to K8: under 1 ohm with SW201 IN, open with it OUT",
          "measuring across the switch rather than the whole network separates a "
          "bad switch from a bad 62R resistor",
          "CAN", "derived", (-1, -1)),
    Probe("K8", "R203.1", "TERM_B", "SW201 pole B", "DMM-R",
          "see K7 - both poles must make; one pole alone leaves 62 ohm, not 124",
          "SW201 is a DPST: pads 1-2 and 3-4 both land on TERM_MID, and C207 hangs "
          "off the midpoint",
          "CAN", "derived", (1, 1)),
    Probe("K9", "U201.8", "VCC_5V", "ADM3053 VDD1, system side", "DMM-V",
          "4.70 - 5.25 V to GND",
          "the isolated DC-DC is fed from 5 V, not 3.3 V - a common mis-wire",
          "CAN", "derived", (1, -1)),
    Probe("K10", "U201.6", "VCC_3V3", "ADM3053 VIO, logic side", "DMM-V",
          "3.23 - 3.43 V to GND",
          "VIO sets the logic level the S3 sees; 5 V here would damage the S3",
          "CAN", "derived", (1, 1)),
]


# ---------------------------------------------------------------------------
# Board resolution
# ---------------------------------------------------------------------------
def load_board():
    if not BOARD_FILE.exists():
        sys.exit(f"board not found: {BOARD_FILE}")
    return pcbnew.LoadBoard(str(BOARD_FILE))


def index_pads(board):
    """{'C107.1': pad} for every pad on the board."""
    out = {}
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        for pad in fp.Pads():
            out[f"{ref}.{pad.GetPadName()}"] = (fp, pad)
    return out


def resolve(board):
    """Fill in coordinates, and fail if the catalogue and the board disagree."""
    pads = index_pads(board)
    tomm = pcbnew.ToMM
    errors = []
    for p in PROBES:
        hit = pads.get(p.pad)
        if hit is None:
            errors.append(f"{p.pid}: no pad {p.pad} on the board")
            continue
        fp, pad = hit
        net = pad.GetNetname().split("/")[-1]
        if net != p.net:
            errors.append(f"{p.pid}: {p.pad} is on net {net!r}, catalogue says {p.net!r}")
        pos = pad.GetPosition()
        p.x = round(tomm(pos.x), 3)
        p.y = round(tomm(pos.y), 3)
        p.side = "B" if fp.IsFlipped() else "F"
        p.footprint = fp.GetFPIDAsString()
    if errors:
        sys.exit("probe catalogue does not match the board:\n  " + "\n  ".join(errors))
    return pads


def isolated_extent(board):
    """Bounding box of the parts that are WHOLLY on the isolated side.

    U201 straddles the barrier by definition - it is the barrier - so shading a
    box that includes it would imply its system-side pins are isolated, which
    is exactly the misunderstanding that scraps boards. Straddlers are excluded
    from the shaded region and returned separately.
    """
    tomm = pcbnew.ToMM
    xs, ys = [], []
    refs, straddlers = [], []
    for fp in board.GetFootprints():
        # `unconnected-(J201-Pad1)` is not the system domain, it is nothing at
        # all. Counting those as system-side made the CAN jacks look like
        # straddlers and left CANH/CANL outside the shaded region - the exact
        # opposite of what a person probing needs to be told.
        nets = {pad.GetNetname().split("/")[-1] for pad in fp.Pads()}
        nets = {n for n in nets if n and not n.startswith("unconnected-")}
        if not (nets & ISOLATED_NETS):
            continue
        if nets - ISOLATED_NETS:            # also touches the system side
            straddlers.append(fp.GetReference())
            continue
        bb = fp.GetBoundingBox(False, False)
        xs += [tomm(bb.GetX()), tomm(bb.GetRight())]
        ys += [tomm(bb.GetY()), tomm(bb.GetBottom())]
        refs.append(fp.GetReference())
    return (min(xs), min(ys), max(xs), max(ys)), sorted(refs), sorted(straddlers)


def calibrate(board) -> tuple:
    """Set the board-mm -> SVG-unit origin from the board outline itself.

    The outline is drawn with a finite line width, so its bounding box is half
    a line width larger than the outline on every side. kicad-cli plots to the
    centreline. Returns the page size the exporter should therefore report.
    """
    global SVG_ORIGIN_X, SVG_ORIGIN_Y
    tomm = pcbnew.ToMM
    edges = [d for d in board.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts]
    if not edges:
        sys.exit("board has no Edge.Cuts geometry")
    widths = {round(tomm(d.GetWidth()), 4) for d in edges}
    if len(widths) != 1:
        sys.exit(f"Edge.Cuts uses mixed line widths {sorted(widths)} - "
                 "the SVG origin cannot be derived unambiguously")
    half = widths.pop() / 2.0
    bb = board.GetBoardEdgesBoundingBox()
    SVG_ORIGIN_X = round(tomm(bb.GetX()) + half, 4)
    SVG_ORIGIN_Y = round(tomm(bb.GetY()) + half, 4)
    return (round(tomm(bb.GetWidth()) - half * 2, 4),
            round(tomm(bb.GetHeight()) - half * 2, 4))


# ---------------------------------------------------------------------------
# Board artwork
# ---------------------------------------------------------------------------
def export_artwork(tmpdir: Path, expect_w: float, expect_h: float) -> str:
    """Plot the front of the board to SVG and return its <g> contents.

    F.Mask, not F.Cu: the solder-mask openings are exactly the metal a probe
    tip can physically touch. Plotting the copper instead fills the drawing
    with the ground pour and hides the very pads the reader is looking for.
    """
    out = tmpdir / "front.svg"
    cli = shutil.which("kicad-cli")
    if cli is None:
        sys.exit("kicad-cli not on PATH - install KiCad's CLI to regenerate the drawings")
    subprocess.run(
        [cli, "pcb", "export", "svg", "--mode-single", "--page-size-mode", "2",
         "--exclude-drawing-sheet", "--drill-shape-opt", "2", "--black-and-white",
         "--layers", "F.Mask,F.Silkscreen,Edge.Cuts",
         "-o", str(out), str(BOARD_FILE)],
        check=True, capture_output=True,
    )
    svg = out.read_text()

    # Check the exporter's own page against the outline we calibrated from.
    # A future KiCad that changes the page rule shifts every marker silently;
    # this turns that into a build failure.
    m = re.search(r'viewBox="([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+)"', svg)
    if not m:
        sys.exit("kicad-cli SVG has no viewBox - cannot verify the coordinate mapping")
    vw, vh = float(m.group(3)), float(m.group(4))
    if abs(vw - expect_w) > 0.1 or abs(vh - expect_h) > 0.1:
        sys.exit(f"kicad-cli SVG page is {vw:.4f} x {vh:.4f} mm, expected "
                 f"{expect_w:.4f} x {expect_h:.4f} from the board outline. "
                 f"The origin rule has changed - recalibrate before trusting any marker.")

    return svg[svg.index("<g "):svg.rindex("</g>") + 4]


def to_svg(x: float, y: float) -> tuple:
    return round(x - SVG_ORIGIN_X, 3), round(y - SVG_ORIGIN_Y, 3)


GROUP_COLOUR = {
    "PWR": "#d94f2b",
    "MCU": "#2f6fb0",
    "ETH": "#1f8a4c",
    "CAN": "#8b3fb5",
}
INSTRUMENT_NOTE = {
    "DMM-V": "DC volts",
    "DMM-R": "resistance, power OFF",
    "DMM-CONT": "continuity",
    "SCOPE": "oscilloscope",
    "LA": "logic analyser",
    "VISUAL": "ground reference",
}


def badge(p: Probe, r: float, font: float) -> str:
    x, y = to_svg(p.x, p.y)
    dx, dy = p.label_dir
    ox, oy = x + dx * r * 2.1, y + dy * r * 2.1
    c = GROUP_COLOUR[p.group]
    return (
        f'<g>'
        f'<line x1="{x:.2f}" y1="{y:.2f}" x2="{ox:.2f}" y2="{oy:.2f}" '
        f'stroke="{c}" stroke-width="{r * 0.16:.3f}"/>'
        f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r * 0.42:.2f}" fill="none" '
        f'stroke="{c}" stroke-width="{r * 0.22:.3f}"/>'
        f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r * 0.10:.2f}" fill="{c}"/>'
        f'<circle cx="{ox:.2f}" cy="{oy:.2f}" r="{r:.2f}" fill="{c}" '
        f'stroke="#ffffff" stroke-width="{r * 0.16:.3f}"/>'
        f'<text x="{ox:.2f}" y="{oy + font * 0.35:.2f}" font-size="{font:.2f}" '
        f'font-family="DejaVu Sans, Helvetica, Arial, sans-serif" font-weight="bold" '
        f'fill="#ffffff" text-anchor="middle">{p.pid}</text>'
        f'</g>'
    )


FONT = "DejaVu Sans, Helvetica, Arial, sans-serif"


def build_svg(title: str, subtitle: str, artwork: str, probes: list[Probe],
              view: tuple, iso_box, scale: float, ident: str) -> str:
    """One annotated drawing: board artwork, badges, and a numbered key.

    All geometry is in board millimetres translated into the exporter's SVG
    space, so a marker and the copper underneath it can never disagree. The key
    is laid out below the artwork in the same units.
    """
    vx0, vy0, vx1, vy1 = view
    ax0, ay0 = to_svg(vx0, vy0)          # artwork window, SVG units
    ax1, ay1 = to_svg(vx1, vy1)
    w, h = ax1 - ax0, ay1 - ay0

    r = max(0.9, w / 46)                 # badge radius
    font = r * 1.0
    row_h = max(3.2, w / 22)             # one key row
    margin = w / 22

    x0 = ax0 - margin                    # page origin
    y0 = ay0 - margin
    page_w = w + margin * 2
    key_top = ay1 + margin * 0.9
    page_h = (key_top - y0) + row_h * 2.7 + len(probes) * row_h + margin

    # Isolated-domain wash, clipped with the artwork.
    ix0, iy0, ix1, iy1 = iso_box
    iso = ""
    if ix0 < vx1 and ix1 > vx0 and iy0 < vy1 and iy1 > vy0:
        bx0, by0 = to_svg(ix0 - 1.2, iy0 - 1.2)
        bx1, by1 = to_svg(ix1 + 1.2, iy1 + 1.2)
        iso = (
            f'<g clip-path="url(#win-{ident})">'
            f'<rect x="{bx0:.2f}" y="{by0:.2f}" width="{bx1 - bx0:.2f}" '
            f'height="{by1 - by0:.2f}" fill="#8b3fb5" fill-opacity="0.06" '
            f'stroke="#8b3fb5" stroke-width="{r * 0.12:.3f}" '
            f'stroke-dasharray="{r * 0.55:.2f} {r * 0.45:.2f}"/>'
            f'<text x="{bx0 + 0.6:.2f}" y="{by0 - 0.8:.2f}" font-size="{font * 0.95:.2f}" '
            f'font-family="{FONT}" fill="#8b3fb5" font-weight="bold">'
            f'ISOLATED CAN DOMAIN &#8212; reference to CAN_GND (K3), never to GND</text>'
            f'</g>'
        )

    badges = "\n".join(badge(p, r, font) for p in probes)

    rows = []
    ty = key_top + row_h * 2.7
    for p in probes:
        c = GROUP_COLOUR[p.group]
        conf = "" if p.confidence != "predicted" else "  [predicted, never measured]"
        rows.append(
            f'<circle cx="{x0 + margin + row_h * 0.36:.2f}" cy="{ty - row_h * 0.30:.2f}" '
            f'r="{row_h * 0.36:.2f}" fill="{c}"/>'
            f'<text x="{x0 + margin + row_h * 0.36:.2f}" y="{ty - row_h * 0.30 + row_h * 0.135:.2f}" '
            f'font-size="{row_h * 0.36:.2f}" font-family="{FONT}" font-weight="bold" '
            f'fill="#ffffff" text-anchor="middle">{p.pid}</text>'
            f'<text x="{x0 + margin + row_h * 1.0:.2f}" y="{ty - row_h * 0.36:.2f}" '
            f'font-size="{row_h * 0.36:.2f}" font-family="{FONT}" fill="#111111">'
            f'<tspan font-weight="bold">{p.pad}</tspan>'
            f'<tspan fill="#666666">  {p.net} &#8212; {_esc(p.signal)}</tspan></text>'
            f'<text x="{x0 + margin + row_h * 1.0:.2f}" y="{ty + row_h * 0.08:.2f}" '
            f'font-size="{row_h * 0.31:.2f}" font-family="{FONT}" fill="{c}">'
            f'{INSTRUMENT_NOTE[p.instrument]}: {_esc(p.expect)}{conf}</text>'
        )
        ty += row_h

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{round(page_w * scale)}" height="{round(page_h * scale)}"
     viewBox="{x0:.3f} {y0:.3f} {page_w:.3f} {page_h:.3f}">
  <title>{_esc(title)}</title>
  <desc>{_esc(subtitle)}</desc>
  <defs>
    <clipPath id="win-{ident}">
      <rect x="{ax0:.3f}" y="{ay0:.3f}" width="{w:.3f}" height="{h:.3f}"/>
    </clipPath>
  </defs>
  <rect x="{x0:.3f}" y="{y0:.3f}" width="{page_w:.3f}" height="{page_h:.3f}" fill="#ffffff"/>
  <g clip-path="url(#win-{ident})" opacity="0.30">
{artwork}
  </g>
  <rect x="{ax0:.3f}" y="{ay0:.3f}" width="{w:.3f}" height="{h:.3f}" fill="none"
        stroke="#dddddd" stroke-width="{r * 0.09:.3f}"/>
{iso}
{badges}
  <text x="{x0 + margin:.2f}" y="{key_top + row_h * 0.75:.2f}" font-size="{row_h * 0.46:.2f}"
        font-family="{FONT}" font-weight="bold" fill="#111111">{_esc(title)}</text>
  <text x="{x0 + margin:.2f}" y="{key_top + row_h * 1.35:.2f}" font-size="{row_h * 0.32:.2f}"
        font-family="{FONT}" fill="#777777">{_esc(subtitle)}</text>
  <text x="{x0 + margin:.2f}" y="{key_top + row_h * 1.85:.2f}" font-size="{row_h * 0.30:.2f}"
        font-family="{FONT}" fill="#999999">Component side, viewed from above. Pads shown are solder-mask openings. Generated from dbcanary.kicad_pcb.</text>
{"".join(rows)}
</svg>
"""


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# Detail views are selected by GEOMETRY, not by group: each drawing shows a
# region of the board and every probe point that physically falls in it. That
# is what someone holding a probe actually needs. The overview carries all of
# them, and a check below refuses to finish if any point is missing from every
# detail view.
VIEWS = [
    ("probe-overview", "dbCANary rev A - bring-up probe points",
     "Every probe point in the bench bring-up procedure.",
     (19.9, 18.9, 120.1, 100.1), 15),
    ("probe-power", "Power corner - USB-C, CH224K PD, AP63200 buck",
     "USB-C entry, PD sink and the 5 V / 3.3 V rails.",
     (93.0, 21.0, 121.0, 59.0), 30),
    ("probe-mcu", "MCU, status LEDs, switches, debug header",
     "ESP32-S3 module, EN network, LED column and J301.",
     (20.5, 21.0, 70.0, 62.0), 22),
    ("probe-ethernet", "Ethernet - W5500, magnetics, LAN jack J401",
     "W5500 supplies, crystal, SPI bus and the magnetics.",
     (68.0, 48.0, 113.0, 96.0), 26),
    ("probe-can", "Isolated CAN - ADM3053, termination, CAN jacks",
     "The isolated domain. Reference every measurement here to CAN_GND.",
     (25.0, 62.0, 70.0, 99.0), 26),
]


def main() -> None:
    board = load_board()
    resolve(board)
    iso_box, iso_refs, straddlers = isolated_extent(board)

    TEST_DIR.mkdir(parents=True, exist_ok=True)
    RENDER_DIR.mkdir(parents=True, exist_ok=True)

    catalogue = {
        "board": "dbCANary rev A",
        "source": "hardware/dbcanary.kicad_pcb",
        "generated_by": "hardware/scripts/probe_points.py",
        "warning": "Values marked 'predicted' have never been measured on a board.",
        "isolated_domain_refs": iso_refs,
        "isolation_barrier_parts": straddlers,
        "probes": [
            {
                "id": p.pid, "pad": p.pad, "net": p.net, "signal": p.signal,
                "group": p.group, "instrument": p.instrument,
                "expect": p.expect, "failure_means": p.why,
                "confidence": p.confidence,
                "x_mm": p.x, "y_mm": p.y, "side": p.side, "footprint": p.footprint,
            }
            for p in PROBES
        ],
    }
    (TEST_DIR / "PROBE-POINTS.json").write_text(json.dumps(catalogue, indent=2) + "\n")

    with (TEST_DIR / "PROBE-POINTS.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "pad", "net", "signal", "group", "instrument",
                    "expect", "failure_means", "confidence", "x_mm", "y_mm", "side",
                    "measured", "pass_fail"])
        for p in PROBES:
            w.writerow([p.pid, p.pad, p.net, p.signal, p.group, p.instrument,
                        p.expect, p.why, p.confidence, p.x, p.y, p.side, "", ""])

    with tempfile.TemporaryDirectory() as td:
        artwork = export_artwork(Path(td), *calibrate(board))

    covered: set = set()
    for name, title, sub, view, scale in VIEWS:
        vx0, vy0, vx1, vy1 = view
        sel = [p for p in PROBES if vx0 <= p.x <= vx1 and vy0 <= p.y <= vy1]
        svg = build_svg(title, sub, artwork, sel, view, iso_box, scale, name)
        (RENDER_DIR / f"{name}.svg").write_text(svg)
        print(f"  {name}.svg  {len(sel)} points")
        if name != "probe-overview":
            covered |= {p.pid for p in sel}

    orphans = [p.pid for p in PROBES if p.pid not in covered]
    if orphans:
        sys.exit(f"no detail view contains {orphans} - widen a view box in VIEWS")

    print(f"\n{len(PROBES)} probe points -> {TEST_DIR}/PROBE-POINTS.{{json,csv}}")
    print(f"isolated domain: {len(iso_refs)} parts, "
          f"x {iso_box[0]:.1f}-{iso_box[2]:.1f} mm, y {iso_box[1]:.1f}-{iso_box[3]:.1f} mm")
    print(f"barrier parts (in both domains): {', '.join(straddlers)}")


if __name__ == "__main__":
    main()
