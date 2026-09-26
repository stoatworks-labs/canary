# Bring-up log — rev A board #1 (serial 0001)

| | |
|---|---|
| Date | 2026-09-09 |
| Board | rev A, the rev A PCBWay order, fabbed and assembled from commit `d9a725d` |
| Firmware | branch `fix/usb-pair-and-script-paths` @ `b299d92`, plus the two fixes below |
| Operator | Stoatworks Labs (with Claude driving the bench tooling) |
| Procedure | [`BENCH-BRINGUP.md`](BENCH-BRINGUP.md) — **§1 through §4 were skipped**, see below |

**This is the first time this firmware has ever executed on hardware.** Everything
below is a first observation, not a repeat measurement.

---

## 0. What was skipped, and why it matters

The board went **straight to USB-C power**. The current-limited bench-supply
sequence (§2), the rail measurements (§3) and the PD comparison (§4) were not
done. Nothing was harmed, but the consequence is that **most of Appendix C's
minimum record is still empty for this board**, and several of the document's
open questions stay open. If board #2 is brought up, do §1–§4 on that one — the
numbers are worth having once.

Also not done: isolation resistance (§9), CAN against a real bus (§8.3), the LED
polarity check (§6.3), and the two-jack test (§8.4).

---

## 1. Identity

| Field | Value |
|---|---|
| Chip | ESP32-S3 (QFN56) revision **v0.2**, 2 cores |
| Crystal | 40 MHz |
| Flash | **8 MB** detected, manufacturer `0x20`, device `0x4017` |
| eFuse MAC (base) | `50:78:7D:0E:39:B0` |
| Ethernet MAC (`ESP_MAC_ETH`) | `50:78:7D:0E:39:B3` |
| DHCP address | 192.0.2.27/24, gateway 192.0.2.1 |
| USB device | Espressif "USB JTAG/serial debug unit", VID `0x303A` PID `0x1001`, `/dev/cu.usbmodem2101` |

---

## 2. The headline result: USB works on the pre-fix routing

**This was the single biggest risk on this board and it is now retired.**

These boards were fabbed from `d9a725d`, which predates the 2026-08-22
differential-pair re-route. `USB_DP`/`USB_DM` are two uncoupled traces 9.5 mm
apart with roughly 16 mm of length mismatch, and J102 is the *only* power path as
well as the only programming path. The bring-up doc says to have a 3.3 V
USB-serial adapter ready for J301 in case it would not enumerate.

It was not needed. The board enumerated on the first plug-in, with no BOOT/RESET
button sequence, and flashed at ~1.6 Mbit/s with every segment hash verified.
Repeated flashes and console sessions over the same cable were reliable all
session.

> J301 is **not fitted** on these boards (it is a DNP), so if a later board does
> fail to enumerate, the UART fallback needs a 1×6 1.27 mm header soldered on
> first. Do not assume the fallback is available.

---

## 3. On-board self-test

Self-test image built with `idf.py -B build-selftest build -DDBCANARY_SELFTEST=1`
and flashed over USB-C. Result at boot and, after the fix in §5, twice more from
the console prompt:

```
RESULT chip            INFO  ESP32-S3 rev v0.2, 2 core(s), idf v5.5.5
RESULT flash.size      PASS  8 MB
RESULT mac.eth         PASS  50:78:7D:0E:39:B3
RESULT reset.reason    INFO  usb
RESULT pd.pg           INFO  GPIO18 reads 0 (polarity unverified)
RESULT eth.versionr    PASS  0x04 at 4 MHz
RESULT eth.regwalk     PASS  wrote 5AA5 to RTR, read 5AA5
RESULT eth.versionr.fast PASS 0x04 at 20 MHz
RESULT can.loopback    PASS  8-byte frame round-tripped (tx_err=0 rx_err=0)
RESULT led.walk        INFO  GPIO15/16/17 driven, active level 1 - confirm by eye
SELFTEST-END pass=6 fail=0 skip=0 info=4
```

Three of those are worth calling out:

- **`eth.versionr.fast` passing answers open question 5.** The W5500 reads
  `0x04` at the full 20 MHz application clock on un-length-matched SPI routing.
  It also passes at 4 MHz, and `eth.regwalk` proves MOSI specifically, so the
  SPI link is good in both directions at both speeds.
- **`can.loopback` passing proves the isolated side started.** The frame goes
  GPIO4 → ADM3053 → across the barrier → CANH/CANL → back → GPIO5, with zero
  TX and RX errors. That is the only check that exercises the isolated DC-DC,
  and it cannot be observed from the system domain any other way.
- **`pd.pg` reads 0 with a PD supply attached.** Open question 3 stays open:
  without the bench-supply comparison from §3.14 there is nothing to compare it
  against, so the polarity is still unknown.

---

## 4. Product image on the network

Flashed and booted clean, no reboot observed over a 50 s capture.

```
net:    W5500 on SPI2 sck=12 mosi=11 miso=13 cs=10 int=14 rst=9 @ 20 MHz
net:    link up                                    (2.2 s after boot)
netif:  eth ip: 192.0.2.27, mask 255.255.255.0, gw 192.0.2.1
dbcan:  dbCAN up at 100 kbit/s on TX=4 RX=5
bridge: discovery listening on UDP 33333
bridge: data socket listening on TCP 30000
status: all indicators nominal: link up, address held, CAN running
```

**With no cable plugged in**, DHCP times out after a full 30 s and the firmware
logs that R1 will not be able to reach it, then starts the bridge anyway. That is
by design, but on the bench it means half a minute of apparent silence before
anything happens. Do not read it as a hang.

### Host-side acceptance run

`tools/board_test.py --serial-number 0001 --skip console` — **19 passed, 0 failed,
1 skipped**. The skip is the CAN wire, which needs an isolated adapter.

Discovery answered with 260 bytes carrying the correct opcode, the `R70 ` tag and
4 unique socket records; the advertised IP matched the address it answered from;
the full RM Byte Command Protocol walk succeeded on TCP 30000 including both
commands that must go *unanswered*. From the board's own side:

```
bridge: answered discovery from 192.0.2.90
bridge: R1 connected from 192.0.2.90
bridge: R1 disconnected (0 malformed frames)
```

Record saved as the `board_test.py` JSON for Appendix C. Note its
`board_selftest` section is empty, because the console stage only works against
the self-test image — see §7.

---

## 5. Firmware bug found and fixed: self-test console stack

**Symptom.** Typing `selftest` at the `dbcanary>` prompt panicked the board every
time, with a corrupted backtrace:

```
Guru Meditation Error: Core 1 panic'ed (LoadProhibited)
PC 0x4037d8be  A2 0xa5a5a5a5  A3 0xa5a5a5a5   <- prvSelectHighestPriorityTaskSMP
Backtrace: ... 0x4037d0b6:0xa5a5a5a5 |<-CORRUPTED
```

**Cause.** `cmd_selftest` puts a `selftest_report_t` on its caller's stack —
24 results × (name + 72-byte detail + verdict), about 2 KB — and the SPI and TWAI
driver frames sit under it. The console REPL task gets
`ESP_CONSOLE_REPL_CONFIG_DEFAULT`'s **4096 bytes**, so it ran past the canary and
into the heap. `0xa5a5a5a5` is FreeRTOS's fill pattern, and the scheduler died
reading a TCB pointer out of memory something had already walked over.

**Why nothing caught it.** `app_main` runs the identical code on the 6 KB main
task, where it fits. Boot-time self-test, 739 host checks, the QEMU boot and the
`--simulate` run had all passed. **Nothing before this session had ever typed the
command at the prompt.**

**Fix.** REPL task stack raised to 8192, sized like the main task with headroom.
Committed as `16c1826`. Verified by running `selftest` twice consecutively from
the prompt: 6 passed 0 failed each, JSON report emitted, no panic.

