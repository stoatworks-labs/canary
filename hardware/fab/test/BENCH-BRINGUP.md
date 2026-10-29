# CANary rev A — bench bring-up and hardware verification

| | |
|---|---|
| Board | CANary rev A, 100 × 81 mm, 4-layer |
| Document | BBU-CANARY-A, **revision 0.1 — DRAFT, worked through in part on board #1 only** |
| Equipment assumed | bench PSU with current limit, DMM, network switch, PC |
| Equipment optional | oscilloscope, logic analyser, insulation tester |
| Companion documents | [`FUNCTIONAL-TEST-SPEC.md`](FUNCTIONAL-TEST-SPEC.md) (production), [`PROBE-POINTS.csv`](PROBE-POINTS.csv), [`TEST-COVERAGE.md`](TEST-COVERAGE.md) |
| Per-board records | [`BRINGUP-LOG-0001.md`](BRINGUP-LOG-0001.md) — board #1, 2026-09-09, the first time this firmware ran on hardware; §12 is 2026-10-28, with two amplifiers |

> **One board has been through part of this** — board #1, with §1–§4 skipped
> ([`BRINGUP-LOG-0001.md`](BRINGUP-LOG-0001.md)), so no supply, rail or PD figure here has
> been measured yet. Every number below is derived from
> `canary.kicad_pcb`, the schematic and the component datasheets. Values are
> tagged **[spec]** (from a datasheet), **[derived]** (our arithmetic on the
> schematic, shown so you can check it) or **[predicted]** (an educated guess
> with no measurement behind it). **Never fail a board on a [predicted] value
> alone** — record what you actually measure, and re-issue this document as
> revision A with real limits once three boards have been through it.

---

## 0. Read this before you touch anything

### 0.1 The three etherCON jacks are not interchangeable, and they look identical

Along the bottom edge, left to right: **J201 (CAN A)**, **J202 (CAN B)**,
**J401 (LAN)**. etherCON accepts a plain RJ45, so nothing physically stops you
plugging a network cable into a CAN jack. The silkscreen in this area is one of
the known-poor regions (see [`docs/renders/README.md`](../../../docs/renders/README.md)).

**Label your patch leads before you start.** If you lose track, identify a jack
electrically with the DMM, board unpowered:

| Measure | J201 / J202 (CAN) | J401 (LAN) |
|---|---|---|
| Jack pin 4 to pin 5, SW201 **TERMINATED** | **118 – 130 Ω** | open |
| Jack pin 4 to pin 5, SW201 **UNTERMINATED** | over 10 kΩ | open |
| Jack pin 1 to pin 2 | open | a few Ω through the magnetics |

### 0.2 The PoE switch: what it is for, and the one way it can destroy the board

**Rev A has no PoE.** There is no PD controller and no isolated front-end
converter; PoE is on the rev B list. The switch in this procedure is used only
as a **DHCP server and a link partner**, and optionally as a second port for
the test PC.

A **standards-compliant 802.3af/at/bt switch is safe.** Before applying power a
compliant PSE looks for a 25 kΩ signature across the pairs. This board presents
about 150 Ω (two 75 Ω Bob Smith resistors in series) — far outside the
19 – 26.5 kΩ detection window — so a compliant switch will simply never power
the port. Managed switches from UniFi, Cisco, Netgear and so on all do this.

**A passive PoE injector will destroy the board.** "Passive PoE" — the 24 V and
48 V injectors sold with older wireless APs, and the "passive PoE" mode some
cheap switches offer — applies voltage with no detection at all.

| If passive PoE reaches | What happens |
|---|---|
| J401 (LAN), mode A on the data pairs | 48 V across R402 + R403 (75 Ω each) = **320 mA, 15 W in two chip resistors**. They fail open or on fire, and the magnetics see DC. |
| J401, mode B on the spare pairs | 48 V across R404 + R405. Same outcome. |
| J201 / J202 (CAN), pins 4 and 5 | 48 V lands **directly on CANH and CANL**. The ADM3053 is rated ±25 V absolute maximum. U201 is destroyed, and it is the part that provides the isolation. |

**Rules:** use a compliant switch or a non-PoE port; never a passive injector;
never plug a CAN jack into any network port.

### 0.3 There is a galvanic isolation barrier, and a ground clip defeats it

U201 (ADM3053) splits the board into a **system domain** (GND) and an
**isolated CAN domain** (CAN_GND / VISO), with 8.50 mm of copper spacing.

- System-side ground reference: **P9** — `C107.2`
- CAN-side ground reference: **K3** — `C206.2`

**Never connect them.** Not with a scope ground clip, not with a shared bench
ground, not with a non-isolated USB-CAN adapter, not with a non-isolated logic
analyser on CANH/CANL. A board with a bridged barrier passes every functional
test in this document and is still scrap.

The isolated domain is shaded on [`probe-can.svg`](../../../docs/renders/probe-can.svg).
Note that **U201, J201 and J202 straddle the barrier** — U201 is the barrier, and
the CAN jacks' shells are bonded to CAN_GND, not to chassis.

### 0.4 CHASSIS is a third domain, is not isolated, and floats

`CHASSIS` is the USB-C shell (J102) plus the LAN jack shell (J401) plus one
plate of C411. **It has no DC connection to GND anywhere on this board.**
Minimum GND-to-CHASSIS copper spacing is 1.15 mm at the USB-C shell, which is
normal for a USB shell but is nothing like the CAN barrier.

