# dbCANary — protocol reference

Everything needed to build an interface compatible with the d&b audiotechnik
**R70 Ethernet to CAN interface**'s protocol, as used by the **R1** remote control
software.

Each claim below is tagged:

- **[spec]** — stated in vendor documentation (cited).
- **[derived]** — followed from a spec statement plus arithmetic we verified in code.
- **[unknown]** — not documented; must come from a packet capture.

---

## 1. The key finding: the R70 is not a bespoke d&b design

R1 lists CAN interfaces by MAC address, e.g. `0050C25DC0BE`
(R70 manual 1.4 EN §3.4, screenshot). That address falls in IEEE Individual
Address Block `00-50-C2 / 5DC000-5DCFFF`, registered to
**RM Michaelides Software & Elektronik GmbH**, Fulda, Germany — now **Proemion**.
(Verified against `https://standards-oui.ieee.org/iab/iab.txt`.)

So the R70 is an OEM RM Michaelides CAN gateway in a d&b enclosure, and its
Ethernet-side protocol is the publicly documented **RM Byte Command Protocol**.
Corroboration, not just the MAC:

| R70 web UI control | RM Byte Command Protocol | Source |
|---|---|---|
| "Block Time (x10ms)" | command `0xA3` *Set IP-block wait time*, "interval in 10 milliseconds" | R70 SW manual §1.2.1 / RMBCP §2.9.3 |
| "Online Timestamp" | commands `0x01`/`0x03` carry "an additional 32 bit timestamp value" | R70 SW manual §1.3.1 / RMBCP §2.3.1 |
| 4 sockets, TCP or UDP, server/client | "CAN to PC gateways connect a CAN network to a remote host using … Ethernet" | R70 SW manual §1.2.2 / RMBCP §1 |
| Mask + Arbitration + Inhibit Time filters | receive/transmit channel ID & mask settings | R70 SW manual §1.3.2 / RMBCP §2.6.1–2 |

**Consequence: no reverse engineering is required for the data path.** Only the
discovery handshake (§4) is undocumented.

---

## 2. Frame format — RM Byte Command Protocol   [spec]

Source: *RM Byte Command Protocol — API description* §2.1; see [SOURCES.md](SOURCES.md).

```
 SOF   Length   Command   Data ...   Checksum   EOF
0x43    1 by     1 by      n bytes    1 byte    0x0D
 'C'                                            <CR>
```

- **Length** = number of bytes between Length and Checksum, i.e. command byte + data bytes. **[derived, test-locked]**
- **Checksum** = XOR of SOF, Length, Command and every Data byte.
- **SOF/EOF** are configurable on some gateways; the R70 uses the defaults above.
- `0xFF` as command means the next byte is a command extension.
- `0xD0`–`0xDF` are the **extended form**: `data[0]` = CAN channel (0 = CAN 1),
  `data[1]` = the real command, `data[2:]` = its payload.

Both worked examples from the spec are encoded as unit tests in
[`tools/test_rmbcp.py`](../tools/test_rmbcp.py) — they pass, which pins our reading
of Length and Checksum to the document.

### Framing hazards   [derived]

- **`0x43` and `0x0D` are legal CAN payload bytes.** There is no escaping, so a
  decoder must never resync on a bare SOF/EOF byte; only Length + Checksum + EOF
  agreeing together identifies a frame.
- **Many frames may share one TCP segment or UDP datagram.** That is precisely
  what Block Time (`0xA3`) batches, to use the link efficiently. Decoding must be
  stream-oriented.
- A corrupt Length must not stall the stream. `tools/rmbcp.py` scans every SOF
  position for the first provably valid frame and only holds the earliest
  candidate that could still complete.

### Commands relevant to a transparent bridge   [spec]

| Cmd | Meaning | Notes |
|---|---|---|
| `0x00` | 11-bit CAN message | data: 2-byte ID (MSB first) + ≤8 data bytes |
| `0x01` | 11-bit CAN + timestamp | as above + 32-bit timestamp |
| `0x02` | 29-bit CAN message | data: 4-byte ID (MSB first) + ≤8 data bytes |
| `0x03` | 29-bit CAN + timestamp | as above + 32-bit timestamp |
| `0x40` | Device ID string | request has no data; last 2 reply bytes are a 16-bit device id |
| `0x41` | Versions | 2 bytes each: hardware, firmware, bootloader |
| `0x47` | CAN bus load | messages per calculation interval |
| `0xA3` | IP-block wait time | units of 10 ms — the "Block Time" control |

DLC is not transmitted; it is implied by Length. **[derived]**

Settings written by command land in volatile RAM and revert on reset — except
CAN baud rate, which persists. **[spec, RMBCP §1]**

---

## 3. Network parameters   [spec]

Source: R70 manual 1.4 EN §3.2–3.4, R70 software reference manual 1.3 EN §1.2.

