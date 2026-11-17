# Changelog

## Unreleased

- **Rack plates for the tube** (`hardware/enclosure/rack/`, generator
  `gen_rack_3dp.py`): 2U panels whose slots are the tube's front plate, so a tube screws
  in with its own four M3 and the etherCONs' panel screws. A 19-inch panel for three
  units, in three pieces that bolt together through ribs (it will not fit a 320 mm bed in
  one), and a 10-inch panel for one unit, plus blanks. STEP, STL and two sliced Bambu Lab
  plates (`bambu/build.sh absgf-0.4-rack rack19` / `rack10`). The generator checks every
  slot against the front plate and the tube's fit before it writes anything.
  **Not printed yet.**
- **Two variants of one design.** The README now presents **CANary** (rev A), the simple
  board: USB-C PD powered, self-contained, made for the desktop tube case; and the
  **CANary Dev Edition** (rev B), with a table comparing them. Rev A is the one that has
  been built.
- **Hardware rev B, the CANary Dev Edition** (`hardware/rev-b/`, write-up `REV-B.md`): rev A
  plus a keyed 16-way front-panel header (J501: buffered LED sinks, RESET, BOOT, I2C, two
  spare GPIOs), DNP pads for CAN, the termination switch, USB data and a 5 V aux input,
  802.3af PoE (SDAPO DP9900M-5V) with a TPS2116 power mux giving it priority over USB-C,
  four M3 mounting holes, and the ESP32-S3-WROOM-1-N8R2 module (2 MB of PSRAM). KiCad
  project, generic and JLCPCB fab packages, and the scripts that generate the board from
  rev A's routed one. ERC 0 errors; DRC 0 errors and 0 unconnected items.
  **Never ordered, built or powered.**
- **Rack front-panel board** (`hardware/frontpanel/`): 84 × 26 mm, two layers, the four
  status LEDs and the RESET and BOOT buttons, on a 16-way ribbon from rev B's J501. Fab
  files and a panel drilling drawing. DRC clean with schematic parity. **Never ordered or
  built.**
- **Library:** `canary:SDAPO_DP9900M` footprint and `DP9900M-5V` symbol, for rev B's PoE
  module. The footprint is drawn from SDAPO's package drawing and has not been checked
  against a real module. Rev A's schematic and board files are unchanged.

## 0.2.0 — 2026-10-19

The changes below were made on 2026-09-27 and released as 0.2.0 on 2026-10-19.

- **Firmware `main-ff4110d`**, the first build under the CANary name, in the release as
  one zip (`canary-firmware-main-ff4110d.zip`): both variants with their flash offsets and
  SHA-256 checksums in a `manifest.json`, so tools that write the firmware themselves can
  fetch it. It's the build the [CANary Flasher](https://canary-flasher.stoatworks-labs.com)
  serves, byte for byte, and differs from 0.1.0's `main-60a871f` only in its names.
  **`main-ff4110d` hasn't been flashed onto a board yet**; the last build proven on one is
  still `main-60a871f`.
- **Renamed dbCANary → CANary** across the docs, firmware, tools, enclosure and KiCad
  project (files and footprint library nickname: `canary:`). The firmware's settings
  namespace keeps its old name, so a configured unit keeps its settings through an update.
  Dated records (the 0.1.0 entry below, the board #1 bring-up log and test record) keep the
  name they were written under.
- **Default name in R1 is now `CANary`**, instead of the R70 factory default `db-70`, so a
  unit is listed as what it is. It can still be changed from the settings page.
- **Flush switch cover.** The tube's lid has a 1.2 mm pocket over the service pinholes and
  the SW201 slot; the cover sits flush in it, with a lever notch at its front end for a
  small screwdriver. The new cover does not fit a 0.1.0 tube, nor the old cover the new one.
- **Internal bracing** in the tube: three hoop bands round the inside (45° undersides, no
  support) and four full-length ribs, clear of the board's path, the etherCONs, the USB-C
  well and the insert pilots. +6 g a case; the stiffness gain has not been measured.
- **Heat-set insert jig** (`hardware/enclosure/gen_insert_jig.py`, `hardware/enclosure/jig/`)
  for a common 3D-printed insert press: an index plate keyed to the press's base, a nest
  that holds the tube on end, and a keyed peg; one socket per insert. The tip's distance
  from the press walls is an estimate until measured on a built press.

## 0.1.0 — first public release (2026-09-26)

The prototype, published as it stands.

- **Hardware rev A.** KiCad project, library and fab outputs. Boards have been
  built; board #1 passes its self-test, runs the bridge over Ethernet and USB,
  and is discovered and listed by R1. CAN has not yet been on a real amplifier
  bus.
- **One-piece tube enclosure**, with its LED window insert and switch cover, as
  a parametric generator plus STEP, STL and sliced print plates.
- **Firmware `main-60a871f`**: Ethernet bridge (RM Byte Command Protocol on TCP
  30000, discovery on UDP 33333, dbCAN at 100 kbit/s), status LEDs, a bench
  self-test image, and the optional USB network device with its settings page.
  Also available from the [dbCANary Flasher](https://canary-flasher.stoatworks-labs.com).
- **Host tools**: Python reference implementation, an emulator you can point R1 at
  with no hardware, and the board acceptance test.
