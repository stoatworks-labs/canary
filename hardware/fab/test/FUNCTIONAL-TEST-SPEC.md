# dbCANary rev A — Functional Test Specification

| | |
|---|---|
| Product | dbCANary rev A — ESP32-S3 IP-to-CAN converter |
| Board | 100 × 81 mm, 4-layer |
| Document | FTS-DBCANARY-A, **revision 0.1 — DRAFT** |
| Status | partly executed on board #1 (see [BRINGUP-LOG-0001.md](BRINGUP-LOG-0001.md)); the CAN-bus sections never |

> **Read before use.** No dbCANary board exists yet. Every limit below is
> predicted from the design, not measured. The first article tests this
> document as much as it tests the board. Re-issue as revision A, with real
> measured limits, before using it for production acceptance.

This document is in two parts:

- **Part A** — for JLCPCB's Functional Test Service. A human operator follows
  it with no special equipment. **This is the part to attach to the order.**
- **Part B** — in-house bring-up and acceptance. Needs equipment a contract
  assembler does not have. **Do not send Part B to JLCPCB.**

---

## 0. Constraints that shape everything below

**0.1 — There is a galvanic isolation barrier.** U201 (ADM3053) splits the
board into a system domain (GND) and an isolated CAN domain (CAN_GND / VISO).
Minimum copper spacing between them is **8.50 mm**. **No fixture, probe,
ground clip or shared rail may connect GND to CAN_GND.** A board with a bridged
barrier passes every functional test and is still scrap.

**0.2 — CHASSIS is a third domain and is *not* isolated to the same degree.**
Minimum GND-to-CHASSIS spacing is **1.15 mm**, at J102's USB-C shell — normal
for a USB shell. Consequence: **never hipot GND ↔ CHASSIS.** It will break down
at the USB connector and tell you nothing. Hipot GND ↔ CAN_GND instead (B.4).

**0.3 — There are no test points.** No `TP*` pads exist. All probing is on
component pads and vias; see `NETLIST-CROSSREF.csv`. Test points are on the
rev B list.

**0.4 — Only one LED works without firmware.** D304 "ON" is driven directly
from the 3V3 rail through R305. D301/D302/D303 are ESP32-S3 GPIO-driven; the
firmware runs a lamp test on them at start-up (A.6), so they light **only on a
programmed board** and stay dark otherwise.

---

# PART A — JLCPCB Functional Test Service

**Scope: an operator with a USB-C PD power supply and no other equipment.**
Estimated 60–90 seconds per board.

If JLCPCB's **Programming Service** is also purchased and firmware is flashed
before this test, add steps A.6–A.8. If not, skip them — they cannot pass on
an unprogrammed board, and an operator will report a false failure.

### Equipment the operator needs

- USB-C power supply, 5 V, with a current display (a USB power meter is ideal)
- Nothing else

### Setup

Board loose on an ESD-safe surface. **Do not attach anything to the two CAN
etherCON jacks (J201, J202)** — those connect to the isolated domain.
Note that all three etherCON jacks are hand-soldered and may not be fitted.

| Step | Action | Pass | Fail action |
|---|---|---|---|
| **A.1** | Visually inspect U301, U401, U201, U104 | no solder bridges, no tombstoned parts, no missing parts | reject, photograph |
| **A.2** | Plug USB-C into J102 | board draws current | if 0 mA or supply trips → reject |
| **A.3** | Read supply current, board idle | **> 5 mA and < 400 mA** | outside range → reject |
| **A.4** | Observe **D304** (green LED, marked ON) | **lit steadily** | not lit → reject |
| **A.5** | Feel U103, U104, U201, U401 after 30 s | none uncomfortably hot | any part hot → reject immediately |

**A.3 note:** the < 400 mA upper limit is deliberately loose because it has
never been measured. It is there to catch a hard short, not to grade the board.
Tighten it once real boards exist.

**A.4 is the single most valuable step.** D304 lighting proves: USB-C
connector soldered, PD sink (U104) negotiating, PTC (F101) intact, buck
converter (U103) running, and the 3V3 rail up.

### Only if firmware has been programmed

| Step | Action | Pass |
|---|---|---|
| **A.6** | Wait 10 s after power-up | D301, D302, D303 each blink at least once during the startup lamp test |
| **A.7** | Press **SW301** (RESET) | LEDs restart their startup sequence |
| **A.8** | Press **SW302** (BOOT) and release | no visible change (correct — it is only read at reset) |

### Recording

For each board record: serial/date code, idle current from A.3, pass/fail, and
operator ID. Photograph any board that fails.

### What Part A does NOT prove

Ethernet, CAN, the isolation barrier, PD profile negotiation, and the W5500
are all untested by Part A. They need Part B.

---

# PART B — In-house bring-up and acceptance

**Do not send this section to JLCPCB.** It needs equipment they do not have,
and B.4 can damage a board if done wrong.

### Equipment

| Item | For |
|---|---|
| Host PC + USB-C cable | flashing, serial, Ethernet peer |
| Ethernet cable, host NIC or switch | B.3 |
| **Galvanically isolated** USB-CAN adapter | B.5 |
| RJ45 → etherCON patch leads ×3 | connector access |
| DMM | rails |
| Insulation tester, 500 V DC | B.4 (sample basis only) |

> The CAN adapter **must** be isolated. A non-isolated one ties CAN_GND to the
> host ground and defeats the barrier being tested.

### B.1 — Rails

