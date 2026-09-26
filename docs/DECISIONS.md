# dbCANary — Design Decisions (ADR-style)

Defaults chosen so work can proceed. Flag any to change before the schematic is
finalised.

| # | Decision | Default (chosen) | Alternative | Why default | Reversible? |
|---|----------|------------------|-------------|-------------|-------------|
| **D1** | **Scope** | **transparent bridge only** ✅ | + virtual amplifier simulator | the real R70 does not interpret dbCAN, so a faithful clone needs zero d&b parameter knowledge — the single biggest scope saving available | Chosen |
| **D2** | **Transport** | **RM Byte Command Protocol** ✅ | reverse-engineer from captures | the R70 is an OEM RM Michaelides gateway (proved via its IEEE IAB MAC block) and the protocol is published | Chosen — evidence in PROTOCOL.md §1 |
| **D3** | MCU | classic ESP32-WROOM-32E | ESP32-S3 / -C6 | matches nanODE; built-in TWAI (CAN 2.0) controller; RMII EMAC for wired Ethernet | Low |
| **D4** | Ethernet | wired PHY via RMII | WiFi only | R1 over WiFi is explicitly supported by the R70, but touring wants copper; PoE needs it anyway | Medium |
| **D5** | CAN PHY | isolated transceiver (e.g. ISO1042 / ADM3053) | plain TJA1051 + no isolation | the R70 is galvanically isolated, and TI 312 warns CAN ground rides the cable shield with a known E-PAC grounding trap | Low |
| **D6** | CAN bit rate | **100 kbit/s fixed** | selectable | dbCAN is fixed at 100 kbit/s and "can not be changed" (R70 SW manual §1.3.1) | No — protocol |
| **D7** | Power | PoE 802.3af + DC barrel | DC only | matches the R70 exactly; nanODE already has the PoE design work | Low |
| **D8** | Sockets | 1 to start, 4 later | 4 immediately | R1 uses socket 1 (TCP server, 30000); the other three cover multi-master and R70↔R70 bridging, neither needed for v1 | Low — firmware. **One consequence was not foreseen here:** the S3 has one USB PHY, so TinyUSB takes it from USB_SERIAL_JTAG and the USB-C port stops being the console and the auto-reset programming port. Hence NCM ships as a build overlay, not as the default image |
| **D9** | Discovery | emulate UDP 33333 | require manual config in R1 | auto-detection is what makes it feel like a real R70; manual config is the documented fallback if the handshake resists | Low |
| **D10** | Host tooling language | Python | Rust | this is an iterative protocol-cracking harness that must run wherever R1 runs; zero build beats a static binary here. Matches nanODE's `tools/` | Trivial |
| **D11** | Firmware language | C (ESP-IDF) | Rust (esp-hal) | matches nanODE; TWAI + lwIP are first-class in ESP-IDF | Medium |
| **D12** | Project name | **dbCANary** | (any) | dbCAN + canary; lowercase `dbcanary` for identifiers, hostnames and the CMake project | Trivial |

## Hardware — MCU pivot (2026-07-23)

The USB question forced a re-examination of D3/H1–H3. **The classic ESP32 has no
native USB peripheral** — it is UART-only, which is why programming needed a
bridge chip. It physically cannot present as a USB device, so neither a USB-NIC
nor R60 emulation was possible on it at any effort level. It was chosen (D3/H3)
precisely *because* only it had the RMII EMAC.