Two consequences:

1. **Never hipot GND ↔ CHASSIS.** It will break down at the USB-C connector and
   tell you nothing. Hipot GND ↔ CAN_GND instead (§9).
2. **Record this as a rev B question.** A shield with no bond to GND — not even
   the usual 1 MΩ ‖ 1 nF — has no defined ESD path. This is an observation from
   reading the netlist, not a measured problem; note the behaviour you see and
   raise it against rev B.

### 0.5 There are no test points

No `TP*` pads exist. Everything is probed on component pads and vias. Use fine
tips; 0402 pads are 0.54 × 0.64 mm. The probe catalogue with exact coordinates
is [`PROBE-POINTS.csv`](PROBE-POINTS.csv) (and `.json`); the drawings are:

| Drawing | Region |
|---|---|
| [`probe-overview.svg`](../../../docs/renders/probe-overview.svg) | whole board, all 38 points |
| [`probe-power.svg`](../../../docs/renders/probe-power.svg) | USB-C, CH224K, AP63200 buck |
| [`probe-mcu.svg`](../../../docs/renders/probe-mcu.svg) | ESP32-S3, LEDs, switches, J301 |
| [`probe-ethernet.svg`](../../../docs/renders/probe-ethernet.svg) | W5500, crystal, magnetics |
| [`probe-can.svg`](../../../docs/renders/probe-can.svg) | ADM3053, termination, CAN jacks |

Regenerate them with `hardware/scripts/probe_points.py`. They are built from
the board file and the script refuses to run if a probe's designator, pad or
net no longer matches — so a marker cannot quietly drift off its pad.

### 0.6 Equipment

| Item | Needed for | Notes |
|---|---|---|
| Bench PSU, 0–6 V, adjustable current limit | §2 | the single most useful instrument here |
| USB-C male breakout board | §2 | lets the PSU feed VBUS without soldering to the board |
| DMM | §1, §3, §6–§8 | |
| USB-C PD supply and cable | §4 onwards | a phone charger is fine |
| Network switch (non-PoE port) + patch leads | §7 | must run a DHCP server, or use a PC sharing one |
| PC with ESP-IDF v5.5 | §5 | |
| Oscilloscope, ≥ 100 MHz | Appendix A | optional |
| Logic analyser | Appendix B | optional; see B.0 on sample rate |
| Insulation tester, 500 V DC | §9 | optional, sample basis |
| **Galvanically isolated** USB-CAN adapter | §8.4 | optional; read §0.3 first |

---

## 1. Before power

Board on an ESD-safe surface, nothing connected.

### 1.1 Visual

| Step | Look at | Expect |
|---|---|---|
| 1.1.1 | U301, U401, U201, U103, U104 | no bridges, no tombstones, no missing parts |
| 1.1.2 | J102 USB-C | all pads wetted, shell tabs soldered, no bridge to the 0.5 mm pitch signal row |
| 1.1.3 | U201's outline vs the barrier | nothing — no part, no track, no solder ball — crosses the clear band across the middle of the board |
| 1.1.4 | D301–D304 | all four fitted the same way round |
| 1.1.5 | Y401 (25 MHz) | fitted, both terminals wetted |

Photograph anything odd before you touch it.

### 1.2 Unpowered resistance

DMM in resistance mode. **The board is full of bulk capacitance**, so every
reading below starts low and climbs as the meter charges the caps. Wait for it
to settle; the number that matters is where it stops.

Black lead on **P9** (`C107.2`, system ground) for all of these except 1.2.5.

| Step | Red lead on | Expect | Failing means |
|---|---|---|---|
| 1.2.1 | **P1** `F101.1` — VBUS_RAW | climbs to over 100 kΩ | under 10 Ω is a hard short on VBUS. **Stop.** |
| 1.2.2 | **P2** `C107.1` — VCC_5V | climbs to over 10 kΩ | under 10 Ω: short on the 5 V rail. **Stop.** |
| 1.2.3 | **P3** `C301.1` — VCC_3V3 | climbs to over 1 kΩ *(the ESP32-S3 module and the W5500 present a real unpowered load, so this settles lower than the others)* [predicted] | under 10 Ω: short on 3V3. **Stop.** |
| 1.2.4 | **P1** to **P2** across F101 | **under 1 Ω** [spec] | the PTC is open or unsoldered |
| 1.2.5 | **K3** `C206.2` (CAN_GND) with black on **P9** | **open circuit / over-range** [derived] | **the isolation barrier is bridged. Quarantine the board.** |

### 1.3 The values that prove the right parts were fitted

Still unpowered. These catch a reel loaded in the wrong feeder, which is
invisible to any functional test that happens to still work.

