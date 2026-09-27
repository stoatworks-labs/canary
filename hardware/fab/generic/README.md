# CANary rev A — generic / vendor-neutral package

The raw board data, in standard formats, with **no fab-specific conventions
applied**. Start here to quote a fab that has no folder of its own, or to build
a board by hand.

| File | What it is |
|---|---|
| `canary-gerbers.zip` | RS-274X gerbers + Excellon drill, the whole set |
| `gerbers/` | the same files loose, for browsing (not tracked in git) |
| `canary-bom.csv` | every part on the board, one line per orderable part |
| `canary-cpl.csv` | centroid — one line per designator, both sides |
| `canary-netlist.ipc` | IPC-D-356 netlist, for bare-board electrical test |
| `canary-ibom.html` | interactive BOM — open in a browser to hand-place |

## Board parameters

| | |
|---|---|
| Size | 100 × 81 mm |
| Layers | 4 (F.Cu, In1.Cu, In2.Cu, B.Cu) |
| Thickness | 1.6 mm |
| Placements | 76, all top side |
| Surface finish | **not specified in the stackup** — an open decision; ENIG suggested |

## Two things that will bite you if you convert this

**Rotations are KiCad-native and deliberately un-corrected.** Every assembly
house applies its own offsets to the standard centroid convention. The
`jlcpcb/` package has JLCPCB's corrections baked in by their plugin; this one
has none. Hand these angles to a fab that applies its own corrections and they
are right; hand them JLC-corrected angles and every part with a correction entry
goes on 180° out.

**Coordinates are absolute page coordinates with Y negated** (standard KiCad
centroid convention). No auxiliary/drill origin is set on this board, so the
gerbers use the same absolute frame and the two are consistent. If a fab wants a
bottom-left-corner origin, set the drill/place origin in KiCad and re-export the
gerbers **and** this CPL together — regenerating one without the other silently
desynchronises them.

## Reading the BOM

`Notes` carries the sourcing history, including PCB Train's UK substitutions
where the design's original part has no Western distribution. Where a line says
`PCB Train UK alternate: …`, either part is electrically correct — pick whichever
your distributor stocks, but read the note first: a few of the substitutions
change a stated spec (crystal stability, PPTC voltage rating) and are flagged
`DESIGNER TO CONFIRM`.

`LCSC` is populated for parts costed through LCSC/JLCPCB. It is a convenience,
not a preference.

## Regenerating

```bash
python3 hardware/scripts/fab_package.py hardware/canary.kicad_pcb
```
