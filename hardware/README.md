# CANary hardware

KiCad 10 project for the R70-compatible IP-to-CAN bridge.
Architecture and the reasoning behind every part choice: [../docs/DECISIONS.md](../docs/DECISIONS.md) (H1–H13).

## Status

| Sheet | File | State |
|---|---|---|
| Root | `canary.kicad_sch` | 4 sheets placed, CAN sheet pins linked |
| Power — PoE + USB-C, 5 V / 3V3 | `power.kicad_sch` | **drawn**, 15 symbols, 0 unconnected pins (U101 pending, see below) |
| MCU — ESP32-S3-WROOM-1, USB, LEDs | `mcu.kicad_sch` | **drawn**, 17 symbols, 0 unconnected pins |
| Ethernet — W5500 SPI, PoE tap, etherCON | `ethernet.kicad_sch` | **drawn**, 18 symbols, 0 unconnected pins |
| dbCAN — ADM3053 isolated | `can.kicad_sch` | **drawn**, 16 symbols, 0 unconnected pins |
| PCB | `canary.kicad_pcb` | **not started** |

**All four sheets are drawn** — 68 symbols, 0 unconnected pins on every sheet, and
the exported netlist confirms every cross-sheet bus connects. One part is still
missing (U101, see below).

**All 68 symbols have footprints assigned** — except that the three etherCON jacks
carry a deliberate placeholder (see below).

Nothing has been laid out, routed, DRC'd or fabricated.

> ### ⚠ etherCON footprint is a placeholder
> J201/J202/J401 use `Connector_RJ:RJ45_OST_PJ012-8P8CX_Vertical` so the netlist
> imports and layout can begin. **It is not an NE8FBH and must be replaced before
> fab.** KiCad ships no Neutrik etherCON footprint; it has to be drawn from the
> NE8FBH datasheet.
>
> Also note the variant correction: **NE8FDP cannot be used.** It is a panel-mount
> *feedthrough* whose rear is a female RJ45 socket — it does not solder to a PCB,
> and would need an internal patch lead per connector. NE8FBH is the horizontal
> PCB-mount part. See DECISIONS.md H6a.

## Architecture pivot (2026-07-23) — read this first

The MCU changed from **classic ESP32 + LAN8720 RMII** to **ESP32-S3 + W5500 SPI**,
and the barrel jack is gone. Full reasoning in `../docs/DECISIONS.md` H14–H18.

The trigger: the classic ESP32 has **no native USB peripheral**. It is UART-only,
so it physically cannot present as a USB network adapter or emulate an R60 — both
of which the S3 makes possible, while also deleting the USB-UART programming
bridge. The S3 has no EMAC, so RMII gives way to W5500-over-SPI; at dbCAN's
100 kbit/s that is ample, and it removes the 50 MHz oscillator and the
length-matched RMII group, previously the most EMC-critical things on the board.

Verified before committing to it, not assumed: `esp_eth_mac_w5500.c` ships in the
installed ESP-IDF v5.5.5, `tusb_ncm` is an official example listing ESP32-S3 as
supported, and the S3's `soc_caps.h` confirms TWAI and USB-OTG.

## ERC

**6 errors, all the same expected cause:** `power_pin_not_driven` on the rails,
because U101 is not placed and there are no `PWR_FLAG`/power symbols yet.

**Deliberately not silenced with PWR_FLAG.** Those flags would equally hide a
genuinely undriven rail. They should clear once U101 lands and the rails are
driven; if they don't, that is a real finding rather than a formality.

Warnings that remain are cosmetic: `same_local_global_label` where a local label
on a component pin shares a name with a global rail (connectivity is correct —
KiCad merges them), and `isolated_pin_label` on nets whose other end lives on the
still-empty Ethernet sheet (`SPI_*`, `ETH_*`, `POE_*`).

### A trap worth knowing