| Step | Across | Expect | Source |
|---|---|---|---|
| 1.3.1 | **E4** `R401.1` to P9 | **12.28 – 12.52 kΩ** | R401 12.4 kΩ 1 % — sets every analogue bias in the W5500 [spec] |
| 1.3.2 | `R103` (P3 side to **P4**) | 31.28 – 31.92 kΩ | 31.6 kΩ 1 % [derived] |
| 1.3.3 | **P4** `U103.1` to P9 | 9.9 – 10.1 kΩ | R104 10 kΩ 1 % [derived] |
| 1.3.4 | **K5** `J201.4` to **K6** `J201.5`, SW201 **TERMINATED** | **118 – 130 Ω** | R202 + R203 = 124 Ω, in parallel with the ADM3053's ≥ 40 kΩ receiver [derived] |
| 1.3.5 | K5 to K6, SW201 **UNTERMINATED** | over 10 kΩ | if it still reads 124 Ω the switch is shorted [derived] |
| 1.3.6 | **K7** `R202.2` to **K8** `R203.1`, SW201 **TERMINATED** | under 1 Ω | proves both poles of SW201 make. One pole alone gives 62 Ω at 1.3.4, not 124 Ω [derived] |

> **1.3.2 and 1.3.3 together set the 3.3 V rail.** The AP63200 regulates its FB
> pin to 0.8 V, so `VCC_3V3 = 0.8 × (1 + 31.6/10) = 3.328 V`. If either
> resistor is wrong, §3 will show a wrong rail and this is where you find out
> why.

---

## 2. First power-up, on a current-limited bench supply

**Do this before you ever plug in USB-C.** A PD supply will happily deliver
3 A into a short; a bench supply set to 100 mA will not.

### 2.1 Connect the supply

Use a **USB-C male breakout board** plugged into J102, and connect the bench
supply to its **VBUS** and **GND** terminals. This needs no soldering and keeps
the PTC (F101) in circuit, so the protection you are relying on is the
protection under test.

If you have no breakout, the alternative is a fine wire to **P1** (`F101.1`,
VBUS_RAW) and **P9** (`C107.2`, GND) — see [`probe-power.svg`](../../../docs/renders/probe-power.svg).

> **CC1 and CC2 will be unterminated.** With a bench supply there is no PD
> source, so the CH224K has nothing to negotiate with. That is expected. It
> also means **P6 (PD_PG) tells you nothing in this section** — its polarity is
> unverified and its state without a PD source is undefined. Record it, do not
> judge it.

### 2.2 The first application of power

| Step | Do | Expect | If not |
|---|---|---|---|
| 2.2.1 | Set **5.00 V**, current limit **100 mA**, output OFF | | |
| 2.2.2 | Output ON, watch the supply for 2 seconds | supply stays in **constant voltage** at 5.00 V | if it drops into constant current with the voltage collapsing below ~1 V, **there is a short. Output OFF.** Go back to §1.2. |
| 2.2.3 | Read the current | **[predicted] 60 – 100 mA** — the W5500's reset line has no pull-up (see 2.2.6) so its state before firmware runs is not defined, and this figure is the least certain number in this document | over 100 mA and limiting: raise the limit to 250 mA and repeat; if it limits again, look for a partial short |
| 2.2.4 | Look at **D304** (green, marked ON) | **lit steadily** | see 2.3 |
| 2.2.5 | Back of a finger over U103, U104, U201, U401, U301 | none noticeably warm after 30 s | any hot part: **output OFF immediately** and find out which |
| 2.2.6 | Note the current for the record | | |

> **2.2.6 — a rev B observation to record.** `ETH_RSTn` (GPIO9 → U401 pin 37)
> has no pull-up resistor, and the ESP32-S3 leaves GPIO9 floating until
> firmware drives it. The W5500's reset state between power-on and the first
> line of firmware is therefore not defined by this design. It has an internal
> power-on reset so it will probably behave, but the idle current in 2.2.3 is
> the thing most likely to differ from the prediction because of it. Record
> what you see; a pull-up is a rev B candidate.

### 2.3 If D304 is dark

D304 is fed from VCC_3V3 through R305, with no MCU involvement. It is the
single most informative indicator on an unprogrammed board: lit proves the
USB-C connector, F101, U103 and the whole 3.3 V rail in one glance.

| Check | Meaning |
|---|---|
| **P2** = 5 V but **P3** = 0 V | the buck is not running — U103, L102 or C106 |
| P3 = 3.3 V and D304 dark | the LED is fitted backwards, or R305 is missing/open |
| P2 = 0 V and P1 = 5 V | F101 is open |
| P1 = 0 V | nothing is reaching the board — cable, breakout, supply |

### 2.4 Raise the limit

Once 2.2 passes, set the current limit to **500 mA** and leave it there for the
rest of the procedure. It is still low enough to save a board from a fault that
develops later.

---

## 3. Rails

Bench supply on, board idle, DMM black lead on **P9** throughout.

