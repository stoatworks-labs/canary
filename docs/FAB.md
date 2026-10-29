# CANary rev A — fabrication

Status: **routed, checked, and ready to upload.** DRC reports **0 errors and 0
unconnected items** (31 accepted silkscreen warnings). Every fab package was
regenerated from the routed board on 2026-08-04.

> Rev A boards were fabricated and assembled turnkey from commit `d9a725d` (before the final USB-C re-route, which board #1 proved survivable). Board #1 passes its self-test 6/6, took a DHCP lease on a live switch, passes the 19-check host-side acceptance run over Ethernet and over USB, and is discovered and listed by R1. On 2026-10-28 it carried the control application's traffic to two d&b amplifiers and back. **Still unproven:** recovery after a CAN cable pull (it failed on 10-28), LAN pulls, amplifier power cycles and long runs, the skipped bench-supply and isolation measurements, and the LED/PD-pin eyeball checks. Only board #1 has been touched. Record: [`hardware/fab/test/BRINGUP-LOG-0001.md`](../hardware/fab/test/BRINGUP-LOG-0001.md).
> The files here are regenerated from the routed board, i.e. one commit later than
> what was built.

## Where the files actually are

This document is background. The operational documents live next to the files:

| Document | What it is for |
|---|---|
| [`../hardware/fab/README.md`](../hardware/fab/README.md) | What is in each vendor folder, and why the BOMs deliberately differ |
| [`../hardware/fab/test/`](../hardware/fab/test/) | ODB++, IPC-D-356 netlist, probe points, functional test spec |
| [`LAYOUT.md`](LAYOUT.md) | The floorplan the board was placed to (historical — see its own correction note) |

Under `hardware/fab/`: a complete self-contained JLCPCB upload set in `jlcpcb/`,
plus a vendor-neutral `generic/`. Board parameters for an order form are in the
[board specification](#board-specification) below. (PCBWay and PCB Train sets, the
ordering checklist and the pre-fab review record were working files and are not
included in the public repo.)

## Board specification

Read from `hardware/canary.kicad_pcb`, not from memory.

| Item | Value |
|---|---|
| Outline | **100 × 81 mm** (Edge.Cuts X 20→120, Y 19→100), 2 mm corner radius |
| Layers | **4** (Sig / GND / PWR / Sig) |
| Thickness | 1.6 mm |
| Copper | 1 oz outer, 1 oz inner |
| Finish | **not set in the stackup — an open decision.** ENIG suggested |
| Min track / clearance | 0.200 / 0.150 mm |
| Min via | 0.60 mm pad / 0.30 mm drill |
| **Min hole** | **0.20 mm** — U301's module thermal vias, exactly at JLCPCB's limit. Do not let anyone shrink it |
| Placements | **76**, top side only |
| BOM | 50 vendor lines, **45 carrying a live-verified LCSC part**; 35 unique parts (18 basic, 17 extended) |
| Fab house | JLCPCB assumed; PCBWay and PCB Train packages also built |

Why 4 layers: the original justification (50 MHz RMII) disappeared with the W5500
pivot, and the 57 V PoE zone disappeared with rev A — so 2 layers is now arguable.
4 is still right: it gives the USB FS pair and the W5500 SPI bus a solid reference
plane, and keeps a continuous plane either side of the ADM3053 isolation barrier
rather than a chopped-up pour.

## Assembly notes

- **`J201` / `J202` / `J401` — Neutrik etherCON NE8FBH.** Through-hole,
  panel-mount, **customer-supplied** (not an LCSC part). Footprint is
  `canary:Neutrik_etherCON_NE8FBH`, drawn from Neutrik drawing 20003890 rev D.
  Its two Ø1.55 mm latch-post holes are **non-plated** — mechanical locating posts.
- **Five parts are hand-soldered, not machine-placed**: `J201`, `J202`, `J401`,
  `J301`, `SW201`. They appear in the BOM and CPL with no LCSC part so the two
  files stay in designator parity (76/76) — **mark them "Do Not Place"** at the
  vendor's review step.
- ⚠️ **One-off exception, the rev A PCBWay order: the etherCONs
  were fitted anyway.** The rule above still stands — we hand-fit `J201`/`J202`/
  `J401` ourselves on every future build. On this order PCBWay had already quoted,
  purchased and soldered **NE8FBH sourced from Digi-Key** before anyone read the
  "Do Not Place" note, which sat later in the BOM document than their review
  reached ("we may have overlooked the DNP note placed later in the document",
  2026-08-29). They were already paid for as part of the quotation, so they stayed
  on the boards rather than being removed — agreed 2026-08-30. **Next order, put
  the DNP note where the vendor cannot miss it**, not at the foot of the BOM.
- All previously unconfirmed LCSC numbers are now assigned and verified:
  `U104` CH224K **C970725**, `U301` ESP32-S3-WROOM-1-N8 **C2913198**,
  `U401` W5500 **C32843**, `T401` PT61017PEL **C124001**,
  `U201` ADM3053BRWZ **C117821**, `U103` AP63200WU **C2071868**.
- `C411` (1 nF, **C9196**) must be a genuine **2 kV** part: it bridges chassis to
  the cable side.
- **Do not substitute** `R401` (12.4 k 1 %, **C11692**) — it sets the W5500's
  internal bias current.
- Stock was re-verified live on 2026-08-04: every line builds ≥ 827 boards. Stock
  goes stale — re-run `hardware/scripts/check_lcsc_stock.py` before ordering.

## Critical, non-obvious constraints

These survive into rev B. Do not "clean them up".

1. **`CFG1` on `U104` is hard-tied to `PD_VDD` in copper.** If it floats at
   power-up the CH224K requests **20 V**, which would destroy the ADM3053
   (VCC abs max ~6 V). Never reroute this to a GPIO. See DECISIONS.md H18a.
2. **The ADM3053 isolation barrier is a full-stack keepout.** No copper on any
   layer may cross it, including pours and stitching vias. `CAN_GND` must stay
   galvanically separate from `GND`.
3. **`CHASSIS` is a separate net from `GND`** (etherCON shells, USB-C shell, Bob
   Smith termination, mounting hardware). It bonds to `GND` at exactly one point.
4. **`J102` (USB-C) sits at origin y 22.60, rotation 180.** This was wrong once
   already and cost a re-route. The mouth must be on the board edge at y 18.95
   with the tails at 26.64. Verify against footprint geometry, **never against
   the silkscreen** — the silk is open at −Y only because the SMD pads are there.
5. dbCAN is **100 kbit/s fixed**; RJ45 pin 4 = CAN_H, pin 5 = CAN_L, **shell =
   CAN ground**. Shielded connectors are mandatory (d&b TI 312).

## Regenerating the packages

```bash
python3 hardware/scripts/fab_package.py hardware/canary.kicad_pcb
```

That rebuilds `generic/` from scratch and **never** overwrites a vendor BOM or a
vendor-plugin-generated file that already exists. The JLCPCB and PCBWay packages
come from those vendors' own KiCad Fabrication Toolkit plugins — see
`hardware/scripts/run_vendor_toolkits.py`, whose docstring carries the exact
commands — and the PCB Train BOM from `hardware/scripts/make_pcbtrain_bom.py`.

Re-check the board yourself before any order with:

```bash
kicad-cli pcb drc --schematic-parity --severity-error --severity-warning hardware/canary.kicad_pcb
```

## Known-broken tooling

Both of Konnect's board-setup tools are **broken and must not be used**:
`add_layer` nests the inner layers inside `F.Cu` with duplicate layer IDs, and
`set_design_rules` writes `min_clearance` / `min_track_width` keys into the
`.kicad_pcb` `(setup)` block where they are not valid — KiCad then refuses to open
the board ("Unexpected min_clearance"). Board design constraints live in
`.kicad_pro`, not `.kicad_pcb`. Both attempts were reverted from git.

There is also no CLI path for *Update PCB from Schematic*: `kicad-cli pcb import`
only converts foreign PCB formats, and Konnect exposes no schematic→PCB sync. It
is **F8** in the GUI.