Deleting a component does **not** delete the net labels `batch_connect_to_net`
placed at its pins. Those orphans linger and ERC surfaces them one at a time, so
it looks like whack-a-mole. Worse, one of them was a genuine short: a leftover
`V5_DC` label from the deleted wide-Vin buck ended up co-located with `VBUS` on
the new USB OR diode, and ERC reported `multiple_net_names` — USB VBUS would have
been silently renamed to the old buck's output net. **After deleting parts, sweep
their pin coordinates for orphaned labels rather than trusting the delete.**

## What the Power sheet encodes

Two sources, OR'd by Schottky into `VCC_5V` — **no barrel jack**:

- **PoE** → Ag97005-FL (U101) → `POE_5V` → D104 → `VCC_5V`
- **USB-C** → `VBUS` → F101 (PTC) → D103 → `VCC_5V`

Both give 5 V directly, so there is no wide-Vin buck and no intermediate rail —
that whole chain (12 parts) was deleted in the pivot. `VCC_5V` feeds the ADM3053
and U103, the only remaining converter (5 V → 3V3).

**USB-PD is real**, not a passive sink: U104 is a **CH224K** negotiating over
CC1/CC2. It happens to be in KiCad's stock `Interface_USB` library, so no custom
symbol and no library-cache blocker.

> ### ⚠ CFG1 is safety-critical
> The CH224K picks its requested voltage from the CFG1/2/3 levels, and the
> datasheet warns it requests **20 V if CFG1 floats at power-up**. This board
> cannot survive that — 20 V would pass D103 straight onto `VCC_5V` and destroy
> the ADM3053 (VCC abs max ~6 V) and U103's input.
>
> CFG1 is therefore **hard-tied to `PD_VDD` in copper, not driven by an MCU GPIO**.
> It could not be a GPIO even in principle: the MCU is powered *from* this rail,
> so it cannot configure the PD chip before the rail it depends on exists.

The 5.1 k Rd pulldowns were removed — the CH224K drives CC itself, and fixed
resistors in parallel would present the wrong impedance and break PD signalling.
CH224K DP/DM are deliberately unconnected: they serve legacy BC1.2/QC, and wiring
them to the data pair would corrupt the USB link needed for NCM/R60/programming.

We request **5 V**, not a higher PD voltage, because 5 V feeds the ADM3053
directly — asking for 9 V or 12 V would reintroduce the wide-Vin buck H17 deleted.

Both bucks use the **adjustable** AP63200WU rather than the fixed AP63205/AP63203
variants: those are `extends` aliases that Konnect resolves to zero pins.

## What the Ethernet sheet encodes

**etherCON has no magnetics.** A Neutrik etherCON is a rugged *shell* around a
plain RJ45, so unlike the usual "HR911105A magjack" design the transformer must be
a separate part — T401 (PT61017PEL, 10/100 with centre taps). Chain: J401 →
T401 line side → T401 PHY side → W5500.

PoE is tapped here and powered on the Power sheet: **Mode A** from the T401 centre
taps, **Mode B** from J401 pins 4/5 and 7/8. All four go to U101's VINA–VIND,
whose internal bridge rectifiers make them polarity-insensitive — which is why
there is no external diode bridge and why both modes work without a jumper.

> ⚠ `POE_MODEA_*` and `POE_MODEB_*` sit at **up to 57 V** relative to GND. They are
> not logic nets. This is a **second** isolation concern, separate from the
> ADM3053 barrier on the dbCAN sheet, and it has its own project design rule.

`CHASSIS` is deliberately a separate net from `GND` (etherCON shell, USB-C shell,
Bob Smith termination, mounting hardware). **Choose the single GND↔CHASSIS bond
point at layout, and make it exactly one point.**

The W5500's four LED outputs are deliberately unused: the front-panel LAN LED is
MCU-driven (IO15) so firmware can show richer state than raw PHY activity.

## What the MCU sheet encodes