| # | Decision | Chosen | Alternative | Why | Reversible? |
|---|---|---|---|---|---|
| **H14** | **MCU** | **ESP32-S3-WROOM-1** ✅ | classic ESP32-WROOM-32E (supersedes D3/H3) | native USB-OTG unlocks USB-NIC *and* R60 emulation, and **deletes the USB-UART bridge chip** — the S3 is its own programming port. Keeps TWAI, so the CAN side is untouched | Chosen — costly after layout |
| **H15** | **Ethernet** | **W5500 over SPI** ✅ | LAN8720A RMII (supersedes H2/H3) | the S3 has no EMAC, so RMII is gone. dbCAN is 100 kbit/s — SPI is orders of magnitude more headroom than needed. **Removes the 50 MHz oscillator and the length-matched RMII group**, which were the most EMC-critical things on the board. Driver ships with ESP-IDF (`esp_eth_mac_w5500.c`) | Chosen |
| **H16** | USB roles | **NIC (NCM) first** ✅ (written 2026-09-21; enumeration, DHCP lease and every service proven on a macOS host 2026-09-26 — see [USB-NIC.md](USB-NIC.md) §7), then R60 (CDC serial), plus programming | power only | NCM reuses the *entire* proven stack — RMBCP, DDT discovery, bridge — unchanged, so R1 discovers us over the USB cable. `tusb_ncm` is an official ESP-IDF example, ESP32-S3 supported. R60 is nearly free afterwards: it speaks **the same RM Byte Command Protocol over a serial port** | Low — firmware |
| **H17** | **Power inputs** | **PoE + USB-C only** ✅ | + 2.1 mm barrel (was H9/H11b) | user decision. Both sources give 5 V directly, so the wide-Vin buck, its inductor, bulk caps, TVS and OR diode all disappear — and the awkward 12–24 V vs the R70's 10–30 V compromise goes with them | Chosen |
| **H18** | USB power role | **CH224K PD sink, real negotiation** ✅ | plain 5.1 k CC pulldowns (5 V sink only) | user decision: make "USB-PD" literally true. Negotiates 5 V explicitly, so the 500 mA Default-USB-Power edge case disappears. **In KiCad's stock `Interface_USB` library**, so no custom symbol and no library-cache blocker | Chosen |
| **H18a** | **CFG1 wiring** | **hard-tied to PD_VDD in copper** ✅ | MCU GPIO; CFG1 resistor to GND | **safety-critical.** CH224K requests **20 V if CFG1 floats at power-up** (datasheet §5.2.2). 20 V would pass D103 onto VCC_5V and destroy the ADM3053 (VCC abs max ~6 V) and U103's input. It cannot be an MCU GPIO — the MCU is powered *from* this rail, so it cannot configure the chip before the rail exists | No — safety |

### H14 knock-on: firmware

`components/net` is WiFi-STA today, so nothing breaks immediately, but the wired
path is now W5500-over-SPI rather than internal EMAC, and `sdkconfig.defaults`
targets `esp32`. Both need rework. The protocol components (`rmbcp`, `r70_ddt`)
are pure C and **entirely unaffected** — as is `tools/`, the reference
implementation proven against R1.

### Resolved: "USB-PD" is now literally true

H18 fits a **CH224K** PD sink controller — real negotiation over CC1/CC2, not a
passive 5 V sink. The 5.1 k Rd pulldowns were **removed**: the CH224K drives CC
itself, and fixed resistors in parallel would present the wrong impedance and
break PD signalling.

Why 5 V rather than a higher PD voltage: 5 V feeds the ADM3053 directly. Asking
for 9 V or 12 V would reintroduce the wide-Vin buck that H17 just deleted.

CH224K DP/DM are **deliberately left unconnected**. They serve legacy BC1.2/QC
negotiation; wiring them to `USB_DP`/`USB_DM` would corrupt the USB link needed
for NCM, R60 emulation and programming. PD runs entirely over CC.

## Rev A scope (2026-07-25): USB-C PD only, PoE deferred