A second commit, `407dd3c`, landed the console-on-USB-Serial-JTAG change that had
been sitting uncommitted since August. Without it a fresh clone builds a REPL that
echoes to USB-C but reads input from UART0 on the unfitted J301 — a prompt that
ignores you, which reads exactly like a dead board.

---

## 6. Firmware bug found and NOT fixed: we advertise ourselves as a UDP client

**This one is open and is the next thing to do.**

R1 V3.46.1 **does** discover the board. It is listed in *Devices > Interfaces* as
model `R70` at 192.0.2.27 with a green status. (It is absent from the *Devices*
tab, which is the easy way to conclude wrongly that nothing was found.)

But R1 names it:

```
db-70-UDP-CLIENT-30000
```

R1 composes that label as `<hostname>-<protocol>-<service>-<port>` from the
discovery record. So R1 is reading our socket as **UDP** and **CLIENT**, while the
bridge actually listens as a **TCP server** on port 30000.

**Root cause.** `components/r70_ddt/include/r70_ddt.h` and `tools/r70_ddt.py` both
define `SERVICE_SERVER = 1` and `PROTOCOL_TCP = 1`. Those were derived from which
values R1 accepts, without ever pinning down what each accepted value *means* —
and R1's own label says wire value 1 is **CLIENT**.

**Proved empirically, not inferred.** Ran the emulator alongside the live board:

```bash
tools/r70_emu.py serve --host-name PROBE-S2P0 --answer-from 192.0.2.90 \
                       --service 2 --protocol 0
```

R1 listed the two side by side:

| Model | Name | Port |
|---|---|---|
| R70 | `db-70-UDP-CLIENT-30000` | 192.0.2.27 (the board) |
| R70 | `PROBE-S2P0-TCP-SERVER-30000` | 192.0.2.90 (the emulator) |

So **SERVER is wire value 2, and TCP is wire value 0.**

**Why this is not cosmetic.** The protocol field decides which kind of socket R1
opens. As it stands, R1 is being told to talk UDP to a board that only
accepts TCP.

**What a fix has to touch — all four encode the old values:**

1. `firmware/components/r70_ddt/include/r70_ddt.h` — the two constants
2. `tools/r70_ddt.py` — the Python mirror
3. `docs/PROTOCOL.md` §4 — the derived mapping table and its `[derived]` claims
4. `tools/board_test.py` — the `discover.record-filter` assertion currently
   *checks for* `service=1 protocol=1`, so it will keep passing on the wrong
   values until it is updated

When changing it, **verify by reading R1's own label, not by reasoning about the
mapping.** That is what turned this from a suspicion into a fact.

---

## 7. The other reason nothing appears: R1 must be Offline to activate an interface

Separate from §6, and it bites first. The **Active** checkbox on the R70 row is
greyed out while R1 is Online, and R1 was Online. Until it is ticked there is no
bus scan, so the *Devices* tab stays empty no matter how healthy the interface is.

This is the trap already documented in `docs/USER-GUIDE.md` §5: go **Offline**,
tick **Active**, then back **Online**. It was not done in this session because
going Offline would have dropped R1's live OCA interface, and what was attached to
it was unknown.

**So the end-to-end path is still unproven.** R1 discovering and listing the board
is confirmed; R1 actually connecting, initialising the gateway and scanning the
bus is not.

---

## 8. How R1 actually scans (measured, not assumed)

Captured on the wire with `tcpdump -i en0 'udp port 33333'`:

- R1 rescans **every 60 seconds** on its own, as well as on the Scan button.
- It sends **one 68-byte probe per local IPv4 address**. On the test Mac that was
  six probes, one per address (LAN, VM bridges, VPN overlays).
- Probes go to `255.255.255.255:33333` from an **ephemeral source port**. R1 does
  *not* bind 33333, which is why a local emulator can hold that port without
  breaking R1's discovery.
- Exactly one probe was answered — the one from `192.0.2.90`, the address on the
  board's own subnet. The board replied 260 bytes to that ephemeral port.

