# Changelog

## Unreleased (2026-09-27)

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