| # | Decision | Chosen | Why |
|---|---|---|---|
| **H19** | **Rev A power** | **USB-C PD only** ✅ | the PoE module was the whole board's risk concentration: 56 × 14 mm (it would dominate a "small as practical" board), **not on LCSC** so JLCPCB cannot assemble it, hand-soldered, and its land pattern is not fab-confident. USB-C PD already delivers a negotiated 5 V / 3 W, which powers everything. Rev A therefore proves the entire protocol + firmware stack — the actual point of the project — with **no unconfirmed footprints and no hand-fit parts** |
| **H19a** | OR-ing diodes | **removed in rev A** ✅ | with one source there is nothing to OR. Keeping a Schottky cost ~0.35 V, leaving the ADM3053 only ~150 mV above its 4.5 V minimum and sagging isoPower. `VBUS → F101 → VCC_5V` direct. **Rev B reinstates OR-ing** (ideal-diode controller preferred over Schottky, to avoid the same drop) |
| **H19b** | Spare Ethernet pairs | **Bob Smith terminated** ✅ | with no PoE to tap, J401 pins 4/5 and 7/8 would otherwise dangle. R404/R405 (75 R) terminate them into the same `BOB_SMITH` node, so all four pairs are properly terminated — standard practice for a non-PoE port |
| **H19c** | Net naming | `POE_MODEA/B_*` → `ETH_CT_TD` / `ETH_CT_RD` / `ETH_SPARE_1/2` | a net called `POE_*` on a board with no PoE misleads a reviewer. These are the rev-B tap points and the note says so |

Deferred to rev B: U101 (Ag97005-FL), R105 (class programming), D103/D104 (OR-ing),
and the 57 V isolation zone. The magnetics centre taps stay accessible, so rev B
is a power-section change rather than a redesign.

### ERC is clean as of rev A

Zero errors. The six long-standing `power_pin_not_driven` errors were **correctly**
resolved with `PWR_FLAG`, not silenced: rev A's rails genuinely *are* driven, from
J102's VBUS pin, which is a *passive* connector pin — precisely the case `PWR_FLAG`
exists for. Flags on `VCC_5V`, `VCC_3V3`, `GND`, `VISO`, `CAN_GND` and `PD_VDD`
(the last is derived through R106, a passive resistor). Earlier refusal to add them
was right *at the time*, because the rails were genuinely undriven then.

### Blocker (rev B only): U101 cannot be placed, and its footprint cannot be drawn

Two independent problems, both now properly diagnosed.

**1. The symbol will not resolve — Konnect process cache.** Evidence: with the
library registered globally, `list_symbol_libraries` returns it (that call reads
`sym-lib-table` live from disk) while `add_schematic_component` reports
"Library 'dbcanary' not found" (that path uses a list cached at Konnect
**process** start). `ethercon-repeater`, registered in an earlier session, resolves
fine from the same table. MCP transport disconnect/reconnect does **not** clear it
— verified across three reconnects and two days. **Needs a genuine restart of the
Konnect MCP server process.**

**2. A separate Konnect bug made it worse.** `register_symbol_library` with
`scope: "project"` wrote a file whose root node is `(fp_lib_table` — a *footprint*
table header — into `hardware/sym-lib-table`. That invalid file made
`list_symbol_libraries` return 0 libraries. Removed (kept as
`broken-project-sym-lib-table.bak` in the scratchpad). Register globally instead.

**3. The land pattern is ambiguous — do not guess it.** Ag97000 datasheet Fig. 10
gives hole Ø `A` = 1.12 mm and pitch `B` = 2.54 mm, and `C` = 30.48 mm, but does
not label which features `C` spans. Ten pins at 2.54 mm pitch span 22.86 mm, not
30.48 mm, so there is an isolation gap of unstated position. The self-consistent
reading is a 13-position 2.54 mm grid with pins at indices 0–5 and 9–12 (gap =
4 × 2.54 = 10.16 mm), which matches the figure visually — **but Fig. 9 also gives
a body length of 56.01 mm, and a 30.48 mm pin span inside a 56 mm body is odd
enough that this is not fab-confident.** Resolve by measuring a physical part or
getting a confirmed land pattern from Silvertel before drawing the footprint.

### Resolved: the etherCON footprint is drawn from Neutrik's own DXF

