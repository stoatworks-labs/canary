# dbCANary rev A — Electrical Test Coverage

Generated from the board file. Companion to `dbcanary.d356` (IPC-D-356A).

## Netlist summary

| | |
|---|---|
| Nets in netlist | **119** |
| Real nets (carry signal or power) | **65** |
| Deliberate no-connects | 54 |
| Total probe features on real nets | 505 |
| **Real nets with ≥2 probe points (continuity-testable)** | **65/65 — 100 %** |
| Real nets probeable from both sides | 19 |
| Real nets probeable from top only | 46 |

**Every real net can be continuity-tested.** No net depends on a single
inaccessible point. The 54 single-point entries are all
`unconnected-(...)` — pins deliberately left unconnected (spare ESP32-S3 GPIO,
W5500 LED outputs the design does not use, USB-C SBU pins, etherCON unused
contacts). They are shorts-testable but have nothing to be continuous *to*,
which is correct.

## Net name truncation — read this before loading the netlist

IPC-D-356A has a **fixed 14-character** net-name field. This board uses
hierarchical sheet names, so full net names are long:

    /Ethernet — W5500 SPI, PoE magjack, etherCON/ETH_CT_RD

is written into the netlist as the last 14 characters:

    HERCON/ETH_CT_RD  ->  truncated to fit

Two consequences:

1. **No collisions.** All 119 nets were checked: every truncated name is
   still unique, so the netlist is electrically correct and no two nets can be
   confused for one another.
2. **The names are unreadable, and 50 nets contain a non-ASCII em-dash** that
   is written as `?`. This is cosmetic. Use `NETLIST-CROSSREF.csv` to map any
   truncated name back to the real one.

## Domain spacing — for anyone planning an isolation test

Minimum copper-feature spacing measured between electrical domains:

| Between | Minimum | Note |
|---|---|---|
| System (GND/3V3/5V/VBUS) ↔ Isolated CAN | **8.50 mm** | the ADM3053 barrier |
| Isolated CAN ↔ CHASSIS | 6.15 mm | |
| System ↔ CHASSIS | **1.15 mm** | at J102's USB-C shell — normal for a USB shell |

**Hipot GND ↔ CAN_GND. Do not hipot GND ↔ CHASSIS** — it would flash over at
the USB-C connector, which is by design and proves nothing.

## Files

| File | What it is |
|---|---|
| `dbcanary-ODB++.zip` | what JLCPCB's PCBA flying-probe service asks for **if support agrees to run it** — it is a support-negotiated service with no published price, not a checkout option. Layers, drills, placement, and a CAD netlist with full untruncated net names |
| `dbcanary.d356` | IPC-D-356A netlist — the portable industry standard. JLCPCB has no netlist upload field, but **their own blog suggests including one in the Gerber ZIP**; PCBWay and most Western fabs require it |
| `NETLIST-CROSSREF.csv` | truncated D-356 name → full hierarchical net name, with probe counts per net |
| `FUNCTIONAL-TEST-SPEC.md` | functional test procedure (draft — never executed) |
| `README.md` | **start here** — which file goes to which service |

## Which format each service wants

| Service | File |
|---|---|
| JLCPCB bare-PCB flying probe | **none required** — CAM-extracted from the Gerbers. Only one option renders ("Flying Probe Fully Test") and it is already selected. Including `.d356` in the ZIP is optional and suggested by JLCPCB's own blog |
| JLCPCB PCBA flying probe | **ODB++** — but contact support first; it is not orderable from the form. PCBDOC is Altium-native and unavailable from KiCad |
| JLCPCB functional test (FCT) | a written procedure + photos, Standard PCBA only — **but confirm the service exists first, see README §0** |
| PCBWay / other fabs | IPC-D-356A (`.d356`) |

## Caveats

- No dedicated test points (`TP*`) exist on this board. All probing is on
  component pads and vias. Adding test points is on the rev B list.
- Coverage figures are computed from the board file, not from a test system's
  own analysis. The fab's CAM will do its own netlist extraction from the
  gerbers and that is the authority for what they actually test.
