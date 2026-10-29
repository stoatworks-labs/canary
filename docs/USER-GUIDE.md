# CANary — User Guide

Flashing, configuring and operating a CANary, and what to check when R1 won't see it.

---

## 0. Read this before you trust it

Rev A boards were fabricated and assembled turnkey from commit `d9a725d` (before the final USB-C re-route, which board #1 proved survivable). Board #1 passes its self-test 6/6, took a DHCP lease on a live switch, passes the 19-check host-side acceptance run over Ethernet and over USB, and is discovered and listed by R1. On 2026-10-28 it went on a real bus with two d&b amplifiers: both answered on both CAN jacks, and the control application drove mute and gain through the board in both directions. **Still unproven:** recovery after a CAN cable pull (it failed on 10-28, and the firmware here has the same fault — see §8), LAN pulls, amplifier power cycles and long runs, the skipped bench-supply and isolation measurements, and the LED/PD-pin eyeball checks. One board of the batch has been touched. Record: [`hardware/fab/test/BRINGUP-LOG-0001.md`](../hardware/fab/test/BRINGUP-LOG-0001.md).

What *is* solid: the protocol. A real R1 (V3.46) discovers the host emulator in `tools/`, lists
it, connects on TCP 30000 and drives the bus. The codec is pinned to the vendor's own worked
examples. That is strong evidence about the wire; what the board has done is in its bring-up log.

So everything below is the **intended procedure, written from the schematic and the source**.
Only board #1 has been through any of it, so treat every step as unverified unless its bring-up
log, or [USB-NIC.md](USB-NIC.md) §7 for the USB image, says it's been done. Where something is
known not to work, it says so.

**It has been tested against real amplifiers once**: two of them, on one board, for one
afternoon, on development firmware newer than any release (bring-up log §12). Treat it as a
development platform, not show equipment.

### Safety — read before touching a board

- **The three etherCON jacks are physically identical and two of them are CAN.** J401 is the
  LAN. J201/J202 are CAN. Plugging a network into a CAN jack, or vice versa, is easy and
  unpleasant.
- **Rev A has no PoE, and a *passive* PoE injector will destroy it.** There is no PD front-end
  to negotiate with; a passive injector simply puts 48 V on the pairs.
- **One ground clip across the isolation barrier turns a good board into scrap** — and one that
  still passes every functional test, so you won't find out until it matters. Read §0 of
  [`hardware/fab/test/BENCH-BRINGUP.md`](../hardware/fab/test/BENCH-BRINGUP.md) before probing.
- Using this with d&b equipment is at your own risk and may affect that equipment's warranty or
  support status. See the legal note in the [README](../README.md).

---

## 1. What it is

An IP-to-CAN converter compatible with the **d&b R70 Ethernet-to-CAN interface**'s protocol, so **R1** can
control d&b amplifiers (D6, D12, E-PAC) over a network through hardware you can build yourself.

```
R1 (Mac/PC) ──Ethernet──▶ [ J401 LAN ]  CANary  [ J201 / J202 CAN ] ──▶ D6 / D12 / E-PAC
```

It is a **transparent bridge** — exactly what the R70 is. It carries CAN frames faithfully and
does not interpret d&b's parameters at all. It is not a control surface and should not become
one.

---

## 2. What you need

- a CANary rev A board with the three etherCON jacks hand-soldered
- a USB-C cable and a 5 V PD-capable supply (rev A is USB-C powered; PoE is deferred to rev B)
- ESP-IDF **v5.5.5** — the firmware targets `esp32s3`
- a network — a DHCP server if you have one, but §4 explains what happens when you don't

---

## 3. Flashing

The ESP32-S3 has native USB, so **J102 is both the power input and the programming port**. No
external programmer, no USB-UART bridge.

```bash
export PATH=/opt/homebrew/opt/python@3.12/libexec/bin:$PATH
. ~/esp/esp-idf/export.sh
cd firmware
idf.py set-target esp32s3      # once
idf.py build
idf.py -p /dev/cu.usbmodem* flash monitor
```

That `PATH` line is not optional and the reason is non-obvious: `export.sh` keys its virtualenv
off whichever `python3` is first on `PATH`. Homebrew's `python@3.12/bin` contains only
`python3.12`, so the script finds the *system* 3.14 — unsupported — and fails. `libexec/bin`
provides an unversioned `python3`. Full detail in [DEVELOPING.md](DEVELOPING.md).

**If the board doesn't appear as a serial device**, force ROM download mode by hand: hold
**SW302 (BOOT)**, tap **SW301 (RESET)**, release SW302.

**If USB enumeration is itself what has failed**, `J301` (1×6, 1.27 mm: `GND, VCC_3V3,
UART0_TXD, UART0_RXD, BOOT, EN`) is the only way to watch the boot log.

---

## 4. Configuration

**Settings live in NVS, and the configuration page is the only way to change them.** The page
exists only on an image built with the USB network device, and only over the USB cable
([WEBUI.md](WEBUI.md)). An Ethernet-only image runs on whatever is stored, or on the defaults
below. A change takes effect at the next boot. There is no console on the shipping image.

| Setting | Value | Changeable |
|---|---|---|
| Hostname shown in R1 | `CANary` | the web UI, over the USB cable ([WEBUI.md](WEBUI.md)) |
| TCP base port | `30000` (R70 socket 1) | the web UI |
| Socket count | `4` | the web UI |
| MAC address | from the module's eFuse | automatic, unique per board |
| IP address | **DHCP**, falling back to link-local `169.254.x.x` | a static address, from the web UI |
| CAN bitrate | **100 kbit/s** | **no — dbCAN is 100 k, full stop** |

### A rig with no DHCP server still works

The board asks for a DHCP lease first. If nothing answers after about 7 seconds of trying, it
**self-assigns a link-local address** — `169.254.x.x`, RFC 3927, the same mechanism Windows and
macOS use when they find no DHCP server — and runs on that. It is normally holding an address
about 15 seconds after link-up. The boot log says which kind it got:

```
I (4137) net: got 192.0.2.27 by DHCP
W (14622) net: got 169.254.13.44 - LINK-LOCAL (RFC 3927): no DHCP server answered, so R1 must
               also be link-local to reach us
```

**The catch is that the R1 machine has to be link-local too.** That happens by itself if it is
plugged into the same DHCP-less switch with its interface set to DHCP — it will self-assign in
the same range and the two can see each other. It does *not* happen if that machine has a static
address on some other subnet, because a 169.254 address only talks to other 169.254 addresses.

DHCP always wins when it is available: the two run together, so a lease that turns up late
replaces the link-local address, and the next discovery answer tells R1 the new one. If R1 was
already connected over the link-local address at that moment, the session drops — scan again.

There is still **no static-IP option**. An address you choose yourself has to be set by a DHCP
reservation.

### Wi-Fi is a devkit convenience, not a shipping path

Wi-Fi STA exists in the source so the bridge can be exercised on a plain ESP32-S3 devkit before
boards exist:

```bash
idf.py build -DCANARY_USE_WIFI=1 -DCANARY_WIFI_SSID=my-ssid -DCANARY_WIFI_PASS=my-pass
```

> **⚠ These flags stick.** `idf.py -D` writes to the CMake cache, so a later plain `idf.py
> build` **silently keeps building the Wi-Fi variant**. Getting back to Ethernet requires saying
> so explicitly:
>
> ```bash
> idf.py -DCANARY_USE_WIFI=0 build
> ```
>
> Check which variant you actually built:
> `grep -c CANARY_USE_WIFI=1 build/compile_commands.json` — `1` means Wi-Fi, `0` means
> Ethernet.

On the real board the LAN jack is fed entirely by the W5500 over SPI and the ESP32-S3 has no
internal EMAC, so wired Ethernet is the only sensible path.

---

## 5. Connecting it to R1

Identical to the host emulator, because R1 cannot tell them apart:

1. Patch **J401** (the LAN etherCON) to the same network as the R1 machine.
2. In R1: **Extras > Options > CAN > Refresh**. `CANary` should appear.
3. Go **Offline**, tick the interface's activation checkbox, then go back **Online**.

### ⚠ Step 3 is not optional and not obvious

**The activation checkbox cannot be ticked while R1 is Online** — it is greyed out. This is pure
R1 UI state and has nothing to do with the gateway emulation.

If initialisation stalls after command `0xA4` and the bus scan never starts, **R1 is Online and
the box was never activated**. That is almost always the cause, rather than anything wrong with
the bridge. It took a long time to establish, so it is worth remembering.

### Trying it with no hardware at all

The host emulator needs only R1 and a laptop:

```bash
python3 tools/r70_emu.py serve --answer-from 192.0.2.90
```

Use your own LAN address. `--answer-from` keeps it to one interface, as a real R70 would be —
answering on every local interface gives R1 several entries sharing one name.

To also stand in for an amplifier on the bus (addressing correct, **payload a placeholder**):

```bash
python3 tools/r70_emu.py serve --answer-from 192.0.2.90 --virtual-device 1.2
```

**If R1 runs in a VM, its adapter must be BRIDGED, not NAT.** A NATted guest cannot reach a
broadcast responder on the host.

---

## 6. Wiring the CAN bus

**J201 and J202 are the same bus in parallel**, for daisy-chaining — not two independent ports.
Either one goes to the amplifiers; the other carries on to the next box.

- **100 kbit/s, fixed.** dbCAN is not rate-configurable, so testing at any other rate proves
  nothing. R1 asks the gateway to set a rate on every connect; the bridge reports 100 k
  whatever it was asked for.
- Amplifiers are addressed `subnet.device` — 3-bit subnet (0–7), 6-bit device (0–63), where
  device **0 broadcasts into the subnet**. See [PROTOCOL.md](PROTOCOL.md) §5.
- **SW201 switches bus termination in and out.** It is a passive mechanical switch across the
  termination resistors — **firmware does not read it and cannot tell you its position.**
  Terminate at the two physical ends of the bus and nowhere else, as with any CAN segment.
  A mis-terminated bus presents as bus-off (ERR = 3 blinks) or as intermittent frames, not as
  anything that names the real cause.

---

## 7. Reading the front panel

On power-up all three MCU-driven LEDs run a **lamp test** — each in turn, then all three
together. An LED that stays dark there is fitted backwards or on the wrong GPIO; the test exists
to make that obvious on the bench rather than later.

| LED | Marking | State | Means |
|---|---|---|---|
| **D304** | ON (green) | steady whenever 3V3 is up | Powered. Wired from the rail through R305, so it lights with or without firmware — the only indicator on an unprogrammed board. |
| **D301** | LAN (green) | off | nothing to reach the unit on — no Ethernet link, and no USB host either |
| | | 4 Hz | a link, but no address yet |
| | | double-pulse heartbeat | *USB image only:* a host is attached but has not taken an address of its own. We are ready; it is not. See below. |
| | | 1 Hz | address held, waiting for R1 to connect |
| | | steady | **R1 connected — the bridge is carrying traffic** |
| **D303** | CAN (green) | off | TWAI not running |
| | | double-pulse heartbeat | bus up, idle |
| | | flickering | CAN traffic |
| **D302** | ERR (red) | off | nothing wrong |
| | | *n* blinks, pause, repeat | fault code *n*, below |

**ERR fault codes** — counted blinks, then a one-second gap. A count is readable across a dark
stage in a way a colour or a duty cycle is not.

| Blinks | Fault | First thing to check |
|---|---|---|
| **1** | no link at all | the patch to J401, and that the far end is up. On a USB image this also means no host is attached — a unit reachable over USB is not in fault |
| **2** | a link, but no address | neither DHCP nor link-local has produced an address yet — normal for the first few seconds after link-up, a fault if it persists |
| **3** | CAN bus-off | wiring short, mis-termination, or the far end at a different bit rate |
| **4** | CAN stopped | TWAI never started — a firmware fault, not a wiring one. Read the serial log. |

> **Only the most significant fault shows.** The network outranks CAN, because without an
> address R1 cannot reach the unit at all. So **1 blink does not mean CAN is fine** — it means
> CAN hasn't been assessed yet. Fix the network fault and look again.

**D301 is a reachability lamp, not an Ethernet lamp.** It is silkscreened LAN because when the
board was drawn the LAN jack was the only way in. On an image built with the USB network device
([USB-NIC.md](USB-NIC.md)) a laptop on the USB-C cable counts too, so a unit with no patch lead
and a host attached shows 1 Hz and no fault — it is working.

**The heartbeat is the one state worth learning.** It means the USB link came up and the host
then failed to take an address: macOS and Windows both fall back to a self-assigned 169.254
address when no DHCP offer arrives, and a host that has done that can never reach the unit
however healthy the unit is. From this end the link looks perfect, which is why it gets its own
pattern rather than being folded into "address held". Check the host's own address on that
adapter first — it should be 192.168.7.2.

The LEDs are on GPIO15/16/17 and are **active HIGH**. (An earlier version of this documentation
said active low; the code and the schematic say high — `BOARD_LED_ACTIVE_LEVEL = 1` in
`firmware/components/board/include/board.h`, where the header comment records the correction.
If all three come up inverted on first hardware, that one constant is what to change.)

For anything more detailed than the panel, the serial log on USB or J301 is the place to look.

---

## 8. Troubleshooting

| Symptom | Cause |
|---|---|
| **R1's Refresh finds nothing** | No address at all (LAN LED at 4 Hz, ERR = 2) — check the cable. Or the board is on a link-local `169.254` address and R1's machine is not (§4). Or R1 is on a different broadcast domain — discovery is a UDP broadcast and does not cross subnets. Or R1 is in a NATted VM (§5). |
| **R1 lists several `CANary` entries** | Something is answering on multiple interfaces. On the host emulator, use `--answer-from`. |
| **R1 lists it but won't connect** | The activation checkbox was never ticked — and it *can't* be ticked while Online (§5). |
| **Initialisation stalls after `0xA4`** | Same thing: R1 is Online, box not activated. Almost never a bridge fault. |
| **It connected, then R1 hung** | If you have modified the firmware to *answer* commands `0x44` or `0xA4`, undo that. Their silence is load-bearing — answering them is what made R1 loop during bring-up. |
| **LAN LED steady but no amps respond** | The bridge is carrying traffic and the problem is downstream: CAN wiring, termination (SW201), or addressing. Check ERR for 3 blinks. |
| **CAN LED off** | TWAI isn't running — ERR = 4, a firmware fault. Serial log. |
| **CAN bus-off (ERR = 3)** | Short, mis-termination, or a device at the wrong bit rate. dbCAN is 100 k and nothing else. |
| **Amplifiers gone after a CAN lead was pulled and refitted** | A known fault in the firmware here and in both releases: the CAN side does not recover by itself, and ERR may stay dark while it is stuck (bring-up log §12). Power-cycle the unit. A fix exists in development firmware; it is not yet in this repository and has not been re-run on a board. |
| **Board doesn't enumerate over USB** | Force ROM download mode: hold SW302, tap SW301, release SW302 (§3). If that fails, use J301. |
| **Built for Ethernet, got Wi-Fi** | The `-DCANARY_USE_WIFI=1` flag stuck in the CMake cache (§4). |
| **A rate change didn't take** | Expected. The bus is 100 k and the gateway reports 100 k regardless of what was asked (§4). |
| **Block Time setting had no effect** | Expected. It is accepted and echoed, not applied — frames go out as they arrive. |
| **All three LEDs inverted** | `BOARD_LED_ACTIVE_LEVEL` (§7). One constant, nothing else. |

---

## 9. Testing a board

Three pieces, meant to be used together. All three have been used on board #1 — the self-test
and the acceptance run in full, the bench procedure in part (its bench-supply, rail and PD steps,
§1–§4, were skipped) — but most limits they carry are still derived from the schematic and the
datasheets, not measured across a batch.

### 1. The board tests itself

A **separate firmware image**, so the shipping unit keeps no command interface:

```bash
cd firmware
idf.py -B build-selftest build -DCANARY_SELFTEST=1
idf.py -B build-selftest -p <port> flash monitor
```

At the `canary>` prompt, `selftest` runs everything and prints machine-readable `RESULT` lines
plus a JSON record. Full command list in [API.md §5](API.md#5-self-test-console).

Two checks carry most of the value: **`eth.versionr`** (one SPI read proves the bus both ways,
the W5500's supply, its crystal and its reset line — and is read at two clock rates so a
signal-integrity fault shows as one pass and one fail rather than one ambiguous failure), and
**`can.loopback`** (a real frame across the isolation barrier, which also proves the isolated
DC-DC started — something that cannot be checked from the system side). **Set SW201 to
TERMINATED before running the loopback** or it fails for the wrong reason.

The product image runs only the identity part of this at boot, and never claims a peripheral.

### 2. The host tests the board

```bash
tools/board_test.py --serial-number 0001 --port /dev/cu.usbmodem101 --record boards/0001.json
```

It reads the board's own self-test over USB, discovers the board with **R1's own captured
discovery probe**, walks the RMBCP command set — including confirming the two commands that must
stay unanswered — and optionally drives a real CAN frame through an isolated adapter. Writes a
JSON record and exits non-zero on failure.

**With an amplifier on the bus, skip the `rmbcp` stage** (`--skip console,rmbcp`). It puts a
test frame, `0x123 55 AA`, on the CAN wire, and nothing but the control application's own traffic
belongs near someone else's amplifier (bring-up log §12).

It can be proven before any board exists:

```bash
tools/board_test.py --simulate
```

That runs the emulator as a stand-in and exercises every stage except the serial console and the
CAN wire, **which it reports as SKIP rather than pretending it looked**.

### 3. The person tests the board

[`hardware/fab/test/BENCH-BRINGUP.md`](../hardware/fab/test/BENCH-BRINGUP.md) is the
step-by-step hardware procedure: bench PSU, DMM, network switch, with optional oscilloscope and
logic-analyser appendices. Every expected value is tagged `[spec]`, `[derived]` or `[predicted]`
so you can tell a datasheet number from a guess.

Probe points are in `hardware/fab/test/PROBE-POINTS.{json,csv}` and drawn on the board in
`docs/renders/probe-*.svg`. Both are generated from `canary.kicad_pcb` by
`hardware/scripts/probe_points.py`, which **refuses to run if a probe's designator, pad or net
no longer matches** — so a marker cannot quietly drift off its pad.

---

## 10. What does not exist yet

- **A web UI anyone has used.** There is one — plug the unit into a laptop and
  `http://192.168.7.1/` gives status, settings, firmware updates and diagnostics. On board #1
  (2026-09-26) a Mac reached it over the USB link and got the page back. Nothing past that has
  been recorded on a board, so treat it as untried. [WEBUI.md](WEBUI.md).
- **A USB network device you can rely on.** The code exists (2026-09-21): built with the
  `sdkconfig.usb-ncm` overlay, the unit appears to a laptop as a second Ethernet adapter at
  `192.168.7.1` and R1 reaches it over the USB cable with no LAN at all. **Only a Mac has
  enumerated it** (2026-09-26: a lease and the 19-check acceptance run over USB). Discovery by
  the control application over USB, and Windows, haven't been tried, so treat those as untried
  — and note that on that image the USB-C port is no longer a serial port, so the console moves
  to J301 and reflashing needs BOOT held.
  [USB-NIC.md](USB-NIC.md).
- **R60 emulation.** The same protocol over a USB *serial* port. No code exists.
- **The dbCAN application layer.** The bridge is transparent, which is all a real R70 does, so
  this is only needed to *emulate* an amplifier rather than to bridge to real ones.
- **PoE.** Deferred to rev B, along with Ethernet ESD/TVS.
- **Amplifiers over a long run, or through a fault.** Two amplifiers have been driven through
  one board for an afternoon (bring-up log §12). After a CAN cable pull the firmware here does
  not recover by itself (§8); LAN pulls, amplifier power cycles and anything longer have not
  been tried.

---

## See also

- [API.md](API.md) — every interface, including what the firmware answers and what it stays silent about
- [PROTOCOL.md](PROTOCOL.md) — the protocol as recovered, with provenance
- [DEVELOPING.md](DEVELOPING.md) — building and extending
- [`hardware/fab/test/BENCH-BRINGUP.md`](../hardware/fab/test/BENCH-BRINGUP.md) — hardware bring-up