`dbcanary:Neutrik_etherCON_NE8FBH`, in `hardware/lib/dbcanary.pretty/`. **Pad
geometry is exact, not estimated** — it came out of Neutrik drawing 20003890 rev D,
taking the DXF rather than reading the rendered PDF. Two things had to be handled:
the DXF is at the drawing's **3:1 scale** (the 8 signal holes appear as Ø2.4, and
2.4/3 = 0.8 mm ✓; the Ø22 body appears as Ø66), and **DXF Y is inverted** relative
to KiCad's.

Origin is the midpoint of the two 1.55 mm latch-post holes, which fall exactly on
±5.08 / ±4.445 — half of the drawing's 10.16 and 8.89 dimensions, which is a good
independent confirmation that the datum and scale are right.

| Feature | Geometry |
|---|---|
| Pins 1–8 | Ø0.8 mm drill, 1.4 mm pad, 2.54 mm pitch, two rows 2.54 mm apart, staggered 1.27 mm |
| `SH` (shield/gnd) | Ø1.2 mm drill, 1.8 mm pad, +2.16 mm from pin 1 (drawing: 2,16) |
| Latch posts ×2 | Ø1.55 mm **non-plated**, ±5.08 / ±4.445 |

Cross-checks against the drawing's own callouts all agree: 2.54 (3×), 1.27 stagger,
2.16 ground offset, 4.44 pin-1 offset, 10.16 and 8.89 latch spacing.

**Body outline is approximate** (front plate 25 × 25.6 mm, but its centre relative
to the latch datum is not given in the PCB view). That affects silkscreen and
courtyard only, never electrical correctness or the drill file. Drawing archived at
`hardware/lib/ne8fbh.pdf`.

Latch posts are deliberately **non-plated**: they are mechanical locating posts, and
plating them risks shorting the shell to whatever the hole touches.

### Resolved (2026-07-31): the two CH224K resistor values

Was open because the datasheet *text* states VDD and the VBUS sense pin each
"require a series resistor" without giving values. The **reference schematics**
do give them — §6.1, §6.2 and §6.3 of the CH224 manual — and all three agree:

| | Was | Now | Evidence |
|---|---|---|---|
| **R106** VBUS→VDD | 1 k | **1 k — unchanged** | all three reference schematics show 1 KΩ. VDD is an internal shunt regulator (VLDOK 3.24/3.3/3.36 V, 30 mA sink capability), so 1 k draws 1.7 mA at 5 V and 16.7 mA even at 20 V — in spec across the whole PD range. C109 = 1 µF matches the required decoupling. |
| **R107** VBUS sense (pin 8) | 100 k | **10 k** | all three reference schematics show 10 KΩ. 100 k was a 10× deviation with nothing recorded to justify it. |

Why R107 mattered enough to change rather than leave: pin 8 is an *analog
voltage-detection input* feeding the over-voltage module and PG, and **PD_PG is
wired to the MCU as a power-good input**. An under-read there is not cosmetic.
The change is a BOM swap with **no layout impact at all** — every copper, mask,
paste, silkscreen and edge-cut gerber layer was diffed old-vs-new and is
byte-identical, with only the drill files' creation timestamps differing.

It also *simplifies* the BOM: C25741 (100 k) had no other user and leaves
entirely, while R107 joins R104/R301 on C25744, so the design drops from 36
unique parts to 35.

Confirmed correct while checking, and worth keeping written down: **CFG1 tied to
VDD selects 5 V** (truth table row 1), and the datasheet explicitly warns that a
*floating* CFG1 requests 20 V — which is exactly why this board ties it in
copper rather than to a GPIO. The existing schematic note about that is right.

**Caveat:** the free-text "VERIFY BEFORE FAB" block on the power sheet still
says 100 k. The values are correct on both the schematic and the board; only
that prose is stale. Konnect has no tool for schematic text objects and hand-
editing a `.kicad_sch` risks UUID damage, so it was left for the next time the
sheet is open in Eeschema. Both parts now carry a `Verified` field recording
the answer.

