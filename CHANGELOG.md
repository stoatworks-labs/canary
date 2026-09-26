# Changelog

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
  Also available from the [dbCANary Flasher](https://dbcanary-flasher.stoatworks-labs.com).
- **Host tools**: Python reference implementation, an emulator you can point R1 at
  with no hardware, and the board acceptance test.
