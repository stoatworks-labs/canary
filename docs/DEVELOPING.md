# dbCANary — Developing

Environment, build variants, tests, and the conventions that keep this project honest.

If you are an LLM picking this up cold, read [`AGENTS.md`](../AGENTS.md) first.

---

## 1. The design principle worth preserving

**Protocol code is pinned to primary sources, not to our reading of them.**

`tools/rmbcp.py` includes **both worked examples from the vendor spec**, checksums and all.
`tools/r70_ddt.py` and its C twin are checked against a **byte-exact capture of R1 V3.46
scanning**. The C firmware components and the Python tooling are verified against the *same
vectors*.

When you extend the protocol code, add vectors from the document or from a real capture. **Do
not write a test that encodes your own assumption and then verify the implementation against
it** — that produces a suite that passes and a bridge R1 won't talk to, which is precisely the
failure this project was built to avoid.

The same rule shapes the test tooling: a check may only report on what it actually examined.
`SKIP` exists so that "I didn't look" never renders as `PASS`.

---

## 2. Environment

### Firmware

ESP-IDF **v5.5.5**, at `~/esp/esp-idf`. Target `esp32s3`.

```bash
export PATH=/opt/homebrew/opt/python@3.12/libexec/bin:$PATH
. ~/esp/esp-idf/export.sh
cd firmware
idf.py set-target esp32s3
idf.py build
```

Two traps:

1. **`export.sh` keys its virtualenv off whichever `python3` is first on `PATH`.** Homebrew's
   `python@3.12/bin` contains only `python3.12`, so the script finds the system 3.14 — which
   ESP-IDF does not support — and fails with a confusing error. Use `libexec/bin`, which
   provides an unversioned `python3`.
2. **Use ESP-IDF v5.x, not v6.x.** v6 moved/removed `driver/twai.h`; the build breaks in
   dependencies rather than in this repo's code.

The firmware compiles **warning-free under `-Werror` from clean**. Keep it that way.

### Tests

```bash
python3 -m venv .venv && ./.venv/bin/pip install pytest
./run_tests.sh          # Python reference + every C firmware component
```

`run_tests.sh` runs `pytest tools/` then every `firmware/components/*/test/run_tests.sh`:
`rmbcp`, `r70_ddt`, `led`, `selftest`. The C suites build on the host — no ESP-IDF, no
hardware, sub-second.

The firmware's pure components are **deliberately ESP-IDF-free** so they can be compiled and
tested on a host. When adding logic, follow that: keep the protocol layer free of `esp_*`
calls and inject the I/O. Every host-tested component here earned its tests that way.

`tools/` is the reference implementation — it is the code actually proven against R1 — and the
C components carry the same vectors.

---

## 3. Build variants

Three, and the flags are **sticky**, which is the single most common way to waste an hour here.

| Variant | Command |
|---|---|
| Product (Ethernet) | `idf.py build` |
| Product (Wi-Fi, devkit only) | `idf.py build -DDBCANARY_USE_WIFI=1 -DDBCANARY_WIFI_SSID=… -DDBCANARY_WIFI_PASS=…` |
| Self-test image | `idf.py -B build-selftest build -DDBCANARY_SELFTEST=1` |

> **`idf.py -D` writes to the CMake cache.** A later plain `idf.py build` silently keeps
> building the variant you last selected. To go back you must say so explicitly:
> `idf.py -DDBCANARY_USE_WIFI=0 build`. Verify with
> `grep -c DBCANARY_USE_WIFI=1 build/compile_commands.json`.

The self-test image is built into a **separate build directory** (`-B build-selftest`) on
purpose: the shipping image must carry no command interface at all, and keeping the two trees
apart means you cannot flash the wrong one by forgetting a flag.

Wi-Fi is **not** a shipping path. It exists so the bridge can be exercised on a plain ESP32-S3
devkit before boards exist. On the real board the LAN jack is fed by the W5500 over SPI and the
S3 has no internal EMAC.

---

## 4. Layout

```
docs/      PROTOCOL.md   the full protocol reference — start here for wire-format work
           API.md        what the firmware actually answers; the tool CLIs
           USER-GUIDE.md operating a unit
           DECISIONS.md  ADR-style choices
           SOURCES.md    where to get the vendor manuals (not redistributed)
           FAB.md, LAYOUT.md, REVIEW-ethernet.md, ENCLOSURE.md
           renders/      probe-point renders for bench work

tools/     rmbcp.py        RMBCP codec + dbCAN ID helpers  ← reference implementation
           r70_ddt.py      UDP 33333 device detection
           dbcan_device.py stand-in amplifier (addressing only)
           r70_emu.py      host-side R70 emulator / prober
           board_test.py   board acceptance run; --simulate needs no hardware
           test_*.py

firmware/  components/rmbcp     protocol codec (C), host tests
           components/r70_ddt   discovery protocol (C), host tests
           components/dbcan     TWAI at dbCAN's fixed 100 kbit/s
           components/net       W5500 over SPI (Wi-Fi STA for devkits)
           components/bridge    discovery responder + TCP + CAN forwarding
           components/board     pin map — the single source of board truth
           components/led       status LED patterns (C), host tests
           components/selftest  board self-test + bench console (test build only)
           main/app_main.c      builds; never run on hardware
           main/status.c        maps link / lease / R1 / CAN state to the LEDs

hardware/  dbcanary.kicad_*  rev A, 4 sheets, 100 × 81 mm, 4-layer
           fab/              gerbers, drill, BOM, CPL per vendor
           fab/test/         BENCH-BRINGUP.md, FUNCTIONAL-TEST-SPEC.md,
                             PROBE-POINTS.{json,csv}, netlists
           scripts/          placement, routing, fab and probe-drawing tools
```