| Step | Probe | Net | Expect | Source |
|---|---|---|---|---|
| 3.1 | **P1** `F101.1` | VBUS_RAW | 4.75 – 5.25 V | [spec] the supply setting |
| 3.2 | **P2** `C107.1` | VCC_5V | 4.70 – 5.25 V, **within 100 mV of P1** | [derived] the PTC's cold resistance is small |
| 3.3 | **P3** `C301.1` | VCC_3V3 | **3.23 – 3.43 V**, nominal **3.328 V** | [derived] 0.8 V × (1 + 31.6/10), ±3 % for the reference and 1 % resistors |
| 3.4 | **P10** `L102.2` | VCC_3V3 | within 20 mV of P3 | [derived] same rail, different end |
| 3.5 | **P4** `U103.1` | FB2 | **0.784 – 0.816 V** | [spec] AP63200 0.8 V reference ±2 % |
| 3.6 | **M1** `R301.2` | EN | 3.23 – 3.43 V | [derived] 10 k pull-up to 3V3 |
| 3.7 | **M2** `J301.1` | VCC_3V3 | same as P3 | [derived] proves the debug header is soldered |
| 3.8 | **K9** `U201.8` | VCC_5V | 4.70 – 5.25 V | [derived] the ADM3053's isolated DC-DC runs from **5 V**, not 3.3 V |
| 3.9 | **K10** `U201.6` | VCC_3V3 | 3.23 – 3.43 V | [derived] VIO sets the logic level the S3 sees |
| 3.10 | **E1** `C408.1` | ETH_1V2 | **1.08 – 1.32 V** | [spec] the W5500's internal 1.2 V regulator. **0 V here means the W5500 is not alive** and nothing in §7 can work |
| 3.11 | **E2** `C409.1` | ETH_VBG | 1.1 – 1.4 V | [predicted] the datasheet publishes no limit — record it, do not judge it |
| 3.12 | **E3** `C410.1` | ETH_TOCAP | 1.0 – 1.4 V | [predicted] as above |
| 3.13 | **P5** `C109.1` | PD_VDD | 3.3 – 5.1 V | [predicted] fed through R106 1 k, so the drop depends on the CH224K's quiescent current, which we have not measured |
| 3.14 | **P6** `U104.10` | PD_PG | record the level, do not judge it | [predicted] open-drain, no external pull-up, polarity unverified |

### 3.15 The isolated side — **change your reference**

Move the DMM black lead to **K3** (`C206.2`, CAN_GND). Every reading below is
referenced to K3, not to P9.

| Step | Probe | Net | Expect | Source |
|---|---|---|---|---|
| 3.15.1 | **K1** `C204.1` | VISO_RAW | **4.5 – 5.5 V** | [spec] ADM3053 *iso*Power output |
| 3.15.2 | **K2** `C206.1` | VISO | within 100 mV of K1 | [derived] FB201 is a 600 Ω @ 100 MHz bead, near-zero at DC |
| 3.15.3 | **K4** `R201.1` | CAN_RS | **under 0.3 V** | [spec] R201 is 0 Ω to CAN_GND, so the transceiver is in high-speed mode |
| 3.15.4 | **K5** `J201.4` | CANH | 2.3 – 2.7 V, bus idle | [spec] both lines sit at the recessive common mode |
| 3.15.5 | **K6** `J201.5` | CANL | 2.3 – 2.7 V, **within 100 mV of K5** | [spec] |

> **3.15.1 is the proof that the barrier works electrically.** VISO exists only
> because the ADM3053's on-chip transformer is running. If K1 reads 0 V while
> K9 reads 5 V, the isolated DC-DC has not started and nothing on the CAN side
> can do anything.

### 3.16 Re-check isolation with everything powered

Return the black lead to **P9**. Measure **P9 to K3** in resistance mode with
the supply still on: still **open**. A barrier that is fine cold and bridged
warm is a solder-ball problem, and it is worth catching now rather than in §9.

---

## 4. USB-C Power Delivery

Now swap the bench supply for a real USB-C PD source.

| Step | Do | Expect |
|---|---|---|
| 4.1 | Bench supply OFF and disconnected | |
| 4.2 | Plug a USB-C PD supply into J102 | D304 lights |
| 4.3 | Repeat 3.1 – 3.5 | same values as on the bench supply |
| 4.4 | **P6** `U104.10` PD_PG | record the level. Compare with what you recorded in 3.14 — **the difference between "PD source present" and "dumb 5 V" is the only evidence we have about this pin's polarity.** Write both down. |
| 4.5 | If you have a USB power meter in line | negotiated profile should be **5 V**; record the current |
| 4.6 | Flip the cable end for end and repeat 4.2 | works identically — this is the only test of CC2, and a cold joint on one CC pin makes the board work in exactly one cable orientation |

> **4.6 is easy to skip and worth doing.** USB_CC1 goes to U104 pin 7, USB_CC2
> to pin 6. A board with one bad CC joint works perfectly with the cable one
> way round and is dead the other, which in the field reads as "bad cable".

---

## 5. Programming and the on-board self-test

### 5.1 Build both images

```bash
cd firmware
idf.py build                                   # the product image
idf.py -B build-selftest build -DCANARY_SELFTEST=1   # the bench test image
```

The self-test image runs every on-board test and then a command console, and
does **not** start the bridge. Flash that one first.

> **The console is on USB-C (USB-Serial-JTAG), not on J301.** The self-test REPL
> binds to whatever the *primary* console is, and that is now
> `CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG` — so one USB-C cable carries power,
> programming and the console.
>
> It was not always so, and the old arrangement is worth recognising if you ever
> meet it again: with UART0 as primary and USB-Serial-JTAG only as the
> *secondary* console, output was duplicated to USB-C but **input was not**. You
> saw the banner and the `canary> ` prompt over USB-C, typed `selftest`, and
> nothing happened — because the REPL was reading GPIO43/44, reachable only on
> J301. A prompt that ignores you reads exactly like a dead board.
>
> If a board will not enumerate over USB, build the J301-console variant:
>
> ```bash
> idf.py -B build-selftest-uart -DSDKCONFIG=build-selftest-uart/sdkconfig \
>        -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.uart-console" \
>        build -DCANARY_SELFTEST=1
> ```
>
> and drive it with a 3.3 V USB-serial adapter on J301 pins 2/3/4 at 115200.