**Why only one.** The firmware unicasts its answer back to the probe's source
address. A probe sourced from an off-subnet address (a second address on the
same adapter, VM bridges, a VPN overlay) gets an answer sent off toward the default gateway,
where it dies. This is correct behaviour and it did not cause a problem here,
because R1 probes from every address and only needs one to come back — but it is
worth knowing before blaming the board on a multi-homed machine.

> A stray hand-added second address on the host's LAN adapter (especially one
> with a malformed broadcast) is harmless here, but it is the kind of thing that
> makes discovery look flaky.

---

## 9. Bench traps learned this session

- **Opening the USB serial port resets the board.** `rst:0x15 USB_UART_CHIP_RESET`
  appears even with DTR and RTS held low on open. There is no such thing as a
  passive serial capture on this hardware — any attempt to "just watch" restarts
  what you are watching.
- **`board_test.py`'s console stage only works against the self-test image.** A
  product-image run must pass `--skip console`, and its record will carry an empty
  `board_selftest` section. A full Appendix C record therefore needs *two* runs,
  or the self-test JSON captured separately.
- **ESP-IDF's `export.sh` fails on this Mac.** Homebrew's `python3` is now 3.14
  and the script looks for a `idf5.5_py3.14_env` that does not exist; only
  `idf5.5_py3.12_env` is installed. Point it at the right venv:
  ```bash
  export IDF_PYTHON_ENV_PATH=~/.espressif/python_env/idf5.5_py3.12_env
  . ~/esp/esp-idf/export.sh
  ```
  Redirect, never pipe — `. export.sh | tail` sources it in a subshell and the
  PATH change is silently lost.
- **The coredump partition holds a stale dump across reflashes.** After the §5
  panic, every subsequent boot logged `previous boot panicked` until the region
  was erased with `esptool.py erase_region 0x3c0000 0x20000`.

---

## 10. Appendix C record status

| Field | Status |
|---|---|
| Serial, date, operator | recorded above |
| Idle current on the bench supply | **not measured** — §2 skipped |
| VBUS_RAW, VCC_5V, VCC_3V3, FB2 | **not measured** — §3 skipped |
| VISO (to CAN_GND) | **not measured**, but `can.loopback` proves the isolated rail runs |
| PD_PG, bench **and** PD supply | PD supply only: GPIO18 reads 0. Polarity still unknown |
| W5500 VERSIONR at 4 and 20 MHz | `0x04` at both — **recorded** |
| LED polarity (`led lan on` → D301?) | **not checked** — needs eyes on the board |
| CAN termination, both switch positions | **not measured** |
| Isolation resistance | **not measured** |
| `board_test.py` JSON record | **recorded**, 19/19 network stages |

### Open questions from BENCH-BRINGUP Appendix C

| # | Question | Answer from board #1 |
|---|---|---|
| 1 | Real idle current | **still open** |
| 2 | Which way round are the LEDs | **still open** |
| 3 | What does PD_PG do, in which polarity | **still open** — one data point, nothing to compare it to |
| 4 | ETH_VBG / ETH_TOCAP where we guessed | **still open** |
| 5 | W5500 at 20 MHz on un-length-matched routing | **YES — works, `0x04` at 20 MHz** |
| 6 | Does floating `ETH_RSTn` cause anything odd | no misbehaviour seen at boot; unconfirmed without the idle-current figure |
| 7 | Does anything care that CHASSIS is not bonded | **still open** |
| — | *(new)* Does USB survive the pre-fix routing | **YES — enumerated first time, flashed reliably all session** |

---

## 11. Next actions

1. **Fix the service/protocol values** (§6) across the four places listed, then
   confirm against R1 by reading the label.
2. **Do the Offline → tick Active → Online sequence** and find out whether R1
   initialises the gateway and scans the bus. This is the last unproven link in
   the whole chain.
3. **CAN against a real bus** (§8.3) — needs an **isolated** adapter. A
   non-isolated one bridges the barrier and turns a good board into scrap that
   still passes every functional test.
4. **LED polarity and PD_PG** — both need a person looking at the board.
5. **Bring up board #2 properly through §1–§4** so the parametric record exists
   at least once.