Pin assignment is recorded on the sheet itself, because firmware has to match it.
`IO9`–`IO18` carry the W5500 SPI bus, the LEDs and `PD_PG`: none of them are
strapping pins, so they are safe as outputs at reset. Avoided: `IO0`/`IO3`/`IO45`/
`IO46` (strapping), `IO26`–`IO32` (module's internal flash, not brought out), and
`IO35`–`IO37` (octal-PSRAM variants — leaving them free keeps a `-N8R8` module a
drop-in option). USB `D+`/`D-` are fixed in silicon at `IO20`/`IO19`.

**J301 is a recovery path, not a convenience.** Programming now runs over native
USB-CDC, so a USB stack that fails to enumerate would otherwise leave no way in.
J301 exposes UART0 + BOOT + EN so the ROM bootloader can always be reached over
serial.

## What the dbCAN sheet encodes

The protocol work drove real decisions here, not just documentation:

- **RJ45 pin 4 = CAN_H, pin 5 = CAN_L, shell = CAN ground** (d&b TI 312). The
  shell carries the bus ground, so the jacks must be shielded — this is why
  `Connector:8P8C_Shielded` is used rather than the plain `RJ45` symbol.
- **J201/J202 in parallel** so amplifiers daisy-chain, exactly as the R70 does.
- **Pins 1,2,3,6,7,8 unused** and explicitly flagged no-connect.
- **Split termination** (2×62 R + 4.7 nF to CAN_GND) on a **2-pole** switch. An
  SPST would leave an asymmetric 62 R + C stub on CANL when open. The real R70
  uses a plain switched 120 R; this is a deliberate EMC improvement.
- **CAN_GND is a separate net from GND** and must stay that way — the project
  design rules encode a full-stack copper keepout across the ADM3053 barrier.

## Gotchas found in this environment

- **`set_design_rules` corrupts the board — do not use it.** It writes
  `min_clearance` / `min_track_width` / `min_via_*` into the `.kicad_pcb` `(setup)`
  block, where they are not valid keys, and KiCad then refuses to open the file:
  *"Unexpected min_clearance ... line 32"*. Board design constraints belong in
  `.kicad_pro`, not `.kicad_pcb`. Set them in *Board Setup ▸ Design Rules* instead.
- **`add_layer` corrupts the stackup — do not use it.** Adding `In1.Cu`/`In2.Cu`
  produced nested entries inside `F.Cu` with duplicate layer id `1`, leaving a board
  KiCad could not read (`get_layer_list` returned 0). Reverted from git. Set the
  layer count in KiCad's *Board Setup ▸ Physical Stackup* instead.
- **There is no schematic→PCB sync.** Konnect exposes none, and `kicad-cli pcb
  import` only converts foreign PCB formats. Use *Tools ▸ Update PCB from Schematic*
  (F8) in the PCB editor.
- **`register_symbol_library` with `scope: "project"` writes a broken file** — root
  node `(fp_lib_table` in `sym-lib-table`. It silently breaks `list_symbol_libraries`.
  Register globally.

- **KiCad 10 uses a nested library table.** The global `sym-lib-table` contains a
  single `(type "Table")` entry pointing at KiCad's stock template. Konnect does
  not follow that indirection, so `search_symbols` and `get_symbol_info` return
  nothing — but `add_schematic_component` resolves lib_ids fine. Find parts by
  grepping `/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols/*.kicad_sym`.
- **`Connector:RJ45` is an `extends "8P8C"` alias with no pins of its own**, and
  Konnect does not follow `extends`. Wiring to it silently connects nothing. Use
  base symbols; verify with `get_schematic_pin_locations` after placing.
- The ADM3053 symbol stacks all five GND1 pins at one coordinate, so bulk net
  connection produces five co-located labels. Cosmetic, but confusing to read.
- **`save_project_config` stringifies whatever you give it.** Passing a JSON array
  to `design_rules` stored a 1230-character *string*, which then iterated one
  character per "rule". Use `add_design_rule` instead — it appends properly and
  repairs the type.
- **Konnect caches the symbol library table at MCP-server startup.** A library
  created and registered mid-session cannot be resolved until Konnect restarts,
  and there is no rescan tool. This still blocks U101.
