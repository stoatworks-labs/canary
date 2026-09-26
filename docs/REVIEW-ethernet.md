# Ethernet section — blocking defects found before layout

A datasheet/appnote sweep against WIZnet's W5500 guides, the Bourns PT61017PEL
datasheet, Espressif's ESP32-S3 hardware design guidelines and JLCPCB's published
capabilities turned up **functional schematic gaps**, not just layout preferences.
These must be fixed before a board is worth fabricating. (The raw sweep output is
not included in the public repo.)

## MUST FIX — the Ethernet link will not work reliably as drawn

### 1. `ETH_PHY_CT` is floating
`T401` pins 10 and 15 (the PHY-side centre taps) are tied to each other and to
**nothing else** — verified in the exported netlist:

```
ETH_PHY_CT   2 nodes: T401.10, T401.15
```

WIZnet's external-magnetics reference feeds the transmit centre tap from the
analogue 3V3 rail through a series resistor, with the centre taps decoupled to
ground. As drawn there is no DC bias path for the transformer.

**Add:** 10 Ω 1% from 3V3 to TCT, plus centre-tap decoupling (WIZnet reference
uses 10 nF and 22 nF), and a series capacitor on the RX centre tap (6.8 nF).

### 2. No MDI termination resistors
WIZnet's reference fits **49.9 Ω 1%** on each of `ETH_TXP`, `ETH_TXN`, `ETH_RXP`,
`ETH_RXN`. The schematic has none — each MDI net has exactly two nodes, W5500 to
transformer. Without termination the line impedance is wrong and the transmit eye
will be out of spec.

**Add:** 4 × 49.9 Ω 1%, placed hard against `T401` on the system-ground side.

### 3. Crystal network incomplete
WIZnet's reference oscillator is a 25 MHz crystal **plus a 1 MΩ feedback resistor
across XI–XO and a 0 Ω series resistor in the XO leg**. Neither is present.

Load caps are also worth revisiting: `C401`/`C402` are 22 pF, while WIZnet's
shipping reference uses 18 pF. Note the W5500 datasheet states CL = 18 pF while the
reference fits 18 pF *to ground on each pin*, which implies ≈9 pF effective — an
inconsistency in WIZnet's own documents. **Use 18 pF, matching their proven
reference**, and confirm against the crystal actually purchased.

Crystal spec to buy against: 25 MHz, **±30 ppm at 25 °C** (datasheet §5.5.3),
±3 ppm/yr ageing, C0 ≤ 7 pF. The current `Y401` value field says 10 ppm, which is
tighter than required and therefore fine.

### 4. No ESD protection on the Ethernet line side
The CAN side has `D201` (NUP2105L). The Ethernet line side has none. WIZnet
recommends a TVS array on the line side with a metal-shell jack.

## MUST OBSERVE during layout

| Rule | Value | Source |
|---|---|---|
| Void **all** planes under `T401`, under `J401`, and in the gap between them — every layer | no plane copper at all | WIZnet HDG "Parts Placement"; Microchip AN18.6 §2.5 |
| Chassis-ground island to system ground | **> 2.03 mm** (80 mil) | WIZnet HDG "ESD & EMI" |
| `T401` → `J401` spacing | **> 2.5 mm and < 25 mm** | WIZnet HDG (both bounds stated) |
| MDI pairs | 100 Ω differential, **no vias, no layer changes**, 45° corners only | WIZnet HDG "MDI routing" |
| Intra-pair gap | ≤ 10 mil edge-to-edge | WIZnet MDI table |
| Pair-to-pair spacing | ≥ 20 mil (WIZnet), 50–100 mil preferred (Pulse) | WIZnet / Pulse |
| Intra-pair length match | ≤ 1.25 mm (50 mil) | Pulse; WIZnet gives no number |
| `R401` (EXRES1) to `U401` | ≤ 7 mm, short direct ground return | Microchip AN18.6 §3.2 |
| Ground pour between TX and RX pairs | required unless well separated | WIZnet |

**Current placement:** `T401`→`J401` = 18.4 mm ✅, `U401`→`T401` = 14.0 mm ✅,
`Y401`→`U401` = 11.2 mm ✅, but **`R401`→`U401` = 10.6 mm ✗** (wants ≤ 7 mm).

There is also a genuine **conflict** worth knowing: WIZnet wants the W5500 *close*
to the magnetics (< 25 mm) while Microchip and Pulse want the PHY ≥ 25 mm *away*
for EMI. ~25 mm satisfies both; 14 mm favours WIZnet's rule, which is the one that
governs signal integrity here.

## ESP32-S3 placement — current placement is the position Espressif advises against

- The **real** antenna keep-out is **18 × 6 mm** (datasheet §11.1), not the
  48 × 21 mm that KiCad's stock footprint encodes. KiCad's zone is effectively the
  "15 mm clear all round" recommendation baked in.
- Espressif: **place the module in a board corner on the antenna feed-point side.
  Mid-edge is explicitly not recommended**, and centre-of-board with clearance
  hollowed on all four sides is prohibited.
- `U301` is currently mid-top-edge at x = 54 — the not-recommended position. It
  should move to a corner in a placement revision.
- Ground pour **is wanted** under the module body (everything outside the antenna
  strip), with dense ground stitching up to the keep-out boundary.

## JLCPCB assembly constraints that affect this board

- **Component body must be ≥ 2.5 mm from the board edge** for assembly — far
  stricter than the 0.3 mm copper rule, and it governs every edge connector here.
- **Parts overhanging the outline need a custom assembly fixture** (2 fixtures at
  1–29 pcs). The overhanging ESP32-S3 antenna triggers this.
- **Through-hole parts are hand-soldered**, not machine placed: $3.50 flat plus
  $0.0173/joint, and +1 day. The three etherCONs are 11 pads each — budget for it.
- `drill_out_of_range` ×12 (U301's 0.2 mm thermal vias) has a free fix:
  JLCPCB charges for sub-0.3 mm drills **only if the via diameter is ≤ 0.4 mm**.
  A 0.2 mm drill on a **≥ 0.45 mm** pad is free on multilayer. So either widen
  those via pads to 0.45 mm or relax `min_through_hole_diameter` to 0.2 mm — no
  surcharge either way, contrary to my earlier assumption that 0.2 mm was
  non-standard.
- Minimum trace/space on 4-layer is 0.09 mm but **anything in the 3.0–3.5 mil band
  adds +20 % to the order**. Our 0.15 mm rules sit comfortably in the free tier.