### Resolved (2026-07-31): flash size was declared 4 MB on an 8 MB module

`CONFIG_ESPTOOLPY_FLASHSIZE` said 4 MB while the BOM module is an
**ESP32-S3-WROOM-1-N8** — 8 MB. `selftest` already encoded the right
expectation (`expect >= 8 MB for the -N8 module`) and would have failed that
check on a perfectly good board. Now **8 MB**.

The partition table is deliberately unchanged and still ends at `0x3E0000`, so
the extra 4 MB is simply unallocated. Growing `ota_0`/`ota_1` or adding a data
partition is a separate decision, and the app partition is currently 76 % free.

## Firmware: status indication (2026-07-26)

Written now, rather than after the prototypes arrive, because bring-up with no
indicators is serial-log-only — and the LEDs are the cheapest diagnostic on the
board.

| # | Decision | Chosen | Alternative | Why | Reversible? |
|---|---|---|---|---|---|
| **F1** | LED driver knows nothing about the system | `components/led` depends only on `board` + `driver`; the mapping lives in `main/status.c` | one component that reads `net`/`dbcan`/`bridge` directly | keeps the dependency arrow pointing one way, and makes the pattern maths testable in isolation | Trivial |
| **F2** | Pattern maths split into `led_patterns.c`, ESP-IDF-free | host-tested, 608 checks | eyeball it on the bench | there is no bench. A blink count that is wrong by one sends a technician to the wrong fault — this is exactly the class of thing to pin with tests | Trivial |
| **F3** | Tick is **25 ms**, not 20 | 40 ticks/s | 20 ms (50 ticks/s) | **corrected by the tests.** 4 Hz is a 250 ms period = 12.5 ticks at 20 ms; integer division rounded it to 12, so "4 Hz" ran at 4.17 Hz with a period that does not divide into a second, visibly beating against the 1 Hz pattern beside it. At 25 ms both 1 Hz and 4 Hz are whole ticks with exact even duty | Trivial |
| **F4** | Faults are communicated as **counted blinks** on D302 | 1 = no link, 2 = no lease, 3 = bus-off, 4 = CAN stopped | colour coding, or duty-cycle coding | a count is readable across a dark stage; there is only one red LED, and duty cycle is not something anyone reads reliably | Low |
| **F5** | ERR shows only the **most significant** fault | Ethernet outranks CAN | show all faults in sequence | without an address R1 cannot reach the unit at all, so the CAN state is moot until the network is up. A sequence of codes is unreadable | Low |
| **F6** | **Lamp test at start-up** | each LED in turn, then all three | go straight to live status | it is the one test that proves all three LEDs are fitted the right way round and on the right GPIOs — and the only visible sign of life during the 30 s DHCP wait. It is step A.6 of the functional test spec | Trivial |
| **F7** | LAN blinks **faster when worse** | off → 4 Hz → 1 Hz → solid | slower when worse | "still settling" should look urgent and "ready" should look calm | Trivial |
| **F8** | `led_start()` runs **before** networking | first thing after NVS | after the network is up | `net_start_eth()` blocks up to 30 s on DHCP. Starting the LEDs first means a board that fails to get a lease still proves it booted | Trivial |

Not covered by any of this: **D304 "ON"** is rail-driven through R305 and needs no
firmware, which is what makes it the only indicator a factory operator can use on
an unprogrammed board.

## Firmware: addressing (2026-09-21)