| Item | Value |
|---|---|
| Data socket | **TCP 30000** (adjustable) |
| Discovery | **UDP 33333** (fixed) |
| Default IP | `192.168.1.70`, DHCP enabled by default |
| Default host name | `db-70` |
| Web config | HTTP on port 80, requires JavaScript |
| Sockets | 4, each independently TCP or UDP, server / client(auto-connect) / disabled |
| Per-PC limit | up to 5 R70s simultaneously in R1 |

Socket modes **[spec, SW manual §1.2.3]**:

| PC (R1) | R70 | peer | use |
|---|---|---|---|
| TCP | TCP server | — | standard R1 operation on LAN/WLAN |
| UDP server | UDP client | UDP client | more than one master (R1 + a PLC/media control) |
| — | TCP client | TCP server | bridging two CAN networks R70↔R70 |

R1 displays discovered interfaces as `<host-name>-<TRANSPORT>-<port>` with the MAC
as the ID column, e.g. `db-70-TCP-30000` / `0050C25DC0BE`. **[spec, screenshot]**

---

## 4. Discovery on UDP 33333 — "device detection" (DDT)   [derived, capture-confirmed]

Not documented by the vendor. Documented here from captures of R1 V3.46's
discovery traffic on UDP 33333 and confirmed live: R1 discovers, lists and
connects to an interface that answers as described below. R1 waits about
4000 ms for answers after each probe. Implemented in
[`tools/r70_ddt.py`](../tools/r70_ddt.py), with the captured probe as a test vector.

### Packet: 4-byte header + N × 64-byte records

| Offset | Field |
|---|---|
| 0 | interface index — R1 numbers its local interfaces 0,1,2,… and sends one probe per interface |
| 1 | `0x00` |
| 2 | **opcode: `0x80` = request, `0x00` = answer** |
| 3 | record count |
| 4… | records, exactly 64 bytes each |

### Record

| Offset | Size | Field |
|---|---|---|
| 0 | 4 | IPv4 address, **big-endian** |
| 4 | 1 | service — must be `1` or `2`, else R1 drops the record |
| 5 | 1 | protocol — `1` = TCP, `3` = UDP; `2` and `0xFF` are rejected |
| 6 | 2 | port, **big-endian** |
| 8 | 6 | MAC address |
| 14 | 4 | device-type tag, ASCII `"R70 "` |
| 36 | ≤28 | host name, NUL-terminated UTF-8 |

Records with any other service value, or with protocol `2` or `0xFF`, are ignored
by R1. The combination service=`1` with protocol=`0` is also dropped.

### Captured probe (interface index 2)

```
00000000  02 00 80 01 00 00 00 00  00 00 00 00 00 00 00 00
00000010  00 00 52 37 30 20 00 00  00 00 00 00 00 00 00 00
00000020  00 00 00 00 ... (zero to 68)
              ^^^^^^^^^^^ "R70 " at record offset 14
```

68 bytes = header + one template record carrying only the device-type tag. The
answer has the identical shape, which is why the protocol is symmetric.

### Two findings that removed risk

1. **R1 accepts an answer on one condition: byte 2 (the opcode) is `0x00`.**
   There is no checksum, magic number or length check. R1 receives its own
   broadcast and ignores it only because its opcode is `0x80`. So an answer only
   has to set byte 2 to zero to be accepted.
2. **R1 ignores the UDP sender address**; the device IP comes from *inside* the
   record. Two consequences: the answer must advertise an address reachable on
   the subnet R1 probed from, and **the MAC is not checked against any OUI** —
   real hardware can use its own address rather than borrowing RM Michaelides'
   range.

### Fallback that no longer matters, but is worth recording   [spec]
> "It is possible to access R70 with R1 using a WAN (Internet). In this case the
> automatic device detection does not work and manual adjustments have to be made."
> — R70 SW manual §1.2.1

R1 V3 exposes this as a **"Dedicated R70 addresses"** list in its interface
settings: add the unit's IP there by hand and it is reached with no broadcast
discovery at all.

---

## 5. dbCAN — the CAN side   [spec]

Source: R70 software reference manual 1.3 EN §1.3.3; TI 312 d&b Remote network 1.4 EN.

- CAN 2.0A layer 2, **11-bit identifiers**, **100 kbit/s — fixed, not changeable**.
- The R70 is a **transparent** bridge: "no direct protocol interpretation is
  implemented" in the gateway firmware. **It does not understand d&b parameters.**

### 11-bit identifier layout

| Bits | Field | Range |
|---|---|---|
| 10–9 | Object class | 0 Primary Master · 1 Secondary Master · 2 Process data from device · 3 Stream objects |
| 8–6 | Subnet | 0–7 |
| 5–0 | Device-Id | 0 = broadcast into subnet, 1–63 |

Object class outranks Device-Id in arbitration priority. Written `subnet.device`,
e.g. `0.01`. Maximum 504 amplifiers; up to two masters (primary + secondary).

Filtering uses `(received_id XOR arbitration) AND mask`; zero means the frame
passes. Default mask/arbitration `0x000` passes everything. The vendor's worked
example (mask `0x600`, arbitration `0x400`: blocks `0x001`, passes `0x401`) is a
unit test. **[spec §1.3.2 → test]**