### 5.2 Enter the bootloader and flash

The ESP32-S3 has native USB, so J102 is both power and programming port.

| Step | Do | Expect |
|---|---|---|
| 5.2.1 | Hold **SW302 (BOOT)**, tap **SW301 (RESET)**, release SW302 | the board enumerates as an ESP32-S3 in ROM download mode |
| 5.2.2 | `idf.py -B build-selftest -p <port> flash` | completes without a timeout |
| 5.2.3 | Tap SW301 | the board reboots into the test firmware |

If it will not enumerate at all, use **J301** (1 × 6, 1.27 mm pitch) instead:
pin 1 `VCC_3V3`, 2 `GND`, 3 `UART0_TXD`, 4 `UART0_RXD`, 5 `BOOT`, 6 `EN`. A
3.3 V USB-serial adapter on pins 2/3/4 gives you the ROM bootloader's own
console, which tells you whether the S3 is running at all.

**Have that adapter on the bench.** These boards were fabbed from `d9a725d`
(ordered 2026-08-13), which predates the 2026-08-22 USB fix — `USB_DP`/`USB_DM`
are two uncoupled traces 9.5 mm apart with ~16 mm of length mismatch. Full-speed
USB should tolerate that comfortably (~89 ps of skew against an 83 ns bit time,
and a ~95 mm trace is electrically short next to a 4–20 ns edge), but it has
never been proven on silicon, and J102 is the *only* power path as well as the
only programming path.

### 5.3 Run the self-test

```bash
idf.py -B build-selftest -p <port> monitor
```

then at the `canary>` prompt:

```
selftest
```

Expected output — this is the shape, not a transcript from a real board:

```
RESULT chip INFO ESP32-S3 rev v0.2, 2 core(s), idf v5.5.5
RESULT flash.size PASS 8 MB (expect >= 8 MB for the -N8 module)
RESULT mac.eth PASS ...
RESULT reset.reason INFO power-on
RESULT pd.pg INFO GPIO18 reads 0 (polarity unverified)
RESULT eth.versionr PASS 0x04 at 4 MHz - SPI, 3V3, 25 MHz crystal and reset all good
RESULT eth.regwalk PASS wrote 5AA5 to RTR, read 5AA5
RESULT eth.versionr.fast PASS 0x04 at 20 MHz
RESULT can.loopback PASS 8-byte frame round-tripped through the ADM3053 ...
RESULT led.walk INFO GPIO15/16/17 driven, active level 1 - confirm by eye
SELFTEST-END pass=6 fail=0 skip=0 info=4
```

