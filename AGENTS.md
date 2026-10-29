# AGENTS.md — bringing an LLM up to speed on CANary

Orientation for an AI assistant (or a new human) picking this project up cold. There is no
`CLAUDE.md` here; this is the entry point.

---

## 1. What this is

An open **IP-to-CAN converter compatible with the d&b audiotechnik R70** Ethernet-to-CAN
interface's protocol, so **d&b's R1 software can control d&b amplifiers (D6, D12, E-PAC) over a network
through hardware you can build yourself**.

Scope is a **transparent bridge** — exactly what the R70 is. It is not a control surface and
should not grow into one.

That rule is about *amplifiers*, and it still holds: nothing here interprets dbCAN. It does not
forbid configuring the converter itself, which `components/webui` now does — but note where
that UI lives. It is reachable over the USB cable only, and does not listen at all unless a
host is attached, precisely so the promise above stays true **on the show network**. Anything
that would move a control surface onto the LAN jack is a different decision and needs making
deliberately.

Target hardware: **ESP32-S3 + W5500 Ethernet + ADM3053 isolated CAN**, USB-C PD powered (PoE
deferred to rev B). Public repo.

## 2. The single most important status fact

**It runs on one board, and has been on a real CAN bus for one afternoon.** Rev A boards were fabricated and assembled turnkey from commit `d9a725d` (before the final USB-C re-route, which board #1 proved survivable). Board #1 passes its self-test 6/6, took a DHCP lease on a live switch, passes the 19-check host-side acceptance run over Ethernet and over USB, and is discovered and listed by R1. On 2026-10-28, with two d&b amplifiers on its CAN jacks, both answered through the isolation barrier and the control application drove them through the board in both directions (bring-up log §12). **Still unproven:** recovery after a CAN cable pull (it failed on 10-28: the CAN side stayed deaf until reset; a fix exists in development firmware, not in this repository, and has not been re-run on a board), LAN pulls, amplifier power cycles and long runs, the skipped bench-supply and isolation measurements, and the LED/PD-pin eyeball checks. Record: [`hardware/fab/test/BRINGUP-LOG-0001.md`](hardware/fab/test/BRINGUP-LOG-0001.md).

Before any board existed it had already executed *somewhere*, and that changed what we knew:

- `firmware/hostsim` links the shipping C into a host process on real sockets, so the
  bridge, codec and CAN return path run as an assembled whole rather than as unit tests.
- `firmware/qemu` boots the real `canary.bin` on an emulated ESP32-S3, which exercises
  the bootloader, partition table and `app_main` bring-up.

Between them those found three real firmware bugs and one remotely triggerable parser
overflow — see §9. One board is not a batch: treat timing, recovery and anything the
bring-up log does not record as unproven on silicon, and say so in any summary you write.

## 3. What *is* solved, and how solidly

- **The protocol is solved and verified against real R1** (V3.46). It discovers the
  emulator, lists it, connects on TCP 30000 and drives the bus.
- **The R70 is a rebadged RM Michaelides gateway** speaking the *public* "RM Byte Command
  Protocol": TCP 30000, UDP 33333 discovery, framing `0x43 / len / cmd / XOR / 0x0D`.
- **dbCAN** is 100 kbit/s, 11-bit CAN, with the ID packed as `class | subnet | device`.
- The **UDP 33333 discovery handshake** is documented from captures of R1's discovery
  traffic and confirmed live.
- **The codec is pinned to the vendor document, not to our reading of it** — the tests
  include both worked examples from the spec, checksums and all, plus a byte-exact capture of
  R1 scanning. The C firmware and the Python tooling are checked against *the same vectors*.

That last point is the design principle worth preserving: when you extend the protocol code,
add vectors from the document or from a real capture. Do not write a test that encodes your
own assumption and then verify the implementation against it.

## 4. Layout

```
docs/PROTOCOL.md     The protocol, as recovered. Start here for wire-format work.
docs/DECISIONS.md    Why things are the way they are
docs/SOURCES.md      Provenance of protocol knowledge
docs/FAB.md, LAYOUT.md, REVIEW-ethernet.md   Hardware
docs/renders/        Probe-point renders for bench work

firmware/            ESP-IDF project, target esp32s3
  components/rmbcp/      RM Byte Command Protocol codec
  components/r70_ddt/    R70 device/data table emulation
  components/dbcan/      dbCAN addressing
  components/bridge/     The actual IP<->CAN bridging
  components/net/        W5500 over SPI (Wi-Fi STA retained as a build option)
  components/usbnet/     USB network device (CDC-NCM) — build overlay, see docs/USB-NIC.md
  components/config/     Settings in NVS; cfg_validate() is pure and host-tested
  components/webui/      Configuration UI, bound to the USB link — see docs/WEBUI.md
  components/board/      Pin map — the single source of board truth
  components/led/        Status LED patterns

tools/rmbcp.py       Protocol codec (21 tests, incl. both vendor worked examples)
tools/r70_emu.py     Host-side R70 emulator — this is what R1 was tested against
```

`components/board` is the pin-map authority. Don't scatter pin numbers into other
components.

## 5. Build and test

```bash
# ESP-IDF v5.5.5, installed at ~/esp/esp-idf
. ~/esp/esp-idf/export.sh
idf.py set-target esp32s3
idf.py build
```

**Two environment traps:**

1. **Prepend python@3.12 to PATH.** The system `python3` is 3.14, which ESP-IDF does not
   support.
2. **Use ESP-IDF v5.x, not v6.x** — v6 moved/removed `driver/twai.h`.

Everything that runs without hardware, in one command:

```bash
./run_tests.sh          # units + the hostsim integration suite + a short fuzz
```

Individually:

```bash
firmware/components/*/test/run_tests.sh   # unit tests, plain cc, no deps
firmware/hostsim/test/run_tests.sh        # the bridge on real sockets, + soak
firmware/hostsim/fuzz/run_fuzz.sh --iterations 2000000
firmware/qemu/run_qemu.sh --check         # boot the real image
```

`SKIP_HOSTSIM=1` drops the integration suite; `FUZZ_ITERATIONS=0` keeps it without fuzzing.

739 firmware host checks and 57 Python tests pass, the integration suite is 20/20, and the
firmware compiles warning-free under `-Werror` from clean. Keep all of those true.

## 6. Hardware notes that will bite you

- **The status LEDs are active HIGH, not active LOW.** This was found during test-rig work
  and contradicts the obvious assumption.
- Rev A is 100 × 81 mm, 4-layer: ESP32-S3-WROOM-1-N8, W5500 with discrete magnetics into a
  Neutrik etherCON, ADM3053 isolated CAN on two more etherCONs, USB-C PD (CH224K) → AP63200
  buck.
- DRC is clean — **0 errors, 0 unconnected items** (31 accepted silkscreen warnings, and
  56 footprint-parity warnings that are unused IC pins plus a leftover `Verified` field on
  R106/R107); the 7.0 mm isolation barrier and 2.03 mm chassis moat were verified against
  the *poured copper*, not just the schematic.
- BOM: **45 of 50 vendor lines carry a live-verified LCSC part**; the other 5 are the
  hand-soldered connectors (`J201`, `J202`, `J401`, `J301`, `SW201`), which must be marked
  **Do Not Place**. Fab outputs are in `hardware/fab/`, one folder per fab house.
- **USB_DP/USB_DM were re-routed as a real differential pair on 2026-08-22.** They
  had been two single-ended traces 9.5 mm apart with 16 mm of length mismatch;
  DRC was clean throughout and could not see it. Both nets also carried exact
  duplicate stacked segments, which silently inflate any length measured off the
  board — **nothing else here has been swept for that**. See
  `hardware/scripts/route_usb_pair.py`.
- **Rev A is built and board #1 works** (see §2), but only one board of the batch has
  been exercised, and it was built one commit before the current fab files.
  If you change the board, regenerate *every* fab package — a stale package in one vendor
  folder is how a wrong board gets ordered.
- **Opening the USB console resets a product image**, even with DTR and RTS held low. If a
  fault test needs the log, attach the console before the fault, never after: that is how
  the 10-28 CAN-recovery fault lost its evidence (bring-up log §12).
- **`board_test.py`'s `rmbcp` stage transmits `0x123 55 AA` onto the CAN wire.** Skip it
  (`--skip console,rmbcp`) whenever a real amplifier is on the bus.
- A full **bench bring-up rig exists** — board self-test image, `board_test.py` (with a
  `--simulate` mode so it can be exercised without a board) and `BENCH-BRINGUP.md`, plus
  generated probe-point renders.

## 6a. Bugs found without hardware, and what they teach

All four were found in July 2026 by the two harnesses above. They are worth reading before
you trust anything else in this repo, because each one was invisible to the existing tests.

1. **`rmbcp_decoder_next` accepted `Length = 0`.** `len = length - 1` underflowed a `uint8_t`
   to 255, reading up to 259 bytes past the SOF — off the end of the 518-byte decode buffer
   when the SOF landed late — then `memcpy`ing 255 bytes into a 254-byte `data[]`, landing
   the last byte exactly on `out->len`. A peer therefore chose the length of the frame the
   bridge went on to handle. **TCP 30000 has no authentication.** Found by the fuzzer;
   regression vectors are in both `rmbcp` test suites.
2. **`main_task` overflowed its 3584-byte stack during bring-up.** Now 6144.
3. **`net.c` never called `gpio_install_isr_service()`** before installing the W5500 driver,
   which registers its handler on `int_gpio_num`. One error line, then a link that comes up
   and receives nothing.
4. **`diag_vprintf` held two 160-byte stack buffers** in the global `esp_log` hook, taxing
   every logging task's stack. Now one, sanitised in place.

Two lessons that generalise:

- **ASan is not enough on these structs.** `rmbcp_frame_t` is `{command; data[254]; len;}`,
  so a one-byte overrun of `data` lands on `len`, inside the same object, where ASan is
  blind. Assert the invariants explicitly.
- **A test that cannot fail proves nothing.** The first fuzz harness passed a planted
  off-by-one. It was fixed only because the negative control was run.

## 7. Not yet written

- **R60 emulation** — the same RM protocol over a USB *serial* port, rather than over IP.
  The R60 speaks the same RM Byte Command Protocol, so the codec is already there.
- PoE — deferred to rev B by design.

**The configuration UI is written, and on hardware it has only been seen serving its page** (to
a Mac over USB on board #1, 2026-09-26).
`components/webui` + `components/config` give the unit settings in NVS (host name, port,
socket count, static IP) and a page to set them, plus OTA firmware updates with rollback and
the diagnostics endpoints `diag.c` had been advertising to nobody. The page itself IS verified
— `components/webui/mock/mock_device.py` serves the real HTML so it can be driven in a browser
— but nothing past serving that page is recorded for `webui.c` on hardware. Read [docs/WEBUI.md](docs/WEBUI.md) §6.

**USB-NIC is written and proven on a macOS host** (2026-09-26; R1 over USB not yet tried). `components/usbnet` brings up
TinyUSB, CDC-NCM, its own netif and a DHCP server, so the unit appears to a laptop as a second
Ethernet adapter and R1 reaches it over the USB cable with the whole proven stack unchanged.
It is a build overlay (`sdkconfig.usb-ncm`), not the default image, because the S3 has ONE USB
PHY: installing TinyUSB takes it from USB_SERIAL_JTAG, so the USB-C port stops being the
console and the auto-reset programming port. Read [docs/USB-NIC.md](docs/USB-NIC.md) before
touching it — particularly §7, which lists exactly what is and is not proven.

## 8. Related projects

- **nanODE** — the sibling PoE ESP32 node this is built "in the spirit of"; shares hardware
  conventions and some tooling.
- **amp-commander** — split out of this project. Key finding from that work: **CAN is a d&b
  idiosyncrasy**; no other manufacturer uses it, so a universal amp bridge's axis is the
  *control protocol*, not the CAN dialect. Its KiCad project is a copy of CANary rev A
  (renamed), and CANary's own project was deliberately left untouched.

## Diagnostics

`firmware/components/diag` gives an in-RAM log ring tapped off `esp_log` (so every existing
`ESP_LOGx` call is captured with no component changes) plus an ELF coredump written to a
128K partition at `0x3C0000` — 256K of flash above `ota_1` was unused, so nothing had to be
resized. `esp_reset_reason()` is logged every boot: brownout, task watchdog and panic are
indistinguishable from outside a rack and have completely different causes.

Decode a dump with `esp-coredump` against **the .elf that was actually flashed**. The same
component and reasoning as nanODE — see that repo's `docs/DIAGNOSTICS.md` for the full
write-up, including why nothing is written to flash as a log.

Compile-verified against ESP-IDF v5.5.5 only; the crash path has never run on silicon.

## Notes

`docs/DECISIONS.md` carries the decisions already made and why. Read it before
changing anything non-obvious. Cross-cutting fleet knowledge lives in
[fleet-notes](https://github.com/stoatworks-labs/fleet-notes).