### Physical layer   [spec, TI 312]

| | |
|---|---|
| d&b RJ45 | pin 4 CAN_H, pin 5 CAN_L, **shell = CAN ground via cable shield** |
| CiA D-SUB9 | pin 7 CAN_H, pin 2 CAN_L, pin 3 CAN_GND |
| Termination | 120 Ω both ends (d&b Z6116 RJ45 terminator) |
| Max length | 600 m at 100 kbit/s; stub ≤ 30 m each, ≤ 150 m total |
| Cable | shielded twisted pair 100–120 Ω: Cat5 F/STP, AES/EBU or DMX 110 Ω, DeviceNet |
| Nodes | ≤ 100 per segment, 504 total via repeaters |

Two RJ45s wired in parallel for daisy-chaining; shielded connectors are mandatory
because CAN ground travels on the shield.

R70 hardware for reference: 16-bit MCU, PoE 802.3af **or** 10–30 V DC / 330 mA,
galvanically isolated CAN, 10/100 Ethernet, −40 to +50 °C.

**Grounding trap [spec]:** E-PAC amplifiers with serial numbers up to 3170 do not
link CAN ground through their RJ45s. Mixing them with D6/D12 needs a D6/D12 or a
post-3171 E-PAC as the first device on the bus.

---

## 6. Observed R1 session   [capture]

Captured 2026-07-22 against R1 V3.46 with `tools/r70_emu.py`, end to end: R1
discovered the emulator, listed it, connected, and drove the bus.

**Getting R1 to connect at all is mode-gated.** The interface's activation
checkbox cannot be ticked while R1 is Online. Go **Offline, tick it, then back
Online**. Nothing in the discovery answer affects this — it is pure R1 UI state.

### Gateway initialisation, in order

| R1 sends | Meaning | Emulator |
|---|---|---|
| `0x44` | interfaces version | **silent** |
| `0x41` | HW/SW version | answered |
| `0xA4` `03 e8` | baud-rate calc interval = 1000 ms | **silent** |
| `0x57` `fe` | set CAN baud rate = **100 kbit/s** | silent |
| `0xC0` | reset device | answer with `0x40` Device ID (spec §2.10.1) |

`0x57 fe` is a nice independent confirmation: the spec's baud table gives
`0xFE` = 100 kbit/s, exactly dbCAN's fixed rate.

`0x57` and the bus scan only appear once R1 goes **Online** — before that it
stops after `0xA4`. A stalled init usually means R1 is Offline, not that the
gateway emulation is wrong.

### Bus scan

Going Online, R1 sweeps **all eight subnets** as **secondary master**
(object class 1 — R1's own preference text says "Secondary is recommended"),
repeating roughly every 35 s:

```
id=0x200  secondary-master 0.00 (broadcast)  00 01
id=0x240  secondary-master 1.00 (broadcast)  00 01
id=0x280  secondary-master 2.00 (broadcast)  00 01
id=0x2C0  secondary-master 3.00 (broadcast)  00 01
id=0x300  secondary-master 4.00 (broadcast)  00 01
id=0x340  secondary-master 5.00 (broadcast)  00 01
id=0x380  secondary-master 6.00 (broadcast)  00 01
id=0x3C0  secondary-master 7.00 (broadcast)  00 01
```

Every subnet gets the same 2-byte payload `00 01` — the device-ident request.

### Where the virtual amplifier stands   [unknown]

`tools/dbcan_device.py` answers as dbCAN **1.02** with id `0x442`
(class 2, "process data from device"). Addressing is correct and R1 accepts the
frame off the wire. But the reply **payload** is a placeholder — we echo `00 01`
— and R1 rejects it: after two scan rounds with no valid ident it issues `0xC0`
and restarts initialisation.

Completing this needs the dbCAN **application layer**, which no document we have
describes, and it is not documented here. **A transparent bridge does not need
any of this** — see §7.

## 7. What this means for dbCANary

Because the R70 does not interpret dbCAN, a faithful emulator needs **only**:

1. RMBCP framing over TCP 30000 — **done and tested** (`tools/rmbcp.py`).
2. The UDP 33333 discovery reply — **open** (§4), or bypassed via manual config.
3. A 100 kbit/s, 11-bit CAN controller doing no filtering by default.

d&b amplifier parameter semantics are **out of scope** — R1 supplies those and the
amplifiers consume them; we only carry the bytes.

---

## Sources

- *R70 Ethernet to CAN interface — Manual 1.4 EN* (DOC01816), d&b audiotechnik
- *R70 Ethernet to CAN interface — Software reference manual 1.3 EN*, d&b audiotechnik
- *TI 312 — d&b Remote network 1.4 EN* (D5312.E.01), d&b audiotechnik
- *RM Byte Command Protocol — API description*, RM Michaelides Software & Elektronik GmbH
- *Device Manual CANlink WLAN Series 2000 V1.0*, RM Michaelides (confirms RMBCP is the transport over TCP/UDP and that frames are batched into blocks)
- IEEE IAB registry, `https://standards-oui.ieee.org/iab/iab.txt`