| Step | Probe | Expect |
|---|---|---|
| B.1.1 | VCC_3V3 at R301.1 | 3.3 V ± 5 % (3.14–3.47 V) |
| B.1.2 | VCC_5V at C107.1 | 5.0 V ± 5 % |
| B.1.3 | CAN_GND (C206.2) to GND (C107.2), DMM resistance | **open circuit** |

B.1.3 failing means the barrier is bridged — quarantine the board.

### B.2 — Programming and boot

The ESP32-S3 has native USB, so J102 is both power and programming port.

| Step | Action | Expect |
|---|---|---|
| B.2.1 | Hold SW302 (BOOT), tap SW301 (RESET), release SW302 | enumerates in ROM download mode |
| B.2.2 | Flash firmware over USB | completes without timeout |
| B.2.3 | Tap SW301 | firmware runs, banner on USB CDC or J301 UART0 |

J301 (1 × 6, 1.27 mm): `GND, VCC_3V3, UART0_TXD, UART0_RXD, BOOT, EN`. Use it
when USB enumeration itself is the suspect.

### B.3 — Ethernet

| Step | Expect |
|---|---|
| B.3.1 | SPI read of W5500 VERSIONR (0x0039) returns **0x04** |
| B.3.2 | Patch J401 to a host NIC — link comes up and **D301 changes from off to blinking**, D302 stops showing 1 blink |
| B.3.3 | Ping the board's test IP — 100 packets, 0 % loss |
| B.3.4 | Once a lease is held, **D301 slows to 1 Hz and D302 goes dark**. Open an R1 session — D301 goes steady |

B.3.2 and B.3.4 are free: the LEDs report link, lease and R1-connected states
directly, so a wiring fault is distinguishable from a DHCP fault without a
serial console. Fault-code table in the README.

B.3.1 is the highest-value single test on the board: it proves the SPI bus,
the W5500's supply, its 25 MHz crystal (Y401) and the reset line in one read.

### B.4 — Isolation (sample basis, before anything else is connected)

| Parameter | Value |
|---|---|
| Between | **GND** (C107.2) and **CAN_GND** (C206.2) |
| Test | 500 V DC insulation resistance |
| Pass | **> 100 MΩ** |
| **Never test** | GND ↔ CHASSIS — 1.15 mm at the USB-C shell (see 0.2) |

The ADM3053 is rated 2.5 kV RMS for 1 minute; the PCB provides 8.50 mm. A
500 V screen catches assembly defects — solder splash, flux residue,
contamination across the barrier. It is not a type test of the part.

### B.5 — CAN

J201 and J202 are the **same** bus in parallel for daisy-chaining, so a frame
into one must appear at the other. **dbCAN is 100 kbit/s fixed** — testing at
any other rate proves nothing about the application.

| Step | Expect |
|---|---|
| B.5.1 | Isolated adapter on J201 at 100 kbit/s — bus idle, no error frames |
| B.5.2 | Firmware transmits a known frame — adapter receives it, ID and payload correct |
| B.5.3 | Adapter transmits — firmware echoes, no bus-off |
| B.5.4 | Move adapter to J202, repeat B.5.2 — proves the second jack |
| B.5.5 | SW201 TERMINATED → ≈ 60 Ω across CANH/CANL with the adapter's 120 Ω |
| B.5.6 | SW201 UNTERMINATED → ≈ 120 Ω |

### B.6 — USB-PD

| Step | Expect |
|---|---|
| B.6.1 | PD_PG (U104 pin 10) asserted when VBUS good |
| B.6.2 | Negotiated profile is 5 V |

---

## Acceptance and traceability

A board is accepted only when Part A and Part B both pass. Log **parametric
values, not just pass/fail**, keyed to serial number:

- idle current (A.3), VCC_3V3 (B.1.1), VCC_5V (B.1.2)
- W5500 VERSIONR (B.3.1)
- isolation resistance (B.4) where sampled
- firmware version, test station, operator, timestamp

Any failure of A.4, B.1.3 or B.4 is an **isolation or power** failure:
quarantine, do not return to stock without full re-test. A partially bridged
isolation barrier is the one defect that is invisible in normal operation.

---

## Known gaps

- Nothing here has been executed; no board exists.
- Current limits (A.3) are predicted, not measured — deliberately loose.
- No test fixture exists. Probe points are named; no pogo layout is drawn.
- No test points on the board; probing is on component pads.

### Closed since revision 0.1 (2026-07-27)

- **The test firmware referenced in A.6 and B.2 now exists.**
  `firmware/components/selftest/` builds with
  `idf.py -B build-selftest build -DDBCANARY_SELFTEST=1` and gives a board-side
  self-test plus a command console. It has still never run on hardware.
- **Part B is superseded in-house by [`BENCH-BRINGUP.md`](BENCH-BRINGUP.md)** —
  the same checks in step-by-step form, with derived expected values, annotated
  board drawings and instrument-specific appendices. Part B stays here because
  it is the short form that belongs beside Part A; where the two differ,
  BENCH-BRINGUP.md is the one that was worked through.
- **A host-side acceptance test exists**: `tools/board_test.py`, which also
  runs against the emulator with `--simulate`, so the runner is proven before
  any board arrives.

### One correction to Part A

**A.6 was written assuming ACTIVE LOW status LEDs, and that is now believed to
be wrong.** `board.h` was corrected to ACTIVE HIGH on 2026-07-27 after
re-deriving the connection from the board file; see BENCH-BRINGUP.md §6.3.
A.6 only asks the operator to see each LED blink, so the step still works
either way — but do not take the polarity from this document.