**`components/board` is the pin-map authority.** Don't scatter pin numbers into other
components — every other component takes its pins from `board.h`, and that is what makes a rev B
re-spin a one-file change.

---

## 5. Extending the protocol

The command dispatch is `handle_frame()` in `firmware/components/bridge/bridge.c`, and its
Python counterpart is in `tools/r70_emu.py`. Change both, in the same commit, and add a vector.

Three things in there that look like gaps and are not:

- **Commands `0x44` (interface version) and `0xA4` (baud calculation) are deliberately
  unanswered.** R1 sends both during initialisation and proceeds without a reply. When the
  emulator started answering them during bring-up, **R1 stopped**. The silence is part of the
  contract. `tools/board_test.py` tests for it explicitly, with a `--silence-wait` window.
- **`0xC0` (reset device) answers with the Device ID and does not reboot.** Per the vendor spec
  §2.10.1 devices answer a reset with their Device ID rather than with `0xC0`, and actually
  rebooting would drop the connection R1 is holding.
- **`0xA3` (block time) is echoed, not applied.** Batching is not implemented. Accepting the
  setting keeps R1 satisfied.

Two things that *are* placeholders and are worth fixing if you have the information:

- **The version triple `01 00 00 01 00 01` is invented**, not a real R70's.
- **The dbCAN application layer does not exist.** `tools/dbcan_device.py` addresses frames
  correctly and echoes the master's payload as a deliberate placeholder — its docstring says so.
  Any R1 reaction to it is *evidence about the protocol, not proof the device is correct*. Log
  the exchange and turn it into a real implementation; don't promote the placeholder.

Decoding must stay **stream-oriented**: several RMBCP frames can arrive in one TCP segment
(that is what Block Time batches on a real R70), so a datagram-shaped decoder will work in
testing and fail in the field.

---

## 6. Hardware

Rev A: 100 × 81 mm, 4-layer. ESP32-S3-WROOM-1-N8, W5500 with discrete magnetics into a Neutrik
etherCON, ADM3053 isolated CAN on two more etherCONs, USB-C PD (CH224K) → AP63200 buck.

The **7.0 mm isolation barrier** and **2.03 mm chassis moat** were verified against the *poured
copper*, not just the schematic. 45 of the 50 vendor BOM lines carry an LCSC part verified live;
the other 5 are the hand-soldered connectors. Fab outputs are in `hardware/fab/`.

**The board is fully routed: DRC reports 0 errors and 0 unconnected items**, with 31 accepted
silkscreen warnings (`silk_over_copper`, `silk_overlap`, `silk_edge_clearance`) and 56 footprint
parity warnings, of which 54 are unused IC pins with no schematic pin to match and 2 are a
leftover `Verified` field on R106/R107. J102 (USB-C) was found placed 180° out on 2026-07-31,
rotated and moved to the board edge, and the connections that move tore up are re-routed —
along with four hidden opens the same pass uncovered. Every fab package was regenerated from
the routed board; see [`FAB.md`](FAB.md).

Re-run DRC yourself with:

```bash
kicad-cli pcb drc --schematic-parity --severity-error --severity-warning hardware/dbcanary.kicad_pcb
```

### The LED polarity correction

**The status LEDs are ACTIVE HIGH**, not active low. `BOARD_LED_ACTIVE_LEVEL = 1` in
`board.h`, whose header comment records that this was active *low* here until bring-up work
re-derived it from the schematic — the net names ending `_K` are what misled. Nothing outside
`board.h` hard-codes a polarity, so **if all three LEDs come up inverted on first hardware,
that one constant is the fix** and nothing else needs touching.

Documentation elsewhere in this repo said active low for a while. If you find another
occurrence, it is wrong.

### Probe points

`hardware/scripts/probe_points.py` generates `hardware/fab/test/PROBE-POINTS.{json,csv}` and the
`docs/renders/probe-*.svg` drawings from `dbcanary.kicad_pcb`, and **refuses to run if a probe's
designator, pad or net no longer matches**. A marker cannot quietly drift off its pad across a
re-spin. Regenerate rather than hand-editing.

### Deferred to rev B

PoE, Ethernet ESD/TVS, silkscreen cleanup.

---

## 7. Scope

**Scope is a transparent bridge — exactly what the R70 is.** It is not a control surface and
should not grow into one.

**dbCANary stays d&b-only.** Multi-brand support was researched and the premise did not hold:
CAN is a d&b idiosyncrasy and no other manufacturer uses it, so a universal amp bridge's axis
is the *control protocol*, not the CAN dialect. That work moved to
[amp-commander](https://github.com/stoatworks-labs/amp-commander), whose KiCad project is a
renamed copy of dbCANary rev A — dbCANary's own project was deliberately left untouched.

**Legal**: this is an independent, clean-room-by-documentation implementation built from
published vendor documentation. Do not import d&b or RM Michaelides code or firmware into it,
and do not redistribute the vendor manuals — `docs/SOURCES.md` says where to get them.

---

## See also

- [API.md](API.md) — the implemented command set and tool CLIs
- [PROTOCOL.md](PROTOCOL.md) — the protocol as recovered, claims tagged `[spec]` / `[derived]` / `[unknown]`
- [SOURCES.md](SOURCES.md) — provenance
- [DECISIONS.md](DECISIONS.md) — why things are the way they are
- [USER-GUIDE.md](USER-GUIDE.md) — operating a unit
- [`hardware/fab/test/BENCH-BRINGUP.md`](../hardware/fab/test/BENCH-BRINGUP.md) — bring-up procedure