**`SW201 must be TERMINATED for `can.loopback`.** With no 120 Ω load the bus
does not settle inside a bit time and the loopback fails on a perfectly good
board. The failure message says so, but set the switch first.

### 5.4 What each result actually proves

| Result | What a PASS proves |
|---|---|
| `eth.versionr` | the SPI bus in **both** directions, the W5500's 3.3 V supply, its 25 MHz crystal, and its reset line — in one register read. **Nothing else on this board is one read away from that much coverage.** |
| `eth.regwalk` | MOSI specifically. A read alone only proves MISO |
| `eth.versionr.fast` | the same link at the 20 MHz the application uses. A board that passes at 4 MHz and fails at 20 MHz is a signal-integrity finding, and it is only visible because they are separate tests |
| `can.loopback` | GPIO4 → ADM3053 → **across the isolation barrier** → CANH/CANL → back → GPIO5. It therefore also proves the isolated DC-DC started, which cannot be checked from the system domain |
| `mac.eth` | the eFuse MAC is programmed and unique. This is the address the W5500 gets, and R1 keys its interface list on it |

### 5.5 If `eth.versionr` fails

The detail line tells you which failure it is:

| Reads | Most likely |
|---|---|
| `0x00` | MISO idle low — the W5500 is not driving. Check §3.10 (ETH_1V2), then the crystal (Appendix A.3), then ETH_RSTn (**E10**, `U401.37`, should be 3.3 V once firmware has run) |
| `0xFF` | MISO idle high — nothing is pulling the line; suspect the MISO track or U401 pin 34 |
| anything else | the SPI is running but out of sync — check SCK and CS with a logic analyser (Appendix B.1) |

---

## 6. Status LEDs

### 6.1 Walk them

At the console:

```
led all off
led lan on
led err on
led can on
led all off
```

| LED | Designator | Colour | Marked |
|---|---|---|---|
| lan | D301 | green | LAN |
| err | D302 | red | ERR |
| can | D303 | green | CAN |
| — | D304 | green | ON — always lit, no MCU control |

### 6.2 Check the drive level

With `led lan on`, measure **M6** (`R302.1`, the GPIO15 end of R302) against P9:

| Reading | Meaning |
|---|---|
| ~3.3 V and D301 lit | correct, and the polarity in `board.h` is right |
| ~0 V and D301 lit | **`BOARD_LED_ACTIVE_LEVEL` in `firmware/components/board/include/board.h` is wrong** |

### 6.3 The polarity question — please answer this one carefully

**This is the one place where firmware and the board file were found to
disagree, and it has not been settled on hardware.**

`board.h` was changed on 2026-07-27 from ACTIVE LOW to ACTIVE HIGH after
re-deriving the connection from `canary.kicad_pcb`:

- KiCad's `Device:LED` symbol is **pin 1 = K (cathode), pin 2 = A (anode)**.
- `D301.1 → GND`, `D301.2 → R302 → GPIO15`. Same shape for D302 and D303.
- `D304.1 → GND`, `D304.2 → R305 → VCC_3V3`.

D304 settles it: it has no GPIO, it is a rail-powered ON lamp, and it **must**
light whenever 3.3 V is up. That only works if current flows R305 → pin 2 →
pin 1 → GND, so pin 2 is the anode — and D301–D303 have the identical topology
with a GPIO where D304 has the rail. Driving the GPIO **high** lights them.

| What you see | What it means | What to do |
|---|---|---|
| `led lan on` lights D301, `off` darkens it | the reading above is correct | nothing |
| the commands are inverted | the reading above is **wrong** | set `BOARD_LED_ACTIVE_LEVEL` back to 0, and record why — the derivation above is then wrong and needs correcting, not just the constant |
| D304 is lit but D301–D303 never light either way | the GPIOs are not reaching the LEDs — check R302/R303/R304 | |

Record the answer in the test record. The net names `LED_LAN_K` etc. are
misnamed for the anode side either way; renaming them is a rev B item.

---

## 7. Ethernet

### 7.1 Set up the switch

- Use a **non-PoE port**, or confirm the switch does proper 802.3af/at
  detection. Re-read §0.2 if in doubt.
- A DHCP server must be reachable on that segment.
- Put the test PC on the same segment.

### 7.2 Link

| Step | Do | Expect |
|---|---|---|
| 7.2.1 | Patch **J401** to the switch. Component side up, USB-C at the top: J401 is the **right-hand** of the three bottom-edge jacks, the one under the W5500 | the switch port shows link |
| 7.2.2 | Reboot the board (`reboot` at the console, or SW301) | |
| 7.2.3 | Watch the switch port LEDs | link at 100 Mbit/s |
| 7.2.4 | Read the console log | an IP address from DHCP |

If there is no link, before suspecting the W5500: check **E11** (`R410.2`,
ETH_TCT, the PHY side of the 10 Ω). With the link up it should sit **20 – 120 mV
below** the 3.3 V rail [derived]; with no link it sits at the rail. No drop
across R410 means the transmitter is not driving at all.

### 7.3 Reachability

```bash
ping -c 100 <board-ip>
```

Expect **0 % loss**. Sporadic loss with a good link points at SPI marginality —
compare `eth.versionr` at 4 MHz and 20 MHz in §5.3.

### 7.4 Bob Smith sanity

Measure **E12** (`C411.1`, the Bob Smith node) to P9: **under 0.5 V DC**
[derived]. Volts here means something is feeding the spare pairs — and the
thing that feeds spare pairs is a PoE port. Unplug it and re-read §0.2.

---

## 8. CAN

### 8.1 Termination

Set **SW201 to TERMINATED** unless the board is a mid-chain node. Verify with
1.3.4 if you have not already.

### 8.2 Loopback, no external hardware

Already covered by `selftest can` in §5.3. Re-run it after any rework on the
CAN side. This is the highest-value CAN test you can do with nothing plugged
in, because it crosses the isolation barrier in both directions.

### 8.3 Listen-only against a real bus

**Listen-only never acknowledges, so it cannot disturb a live d&b system.** It
is the right mode for a first connection to customer equipment.

```
can listen
can rx 5000
can stats
```

| Expect | Meaning |
|---|---|
| frames appear with 11-bit IDs | the bus is alive and the board sees it |
| `bus_err` staying at 0 | bit timing agrees with the bus |
| `bus_err` climbing | wrong rate, wrong termination, or wiring — dbCAN is **fixed at 100 kbit/s**, and testing at any other rate proves nothing |

### 8.4 Two-jack test

J201 and J202 are the **same bus in parallel**, for daisy-chaining. A frame
into one must appear at the other.

With an **isolated** USB-CAN adapter at 100 kbit/s (re-read §0.3):

| Step | Do | Expect |
|---|---|---|
| 8.4.1 | Adapter on **J201**, board in `can listen` | bus idle, no error frames |
| 8.4.2 | Adapter transmits a known frame | the console prints it with the right ID and payload |
| 8.4.3 | `can normal`, then `can tx 123 55AA` | the adapter receives it. In `normal` mode the board **needs the adapter to acknowledge** — a transmit that fails with no other node on the bus is CAN working correctly, not a fault |
| 8.4.4 | Move the adapter to **J202** and repeat 8.4.2 | proves the second jack |

---

## 9. Isolation (sample basis, before anything else is connected)

| Parameter | Value |
|---|---|
| Between | **P9** (`C107.2`, GND) and **K3** (`C206.2`, CAN_GND) |
| Test | 500 V DC insulation resistance |
| Pass | **over 100 MΩ** |
| **Never test** | GND ↔ CHASSIS — see §0.4 |

The ADM3053 is rated 2.5 kV RMS for one minute and the PCB provides 8.50 mm of
creepage. A 500 V screen is not a type test of the part: it is there to catch
**assembly** defects — solder splash, flux residue, contamination across the
barrier. Those are exactly the faults that pass every functional test.

Any failure of 1.2.5, 3.16 or this test is an isolation failure: **quarantine
the board.** A partially bridged barrier is the one defect that is invisible in
normal operation.

---

## 10. Full system test

Flash the **product** image, then run the host-side acceptance test:

```bash
tools/board_test.py --serial-number 0001 --operator AS --record boards/0001.json
```

It discovers the board with **R1's own captured discovery probe**, walks the
RMBCP command set on TCP 30000, checks the two commands that must stay
unanswered, and writes a JSON record.

To include the board's own self-test in the same record, flash the self-test
image instead and add `--port /dev/cu.usbmodem101`.

To test the CAN wire end to end, add `--can-channel can0 --can-interface socketcan`
with an **isolated** adapter attached.

You can prove the runner itself works before any board exists:

```bash
tools/board_test.py --simulate
```

That runs `tools/r70_emu.py` as a stand-in device. It exercises every stage
except the serial console and the CAN wire, and reports them as SKIP rather
than pretending it looked.

Finally, the real acceptance test is R1 itself: scan, go Offline, tick the
interface, then back Online.

---

## Appendix A — oscilloscope

Ground clip on **P9** for everything in this appendix. **Never on the CAN side
unless the scope channel is isolated** — see §0.3.

### A.1 3.3 V rail quality — `P3` (`C301.1`)

AC coupled, 20 MHz bandwidth limit on, ground spring rather than the clip lead.

| Measure | Expect | Source |
|---|---|---|
| Ripple | **under 50 mVpp** | [predicted] |
| Switching ripple frequency | ~500 kHz, matching A.2 | [derived] |
| Any 100 Hz / 120 Hz component | none — this is a DC-fed buck | [derived] |

### A.2 Buck switching node — `P7` (`U103.5`, SW2)

DC coupled, 10:1 probe.

| Measure | Expect | Source |
|---|---|---|
| Amplitude | 0 V to about VIN (5 V) | [derived] |
| Frequency at load | **500 kHz ±20 %** | [spec] AP63200 |
| Duty at load | **62 – 72 %** (3.33/5 = 67 %) | [derived] |
| Ringing on the rising edge | note the amplitude for the record | [predicted] |

> **At light load this will not be steady, and that is correct.** The AP63200
> drops into pulse-skipping at light load, so you will see bursts of pulses
> separated by gaps, and neither the frequency nor the duty will match the
> table. Load the rail (Ethernet linked, CAN running) before judging it.

`P8` (`C105.2`, BST2) should be the same waveform offset upward by roughly
4.5 – 5 V. Flat means C105 is open and the high-side FET is not being driven
properly.

### A.3 25 MHz crystal — `E5` (`R412.1`, the W5500 side of the 0 Ω)

> **Probe this only if `eth.versionr` has already failed.** A 10:1 probe adds
> around 10 pF, which is enough to pull or stop a crystal oscillator. A pass
> here on a board that fails §5 is not proof of anything; a *fail* here is.

| Measure | Expect | Source |
|---|---|---|
| Frequency | **25.000 MHz ± 250 Hz** (Y401 is ±10 ppm) | [spec] |
| Shape | roughly sinusoidal, not square | [predicted] |
| Amplitude | 0.8 – 2.0 Vpp | [predicted] |

Expect the frequency to be pulled by the probe. Judge "oscillating at about
25 MHz" — not the last digit.

### A.4 UART at reset — `M3` (`J301.3`, UART0_TXD)

Single-shot trigger on the falling edge, tap SW301.

| Measure | Expect | Source |
|---|---|---|
| Idle level | 3.3 V | [derived] |
| Activity after reset | a burst within ~100 ms, then silence | [derived] ROM bootloader banner |
| Bit width | 8.68 µs (115200 baud) | [derived] |

Silence here after a reset means the S3 is not running at all — a much earlier
fault than anything in §5.

The burst **stopping** is expected and is not a fault: the ROM prints its banner
on UART0 regardless, but the app console is on USB-Serial-JTAG (§5.1), so UART0
goes quiet at the hand-off to the second-stage bootloader. Confirmed under QEMU,
where booting the USB-console image gave exactly this — ROM output ending at
`entry 0x403c8920`, then nothing.

### A.5 CAN bus, differential — **isolated channels only**

Two channels, both ground-referenced to **K3** (`C206.2`), or a differential
probe. **If your scope's channel grounds are commoned to mains earth and
anything else on the bench touches GND, this test bridges the barrier.**

A single loopback frame is about 1 ms long and hard to catch once. Put the bus
in no-ack mode and transmit on demand instead — in that mode a transmit
succeeds with no other node present:

```
can selftest
can tx 123 55AA00FF0FF05AA5
```

Repeat the `can tx` line as often as you need. (`selftest can` also works, but
it runs one frame and then releases the controller.)

| Measure | Expect | Source |
|---|---|---|
| Bit time | **10.0 µs** (100 kbit/s) | [spec] dbCAN's fixed rate |
| CANH dominant | ~3.5 V to CAN_GND | [spec] |
| CANL dominant | ~1.5 V to CAN_GND | [spec] |
| CANH − CANL dominant | **1.5 – 3.0 V** | [spec] |
| CANH − CANL recessive | under 0.5 V | [spec] |
| Ringing after a dominant-to-recessive edge | should settle inside one bit time. If it does not, the bus is unterminated — check SW201 | [derived] |

---

## Appendix B — logic analyser

### B.0 Sample rate, and why the self-test reads the W5500 twice

A logic analyser needs roughly 4× the signal rate to decode reliably. The
application's SPI clock is **20 MHz**, so decoding it needs **80 MS/s or
better** — a cheap 24 MS/s clone cannot do it.

This is why `selftest_eth()` does its **first** VERSIONR read at **4 MHz** and
only then repeats at 20 MHz. A 24 MS/s analyser can capture that first
transaction cleanly. If all you have is a cheap analyser, capture the 4 MHz
read; it carries the same bytes.

Ground the analyser to **P9**. All the pins below are in the system domain, so
this is safe — **including the CAN ones**, because you are probing the *logic*
side of the ADM3053, not the bus.

### B.1 SPI to the W5500

| Channel | Probe | Pad |
|---|---|---|
| CLK | **E7** SPI_SCK | `U401.33` |
| MOSI | **E8** SPI_MOSI | `U401.35` |
| MISO | **E9** SPI_MISO | `U401.34` |
| CS | **E6** ETH_CSn | `U401.32` |

Decoder: SPI, **mode 0** (CPOL 0, CPHA 0), MSB first, CS active low.

Trigger on the CS falling edge and reset the board. The **first** transaction
should be the VERSIONR read:

| Byte | MOSI | MISO | Meaning |
|---|---|---|---|
| 1 | `0x00` | — | address high |
| 2 | `0x39` | — | address low — VERSIONR |
| 3 | `0x00` | — | control: common register block, read, variable-length mode |
| 4 | `0x00` | **`0x04`** | **the W5500's version. This byte is the whole test.** |

[derived from the W5500 datasheet's SPI frame format and ESP-IDF's
`esp_eth_mac_w5500.c`, which sets `command_bits = 16` (the address phase) and
`address_bits = 8` (the control phase).]

| What you see | Meaning |
|---|---|
| The three MOSI bytes but MISO flat at 0 | the W5500 is not driving — supply, crystal or reset |
| MISO flat at 1 | nothing is pulling MISO; suspect the track or U401 pin 34 |
| No CS activity at all | the ESP32-S3 side never started — check firmware, not hardware |
| CS and CLK but no MOSI | GPIO11 or its track |

### B.2 TWAI, on the logic side of the transceiver

| Channel | Probe | Pad | Direction |
|---|---|---|---|
| TXD | CAN_TX | `U201.5` | S3 → transceiver |
| RXD | CAN_RX | `U201.4` | transceiver → S3 |

Decoder: **CAN**, 100 kbit/s, sampling the TXD line.

Run `selftest can` at the console (or `can selftest` then `can tx ...` if you
want repeatable traffic). Expect on TXD:

| Field | Expect |
|---|---|
| Bit time | **10.0 µs** |
| Identifier | `0x123`, 11-bit |
| DLC | 8 |
| Data | `55 AA 00 FF 0F F0 5A A5` |

**RXD should carry the same frame a fraction of a bit later.** That is the
whole point: TXD is what the S3 sent, RXD is what came back through the
transceiver and across the barrier. Seeing it on TXD and not on RXD isolates
the fault to the transceiver or the isolated supply, and needs no isolated
equipment at all.

### B.3 Boot straps

| Channel | Probe | Pad |
|---|---|---|
| BOOT / GPIO0 | `J301.5` | |
| EN | `J301.6` | |
| UART0_TXD | `M3` `J301.3` | |

Capture across a reset. EN should rise ~10 ms after power (the 10 k / 100 nF
RC), BOOT should be high for a normal boot and low for ROM download, and
UART0_TXD should start talking shortly after EN rises.

---

## Appendix C — what to record

Log **parametric values, not pass/fail**, keyed to the board's serial number.
`PROBE-POINTS.csv` has empty `measured` and `pass_fail` columns for exactly
this.

Minimum per board:

| Field | From |
|---|---|
| Serial number, date, operator | |
| Idle current on the bench supply | 2.2.3 |
| VBUS_RAW, VCC_5V, VCC_3V3, FB2 | 3.1 – 3.5 |
| VISO (to CAN_GND) | 3.15.1 |
| PD_PG level with a bench supply **and** with a PD supply | 3.14, 4.4 |
| W5500 VERSIONR at 4 MHz and 20 MHz | 5.3 |
| **LED polarity: does `led lan on` light D301?** | 6.3 |
| CAN termination, both switch positions | 1.3.4, 1.3.5 |
| Isolation resistance, where sampled | 9 |
| `board_test.py` JSON record | 10 |

### Open questions this document is trying to answer

These are the things nobody knows yet. Board #1 answers them, and this document
gets re-issued as revision A with the answers in it.

1. **What is the real idle current?** (2.2.3) The prediction is the weakest
   number here.
2. **Which way round are the LEDs?** (6.3)
3. **What does PD_PG do, and in which polarity?** (3.14, 4.4)
4. **Do ETH_VBG and ETH_TOCAP sit where we guessed?** (3.11, 3.12)
5. **Does the W5500 work at 20 MHz on un-length-matched routing?** (5.3)
6. **Does the floating ETH_RSTn cause anything odd before firmware runs?** (2.2.6)
7. **Does anything care that CHASSIS is not bonded to GND?** (0.4)