| # | Decision | Default (chosen) | Alternative | Why default | Reversible? |
|---|----------|------------------|-------------|-------------|-------------|
| **N1** | **Link-local when DHCP does not answer** | DHCP first, then RFC 3927 `169.254.x.x` via `CONFIG_LWIP_AUTOIP` (`TRIES=5`) | DHCP only (the original behaviour); a compile-time static IP | a converter is regularly plugged into a laptop and an amp network on an unmanaged switch, with nothing serving DHCP. The original build sat at 0.0.0.0 and was simply unusable there, which is a poor answer to an ordinary rig. Link-local is what every OS on that switch already does, so R1's machine self-assigns into the same range and the two find each other. DHCP still wins whenever a server exists: the two run cooperatively and a late lease replaces the link-local address | Trivial — one Kconfig line |
| **N2** | **No static IP of your own** | DHCP reservation if you need a fixed address | NVS-stored settings + a console or web UI to set them | unchanged from the original decision, and the reason is unchanged: the shipping image deliberately has no command surface on a show network. N1 removes the reason people wanted a static IP (an unusable box on a DHCP-less rig) without adding one | Low |
| **N3** | **LEDs do not distinguish a lease from link-local** | "address held" covers both | a distinct LAN pattern, or a persistent ERR code, for link-local | either address is a working converter, and an ERR code that fires on a perfectly good DHCP-less rig trains people to ignore ERR. The boot log names which one is held, and R1's scan list shows the address | Trivial |

**Unverified.** None of it has lit a real LED.

## Hardware (added 2026-07-22, phase start)

| # | Decision | Default (chosen) | Alternative | Why default | Reversible? |
|---|----------|------------------|-------------|-------------|-------------|
| **H1** | **Ethernet** | **one port, single RMII PHY** ✅ | 2-port KSZ8863 switch (nanODE-style daisy chain) | matches the real R70, which has one LAN jack; far less board and no switch-clock complication. The unit lives in an amp rack that already has a switch | Medium — architectural |
| ~~H2~~ | ~~RMII clock, 50 MHz XO~~ | — | — | **superseded by H15** — no RMII, so no oscillator. Good riddance: it was the most EMC-critical net on the board | — |
| ~~H3~~ | ~~PHY LAN8720A~~ | — | — | **superseded by H15** — W5500 over SPI | — |
| **H4** | **CAN front end** | **ADM3053** ✅ | ISO1042 + separate isolated rail; TJA1051 non-isolated | transceiver + isoPower DC-DC + digital isolation in one part — removes an entire isolated supply sub-circuit. Same philosophy as nanODE's ADM2587E | Chosen |
| **H5** | CAN rails | **VCC = 5 V, VIO = 3.3 V** | VIO = 5 V + level shifting | ADM3053 requires 5 V on VCC; VIO at 3.3 V talks to the ESP32 directly with no shifting | No — part requirement |
| **H6** | **Connectors** | **Neutrik etherCON, shielded** ✅ | plain shielded RJ45 (what the R70 uses) | user choice; touring-hardened. Compatible either way — etherCON accepts a plain RJ45 plug, so real d&b amps still patch in | Chosen |
| **H6a** | **etherCON variant** | **NE8FBH (B-series, PCB mount)** ✅ | ~~NE8FDP (D-series)~~ | **correction.** NE8FDP is a panel-mount *feedthrough*: its rear is a female RJ45 socket, so it does not solder to a PCB at all and would need an internal patch lead per connector — absurd for a 3-connector board. NE8FBH is the horizontal PCB-mount B-series part. Trade-off: B-series front plate is less rugged than D-series | Chosen |
| **H7** | CAN ports | 2, **wired in parallel** | 1 | exactly what the R70 does, so amps daisy-chain. TI 312: pin 4 CAN_H, pin 5 CAN_L, **shell = CAN ground** — shielded shells are mandatory, not optional | No — protocol |
| **H8** | Termination | switchable 120 Ω + status LED | fixed, or none | copies the R70's front-panel switch; the bus may only ever have two terminators | Low |
| ~~H9~~ | ~~Power in~~ | ~~PoE + DC 10–30 V~~ | — | **superseded by H17**: PoE + USB-C, no barrel | — |
| **H10** | PD module | Silvertel **Ag97005-FL** (5 V, 9 W, SIL) ✅ | ~~Ag5712-LPB (12 V, 30 W)~~; Si3402-B + flyback | **revised.** Ag5712-LPB is a 30 W module for a 3 W board. Ag97005-FL is right-sized, has an **integrated bridge rectifier** (saves 8 diodes), 1500 Vdc isolation, and outputs **5 V directly** — which is exactly what the ADM3053 needs, deleting a conversion stage. Still hand-fit (not on LCSC) | Chosen |
| **H10a** | PoE class | **Class 2**, R105 = 383 R 1% | Class 1 (698 R), Class 0 (open) | measured budget ~3 W peak. Class 1 gives only 3.84 W — too tight once WiFi transmits. Class 0 asks a PSE for 15.4 W we never use | Low |
| **H11** | Rails | PoE → **5 V direct**; barrel → buck → 5 V; 5 V → buck → 3.3 V ✅ | 12 V intermediate rail | the 5 V PD output feeds the ADM3053 and the 3V3 buck with no intermediate rail at all | Chosen |
| **H11a** | Buck | **AP63200WU** (adjustable) for BOTH rails | AP63205WU / AP63203WU (fixed) | one part number, output set by divider. Critically, the fixed variants are `extends` aliases that Konnect resolves to **zero pins** — wiring them would silently connect nothing. LCSC C2071868, in JLCPCB's library | Chosen |
| ~~H11b~~ | ~~DC input range 12–24 V~~ | — | — | **moot under H17** — there is no barrel jack, and both sources are 5 V | — |
| **H12** | **Layers** | **4** ✅ | 2 (the Konnect user default) | 50 MHz RMII needs a solid reference plane, and there are two isolation barriers to keep clear. 2-layer is not viable here | No — physics |
| H13 | Indicators | LAN, ERR, CAN, ON, TERMINATE | fewer | mirrors the R70's front panel, so a d&b tech reads it without a manual | Trivial |

