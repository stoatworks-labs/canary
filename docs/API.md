# CANary — interfaces

What a CANary exposes, and what the tooling exposes. This is the **implementation** side:
what the firmware actually answers, in what shape.

For the wire format itself — frame layout, checksums, the derivation of the discovery
handshake, the dbCAN identifier packing, provenance of every claim — read
**[PROTOCOL.md](PROTOCOL.md)** first. It is not repeated here.

> Everything below is read from the source and verified on a host, against a real R1 (V3.46)
> talking to the *Python emulator* in `tools/`, and on rev A board #1 (discovery, the TCP session,
> the LEDs' logic, the USB network link), and on 2026-10-28 carrying CAN to two real amplifiers
> and back (bring-up log §12). **The firmware here recovers from bus-off only on `0x58`** (§1),
> which the control application never sent, so after a CAN cable pull that day the CAN side
> stayed deaf until the board was reset.

| § | Interface | Source |
|---|---|---|
| [1](#1-rmbcp-on-tcp-30000) | RMBCP command set, as implemented | `firmware/components/bridge/bridge.c` |
| [2](#2-discovery-on-udp-33333) | Discovery answer fields | `firmware/components/r70_ddt/` |
| [3](#3-the-can-side) | dbCAN forwarding | `firmware/components/dbcan/` |
| [4](#4-status-leds) | Status LEDs | `firmware/components/led/`, `main/status.c` |
| [5](#5-self-test-console) | Self-test console (test build only) | `firmware/components/selftest/` |
| [6](#6-host-tools) | Host tools | `tools/` |

> **There is no authentication on anything.** Not on TCP 30000, not on UDP 33333, not on the
> serial console. Anyone who can reach the bridge on the network can open a socket and inject
> arbitrary CAN frames onto the amplifier bus. A real R70 is the same, but a real R70 is
> normally on a locked-down show network — put this one there too.

---

## 1. RMBCP on TCP 30000

Four sockets, base port **30000** (socket 1 = 30000, socket *n* = 30000 + n − 1).

Frames arriving as CAN messages (`0x00`–`0x03`) are unwrapped and transmitted straight onto the
bus with a 20 ms transmit timeout. Everything else is a gateway command, handled as follows.

| Cmd | Name | CANary's answer |
|---|---|---|
| `0x00`–`0x03` | CAN 11/29-bit, ±timestamp | **Forwarded to the bus**, not answered |
| `0x40` | Device ID | `"<host>-TCP-<port>"` NUL-terminated, then the 6 MAC bytes |
| `0x41` | Version | fixed `01 00 00 01 00 01` — HW/FW/bootloader, 16-bit each. **Ours, not a real R70's.** |
| `0x42` | Error status | fixed `00 00` — always "no error" |
| `0x44` | Interface version | **deliberately unanswered** |
| `0x47` | Bus load | live figure from `dbcan_busload()`, 16-bit big-endian |
| `0x56` | Baud request | always `0xFE` (100 kbit/s) |
| `0x57` | Baud set | always `0xFE`, **whatever was asked for** |
| `0x58` | CAN reset | runs bus-off recovery, then answers with an empty frame |
| `0xA3` | Block time | **echoed back verbatim** — the value is not applied |
| `0xA4` | Baud calculation | **deliberately unanswered** |
| `0xC0` | Reset device | answers with the **Device ID** (`0x40`), and does **not** reboot |
| anything else | | ignored, logged at debug |

Four of those rows are the load-bearing ones:

**`0x44` and `0xA4` must stay silent.** R1 sends both during initialisation and proceeds
without a reply. When the emulator started *answering* them during bring-up, **R1 stopped** —
the silence is part of the contract, not an unimplemented gap. Do not "fix" this by adding
replies. `tools/board_test.py` explicitly tests that these two remain unanswered.

**`0xC0` answers with `0x40`, and doesn't reset.** Per the vendor spec §2.10.1 a device answers
a reset with its Device ID rather than with `0xC0`. Actually rebooting would drop the host
connection R1 is holding, so the firmware deliberately does neither.

**Baud is a fiction that always says 100 k.** dbCAN is fixed at 100 kbit/s ("can not be
changed", per the R70 manual), so `0x57` accepts any rate and reports `0xFE` regardless. R1
sets exactly this value on every connect. A request to run the bus at another rate is silently
not honoured — there is nothing to honour it with.

**`0xA3` Block Time is echoed, not applied.** On a real R70, Block Time batches several frames
into one TCP segment. CANary accepts the setting so R1 is satisfied, and does not implement
the batching. Frames go out as they come.

**Version is invented.** `01 00 00 01 00 01` is not a real R70's version triple. If anything
downstream ever branches on gateway version, this is where it will make the wrong decision.

### Framing

Several frames may be concatenated inside one TCP segment, so decoding is **stream-oriented,
not datagram-oriented** — `rmbcp_decoder_t` is a running decoder, and any reimplementation must
be too. Max data 254 bytes, max frame 259. Commands `0xD0`–`0xDF` are the extended range and
are unwrapped before dispatch (`rmbcp_unwrap_extended()`).

---

## 2. Discovery on UDP 33333

This is the part with no vendor document behind it: documented from captures of R1's
discovery traffic and confirmed live. Full description in
[PROTOCOL.md §4](PROTOCOL.md).

Packet = 4-byte header + N × 64-byte records. Opcode `0x80` is R1's request, `0x00` is the
answer.

Record layout (`r70_ddt.h` is the authority — offsets are named constants there):

| Offset | Field | What CANary sends |
|---|---|---|
| 0 | IPv4, big-endian | the interface's current address — DHCP lease, or the self-assigned 169.254 one |
| 4 | service | `1` (server). `2` = client; **anything else and R1 drops the record** |
| 5 | protocol | `1` (TCP). `3` = UDP; **never 2 or 0xFF**, and service `1` with protocol `0` is dropped |
| 6 | port | `30000` |
| 8 | MAC | from the module's eFuse — unique per board |
| 14 | tag | |
| 36 | hostname | `CANary` by default, max 27 chars + NUL |

Four socket records are advertised (`R70_DDT_MAX_SOCKETS`). A real R70 offers four, and R1
keeps its socket column read-only unless it sees them.

Two operational consequences:

- **Answer from one interface only.** A host answering on every local interface gives R1
  several entries sharing one name. `tools/r70_emu.py` has `--answer-from` for exactly this.
  The firmware answers on the socket the probe arrived on, so it never produces duplicates —
  but since `components/usbnet` it can have **two** interfaces, and which address it names
  now matters (below).
- **R1 connects to whatever address the answer advertises**, not the UDP sender's address, so
  the answer has to carry the address the interface currently holds. `bridge_local_ip_for()`
  is read per answer, and takes the probe's source address, for exactly that reason: on a network with no DHCP server the address starts as a
  self-assigned `169.254.x.x` and may be replaced by a lease later, and the next answer must
  carry the new one. With no link at all there is no address to advertise, the bridge is useless,
  and it says so in the log rather than sitting there looking alive.

  With a USB-NCM interface up there are two addresses and only one of them is reachable from
  any given R1, so the answer names the one on the interface whose subnet contains the peer,
  falling back to the wired address — never the USB one, which routes nowhere. The rule is
  `firmware/components/net/net_select.c`, host tested; see
  [USB-NIC.md §5](USB-NIC.md#5-two-interfaces-one-discovery-answer).

---

## 3. The CAN side

**dbCAN: CAN 2.0A, 11-bit identifiers, 100 kbit/s fixed.** Not rate-configurable — testing at
any other rate proves nothing.

Identifier packing (`DBCAN_*` in `rmbcp.h`, full derivation in [PROTOCOL.md §5](PROTOCOL.md)):

```
 bits 10..9   object class   0 primary master, 1 secondary master, 2 device data, 3 stream
 bits  8..6   subnet         0-7
 bits  5..0   device         0-63   (device 0 = broadcast into that subnet)
```

The bridge is **transparent**: it does not interpret the up-to-8 payload bytes, and neither
does a real R70. The dbCAN *application layer* — what those bytes mean — is **not documented in
any vendor material we have** and is not implemented. That is only needed to *emulate* an
amplifier, not to bridge to real ones.

`tools/dbcan_device.py` is a stand-in amplifier that addresses frames correctly and echoes the
master's payload as a deliberate placeholder. Any reaction R1 has to it is **evidence about the
protocol, not proof the device is correct.**

---

## 4. Status LEDs

The board's only interface when there's no serial console attached. Three MCU-driven LEDs on
GPIO 15/16/17, plus a hard-wired power LED.

> **They are ACTIVE HIGH** (`BOARD_LED_ACTIVE_LEVEL = 1` in `board.h`) — cathode to GND, anode
> to the GPIO. This was recorded as active *low* until bring-up work re-derived it from the
> schematic; the net names ending `_K` are what misled. If all three LEDs come up inverted on
> first hardware, that constant is what to change — and nothing else, because nothing else
> hard-codes a polarity.

On power-up all three run a **lamp test**: each in turn, then all three together. An LED that
stays dark there is fitted backwards or on the wrong GPIO.

| LED | Marking | State | Means |
|---|---|---|---|
| D304 | ON (green) | steady with 3V3 up | Powered. Wired from the rail through R305 — lights with or without firmware, so it's the only indicator on an unprogrammed board. |
| D301 | LAN (green) | off | no Ethernet link |
| | | 4 Hz | link up, no address yet |
| | | 1 Hz | address held, waiting for R1 |
| | | steady | **R1 connected — carrying traffic** |
| D303 | CAN (green) | off | TWAI not running |
| | | double-pulse heartbeat | bus up, idle |
| | | flickering | CAN traffic |
| D302 | ERR (red) | off | nothing wrong |
| | | *n* blinks, pause, repeat | fault code *n* |

**ERR fault codes** — counted blinks then a one-second gap. A count is readable across a dark
stage in a way a colour or a duty cycle is not. **Only the most significant fault shows:**
Ethernet outranks CAN, because without an address R1 cannot reach the unit at all. So a
1-blink code does not mean CAN is healthy — it means CAN hasn't been looked at yet.

| Blinks | Fault |
|---|---|
| 1 | no Ethernet link |
| 2 | link but no address (neither DHCP nor link-local yet) |
| 3 | CAN bus-off |
| 4 | CAN stopped — TWAI never started (firmware fault, not wiring) |

State mapping is in `main/status.c`, patterns in `components/led/`, pins in `components/board/`.

---

## 5. Self-test console

**Test builds only.** The shipping image has no command interface at all — the console is
compiled in by a separate build:

```bash
idf.py -B build-selftest build -DCANARY_SELFTEST=1
```

Prompt is `canary>` over USB CDC at 115200.

| Command | Does |
|---|---|
| `selftest [eth\|can\|led\|post]` | run everything, or one group; prints `RESULT` lines + a JSON record |
| `id` | chip, flash size, eFuse MAC, reset reason |
| `led <lan\|err\|can\|all> <on\|off>` | drive an LED directly; prints the GPIO level used |
| `can normal\|listen\|selftest\|off` | set TWAI mode |
| `can tx <id-hex> [data-hex]` | transmit a frame |
| `can rx [ms]` | receive for a period |
| `can stats` | TWAI counters |
| `reboot` | restart |
| `help` | the above |

Results are `PASS` / `FAIL` / `SKIP` / `INFO`. **`SKIP` is used deliberately** where something
could not be examined — the runner never reports a pass for a check it didn't perform.

Two checks carry most of the value:

- **`eth.versionr`** — one SPI read of the W5500's `VERSIONR` must return `0x04`. That single
  byte proves the SPI bus in both directions, the W5500's supply, its 25 MHz crystal and its
  reset line. It is read at **4 MHz and then at the application's 20 MHz**, so a
  signal-integrity problem shows as one passing and the other failing rather than as one
  ambiguous failure. `0x00` means MISO idle low, `0xFF` means idle high — different faults.
- **`can.loopback`** — a real frame out of GPIO4, through the ADM3053, **across the isolation
  barrier**, onto CANH/CANL and back into GPIO5. It therefore also proves the isolated DC-DC
  started, which cannot be checked from the system side. **Set SW201 to TERMINATED first** or
  it will fail for the wrong reason.

The self-test deliberately does **not** use `esp_eth`'s W5500 driver: that driver reports
"failed to detect W5500" for a dozen different causes and hides which one. A raw SPI read
names the fault.

`pd.pg` reports the PD power-good GPIO as `INFO` with "polarity unverified" — it is not a pass
or a fail until hardware settles which way round it reads.

---

## 6. Host tools

`tools/` is the **reference implementation** — the code actually proven against real R1. The C
firmware components carry the same test vectors.

### `r70_emu.py` — emulator and prober

Turns a laptop into something R1 lists as an R70. No ESP32, no R70, no amplifiers needed.

```bash
python3 tools/r70_emu.py sniff                          # watch R1's probe, byte for byte
python3 tools/r70_emu.py serve --answer-from 192.0.2.90
python3 tools/r70_emu.py serve --answer-from 192.0.2.90 --virtual-device 1.2
```

| Option | Default | Notes |
|---|---|---|
| `mode` | — | `sniff` or `serve` |
| `--answer-from LOCAL_IP` | all | **Use it.** Answering on every interface gives R1 duplicate entries sharing one name. |
| `--reply ddt\|raw\|none` | `ddt` | `raw` sends `--raw-hex` literally, for testing a captured reply |
| `--host-name` | `db-70` | the R70 factory default |
| `--mac` | `00:50:C2:5D:C0:BE` | must stay in RM Michaelides' IAB or R1 won't recognise it as an R70 |
| `--virtual-device SUBNET.DEVICE` | — | stand-in amplifier; payload is a placeholder |
| `--sockets` | 4 | |
| `--service` / `--protocol` | server / TCP | see §2 — wrong values make R1 drop the record |
| `--udp-port` / `--tcp-port` | 33333 / 30000 | |

**If R1 runs in a VM its adapter must be BRIDGED, not NAT.** A NATted guest cannot reach a
broadcast responder on the host. (R1 V3 has a macOS build, in which case this doesn't arise.)

### `board_test.py` — board acceptance run

```bash
tools/board_test.py --serial-number 0001 --port /dev/cu.usbmodem101 --record boards/0001.json
tools/board_test.py --simulate      # prove the runner with no board
```

Five independent stages, each skippable via `--skip`, because during bring-up you rarely have
all five working at once and a runner that reports nothing until everything passes is useless
on a bench:

| Stage | What it proves | Needs |
|---|---|---|
| `console` | the board's own verdicts, from inside | self-test build + pyserial |
| `discover` | **R1's real captured probe** is answered correctly — so R1 will list it, not merely that our decoder likes our encoder | network |
| `rmbcp` | the TCP command set, **including that `0x44`/`0xA4` stay silent** | network |
| `can` | a real frame through an isolated adapter | python-can + adapter |
| — | writes a JSON record keyed to `--serial-number`, exits non-zero on any failure | |

Other options: `--host` (default: discover it), `--broadcast`, `--tcp-port`, `--udp-port`,
`--baud`, `--operator` (stamped into the record), `--can-channel` / `--can-interface`
(e.g. `can0` / `socketcan`, `PCAN_USBBUS1`), `--timeout`, `--console-timeout`,
`--silence-wait` (how long to wait to confirm a command really *wasn't* answered).

`--simulate` runs `r70_emu.py` as the stand-in device and exercises every stage except the
serial console and the CAN wire — which it reports as **SKIP, not PASS**.
`tools/test_board_test.py` runs exactly that in CI.

### Modules

`rmbcp.py` (codec + dbCAN ID helpers), `r70_ddt.py` (discovery), `dbcan_device.py` (stand-in
amplifier). All importable. `rmbcp.py` carries **both worked examples from the vendor spec**,
checksums and all, as tests — the codec is pinned to the document rather than to our reading of
it.

---

## See also

- [PROTOCOL.md](PROTOCOL.md) — the protocol as recovered, every claim tagged `[spec]` / `[derived]` / `[unknown]`
- [SOURCES.md](SOURCES.md) — where to get the vendor manuals (not redistributed here)
- [USER-GUIDE.md](USER-GUIDE.md) — operating a unit
- [DEVELOPING.md](DEVELOPING.md) — building and extending
- [DECISIONS.md](DECISIONS.md) — why things are the way they are