## Open hardware questions

- **Isolation barrier width.** ADM3053 is rated for basic isolation; creepage under the part must be respected and no copper (including ground pour) may cross the barrier. Needs a keepout, not just care.
- **PoE class.** We need roughly 3 W, so Class 1 would do; Ag5712-LPB is Class 4. Fine electrically, but a smaller/cheaper PD is worth revisiting.
- **Enclosure.** Not chosen. The R70 is 115×110×35 mm extruded aluminium; etherCON jacks are deeper than plain RJ45 and will drive the depth.

## Resolved

- **UDP 33333 payload** — solved. Documented from captures of R1's discovery
  traffic and confirmed live against R1. 4-byte header + 64-byte records; R1
  accepts an answer as long as byte 2 (the opcode) is `0x00`. See PROTOCOL.md §4.
- **Does R1 filter on the MAC?** **No.** R1 takes the MAC from the record without
  checking its OUI, and ignores the UDP sender address entirely. Shipping hardware can use its own MAC — we do not need to
  borrow RM Michaelides' IAB range. This removes the identity problem.

## Open questions

- **Which `service` value is TCP-server?** Only `1` and `2` are accepted;
  we advertise `1`. If R1 lists the interface as a
  client rather than a server, flip to `2` (`--service 2`).
- **HTTP config page.** R1 also drives the R70's web UI for the Properties pane —
  device info, LAN parameters, restart/restore. A convincing emulator has to
  serve pages R1 can scrape. Unscoped; not needed for a CAN data path.
- **Timestamp mode** — whether R1 enables `0x01`/`0x03` timestamped frames and
  what clock base it expects. Visible once R1 connects on TCP 30000.

## Deliberately out of scope

- d&b amplifier parameter semantics (EQ, gain, routing, mute). R1 generates these
  and the amplifiers consume them; a bridge just carries bytes. Revisit only if
  D1 ever changes.
- Amplifier firmware update over CAN. TI 312 says the remote network supports it;
  a transparent bridge should carry it, but it is a high-risk path to claim
  support for without an amplifier to test against.
