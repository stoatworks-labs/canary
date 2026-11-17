# CANary rev B

> **Status (2026-10-29): designed, routed and packaged for JLCPCB, never ordered or built.**
> The schematic is rev A's netlist plus exactly the changes below, sourcing included
> (`scripts/check_schematic.py`). The board has 0 DRC errors and 0 unconnected items, and
> every one of rev A's 778 tracks and vias is still on its expected net
> (`scripts/finish.py`). PoE is in, as option C below. Nothing here has met a soldering iron.

Rev B is rev A with its insides brought out. Every switch, LED and port gets a header or
pads in parallel, so a board can live in something other than the desktop tube, a 1U rack
box with a front panel being the obvious one. The rack front panel itself is a separate
board in [`../frontpanel`](../frontpanel), joined by a 16-way ribbon.

It lives in its own folder because rev A's files still describe board #1, which is on the
bench with its bring-up procedures and renders keyed to its copper. Rev A stays orderable
as it is.

## What changed from rev A

| Area | Rev A | Rev B |
|---|---|---|
| Front panel | the board's own LEDs and buttons, nothing else | **J501**, keyed 2x8 IDC (SMD), on the top edge: LEDs, RESET, BOOT, I2C, two spare GPIOs, 5 V and 3V3 |
| CAN | J201/J202 etherCONs, SW201 | + **J203** (CANH, CANL, CAN_GND) and **J204** (SW201 in parallel), isolated side, DNP |
| USB | J102 | + **J502** (D-, D+, GND only), DNP |
| Power | USB-C only, `VBUS -> F101 -> VCC_5V` | **PoE** (802.3af, SDAPO DP9900M-5V) or a 5 V auxiliary input (**J103**, DNP), with priority over USB through a TPS2116 power mux |
| Ethernet | PT61017PEL magnetics; Bob Smith 75 Ω straight to the shared node | **B1608S** magnetics (PoE+ rated, same land pattern); 10 nF / 100 V in series with each 75 Ω, so PoE can be detected |
| Module | ESP32-S3-WROOM-1-**N8** (C2913198), no PSRAM | ESP32-S3-WROOM-1-**N8R2** (C2913204): the same module with 2 MB of quad PSRAM, for a planned remote-access client. Same footprint and pins: quad PSRAM shares the flash bus inside the module. Rated -40 to 85 °C like the N8; the octal R8 modules are 65 °C (datasheet v1.8) |
| Mounting | none at all | four M3 holes (NPTH, copper kept 4 mm clear); two sit where a flashing fixture (not in this repository) asked for tooling holes |
| Rev B list | | W5500 reset pull-up (R413); `LED_*_K` nets renamed `LED_*_A`; SW201 labelled on the silkscreen (direction still to confirm) |

## J501, the front-panel header

On the top edge, so in a rack the ribbon heads straight for the front. Pin 1 (the triangle
on the silkscreen) is the end away from the edge: turned that way, the I2C and FN pins come
out beside their resistors and the LED pins beside their sinks, and the board routes. It is a
standard 16-way IDC ribbon, straight through: pin *n* at one end is pin *n* at the other.

| Pin | Signal | | Pin | Signal |
|---|---|---|---|---|
| 1 | FP_5V (F501, 0.35 A polyfuse) | | 2 | FP_3V3 (F502, 0.2 A polyfuse) |
| 3 | GND | | 4 | GND |
| 5 | FP_ON_N | | 6 | FP_LAN_N |
| 7 | FP_CAN_N | | 8 | FP_ERR_N |
| 9 | FP_RESET_N (EN) | | 10 | FP_BOOT_N (IO0) |
| 11 | GND | | 12 | GND |
| 13 | FP_SDA (IO1) | | 14 | FP_SCL (IO2) |
| 15 | FP_FN1 (IO38) | | 16 | FP_FN2 (IO39) |

- **LED lines are open-drain sinks**: one 74LVC1G06 per line, inverting, so a panel LED is
  lit exactly when its board LED is. Wire LED and resistor from FP_5V into the pin. Up to
  20 mA each, outputs tolerate 5.5 V. A panel LED never loads a GPIO, and nothing on the
  ribbon can reach one directly. FP_ON_N sinks whenever 3V3 is up.
- **RESET and BOOT** go out through 100 R. BOOT gains a 10 k pull-up (rev A relied on the
  module's internal one, which is too weak at the end of a ribbon). Shorting either to GND
  does what the board's buttons do. **JP501** is a bridged solder jumper: cut it and the
  ribbon can no longer reset the board, for anyone who would rather it couldn't mid-show.
- **I2C** (IO1 SDA, IO2 SCL), 4.7 k pull-ups on the board, 100 R out. Standard mode only:
  the ESD arrays add about 140 pF. That is enough for a small OLED showing the IP address.
- **FN1/FN2** (IO38, IO39): 10 k pull-ups, 100 R out, otherwise unassigned. Firmware does not
  use them yet, nor I2C.
- Every line leaving the board has an ESDA6V1-5SC6 channel on it (U505, U506).
- J501 is the SMD version of the box header so rev A's B.Cu USB pair and PD_PG can carry on
  underneath it. A through-hole header would have needed both rerouted.

## The port pads

All DNP, 2.54 mm, for whoever wants a different connector.

- **J203 CAN BUS**: CANH, CANL, CAN_GND, in parallel with both etherCONs: a terminal block,
  a panel XLR, whatever the install uses. It is on the isolated side, so wire it like the
  bus it is and keep it away from anything grounded to the chassis.
- **J204 TERM REMOTE**: SW201's two poles in parallel (TERM_A, TERM_MID, TERM_B). A remote
  2-pole switch wires TERM_A-TERM_MID and TERM_B-TERM_MID. Leave SW201 off when it is used,
  or the remote switch can only ever add termination.
- **J502 USB DATA**: D-, D+, GND. Deliberately no VBUS and no CC: a second receptacle with
  those joined to J102's would join two power sources the moment both are plugged in. A
  panel USB-C wired here needs its own 5.1 k Rd on CC to be seen by a host. Plug only one
  host in at a time. The stub is about 12 mm on a full-speed link, which does not care.
- **J103 5V AUX IN**: for a supply inside a rack box, on the same side of the power mux as
  PoE, so it too takes priority over USB. F102 (1.1 A polyfuse) and D105 (SMF5.0A) protect
  it: reversed polarity forward-biases D105 until F102 trips. D105 was an SMAJ5.0A; the
  SOD-123F fits where the PoE module left room. It sits beside the buck converter, the rest
  of its parts in the strip above the PoE module.

## Power

`VCC_5V` comes out of **U105, a TPS2116 power mux** in priority mode:

- **VIN1 = `EXT_5V`**: the PoE module's output, OR-ed through U106 (LM66100) with the
  auxiliary input. Both are supplies that cannot be unplugged by a laptop, so both beat USB.
- **VIN2 = `VBUS_FUSED`**: USB-C after F101. Used only while `EXT_5V` is absent.
- MODE is tied to VIN1; R108/R109 (100 k / 33 k) bring PR1 to its 1.0 V reference when
  `EXT_5V` falls to about 4.0 V (3.7-4.4 V across the reference's ±8 % tolerance), below
  the module's 4.75 V minimum even at the top of that range. Hand-over is
  break-before-make, about 8 µs.
- The cost of that margin: until it hands over, the mux follows `EXT_5V` down. Pull the
  PoE cable with USB attached and `VCC_5V` sags to about 4 V for a fraction of a
  millisecond (the module's capacitors under the board's load) before USB takes over. The
  3.3 V rail rides through (the AP63200 runs from 3.8 V); the ADM3053 is specified from
  4.5 V, so CAN may glitch at that moment. Not measured.

Priority matters for PoE in particular: a PoE module idling behind USB stops drawing its
maintain-power signature, the switch withdraws power, and pulling USB then browns the board
out. With the mux the module carries the board whenever it is up.

The CH224K's supply (R106) and VBUS sense (R107) stay on `VBUS_FUSED`, so the PD chip sees
USB and not the muxed rail. PD_PG still means "USB has negotiated", nothing more.

U105 lives in the pocket below the CH224K's PD traces. `VBUS_FUSED` reaches it on B.Cu from
rev A's F101 copper; its output joins `VCC_5V` through a via onto rev A's own In2 VCC_5V run,
which already feeds everything that run fed. ERC is clean: with the mux, `VCC_5V` has a
single source again, so the OR-ing error the first rev B pass carried is gone.

## Layout

The board is generated: `scripts/build.sh route` rebuilds it from rev A's routed board and
the rev B schematic in about five minutes, and **edits made in the GUI are lost on the next
run**. Stages, each its own process:

1. `sync.py` renames nets in place, so routed copper follows its net, adds the new
   footprints (`canary:` ones from `hardware/lib`), gives T401 its new value, writes every
   sourced part's LCSC / MPN / Manufacturer fields, marks the DNP pads DNP, and checks
   every pad against the netlist.
2. `layout.py` places the 53 new parts, deletes the copper the PoE rework replaces (all of
   BOB_SMITH, one ETH_CT_RD segment), clears the stitching vias the new parts and keep-outs
   land on, cuts U301's courtyard (below), adds the hole and PoE keep-outs and labels the
   silkscreen.
3. `route.py`:
   - draws the fixed pre-routes, each checked against the board and against every other
     net's pre-routes;
   - fans the new 3V3 and GND pads out to the inner planes, clear of the board edge;
   - runs Freerouting on F.Cu and B.Cu with every rev A track locked, in fresh attempts
     until one completes;
   - drops GND vias into any pour piece left with none (placement strips rev A's stitching
     from under the new parts). A pre-route that no longer fits stops the build.
4. `finish.py` refills the zones, runs DRC next to rev A's, and checks rev A's copper is
   untouched.

Things worth knowing before changing it:

- **U301's courtyard was the stock WROOM-1 box, 48 x 41 mm**: the antenna's 15 mm side
  clearance carried all the way down the module. It is now that clearance across the
  antenna strip plus the module body. The antenna keep-out rule area inside the footprint is
  unchanged. DRC notes the footprint no longer matches the library: that is this edit.
  The expansion parts sit in the band the old courtyard claimed.
- **EN and the three LED nets cross under U301 on fixed B.Cu lanes** (`route.PREROUTES`).
  Freerouting never finished all four on its own. B.Cu under the module is empty in rev A
  except PD_PG, the USB pair and the through-via field of the module's GND pad. The lanes run
  above that field, apart from CAN, which runs in the one gap below it.
- Nothing grounded may sit below y 76 on the right: that is rev A's magnetics plane void,
  where In1 has no GND and a ground via reaches nothing (the first rev B pass found that out
  with U106). U503's GND pin had the same fault from a different cause, no room for its via,
  and has a fixed one now. **DRC reports a pad with no
  way to ground as a zone-to-zone unconnected item**, which reads like a sliver of copper. It
  is a floating IC: chase every one.
- The ESD channels are grouped by where their lines leave J501: U505 takes I2C, FN and
  RESET, beside J501's upper pins; U506 takes the LED sinks and BOOT. Freerouting only
  finished reliably once the placement matched the pinout like that.
- **VCC_5V's run west to the ADM3053's feed is fixed too**, between J501's last two pad
  rows. Rev A's F.Cu run across J501's spot had to go; Freerouting replaced it reliably
  until EXT_5V started sharing the corridor, then failed it in six attempts out of six.
- **The TPS2116 is fanned out by hand.** Its 0.5 mm pitch leaves exactly 0.2 mm between a
  0.3 mm track and the next pin, which is the clearance rule, so Freerouting's 0.4 mm power
  tracks cannot get in. MODE and VIN1 meet under the body, as do the two VOUT pins.
- pcbnew traps that bit here, on top of those in `../scripts/README.md`. `GetCourtyard()` is
  empty until `BuildCourtyardCaches()`, so every courtyard test passes. A save hands a via
  under a new pad to the pad's net. Importing a Specctra session into a board drops every
  track the session does not hold, which is all of rev A's. `finish.py`'s frozen-copper
  check exists because of the second. KiCad 10's `FOOTPRINT` has no `GetFieldByName()`:
  find a field by walking `GetFields()`.

## PoE

Option C from the costing below: the **SDAPO DP9900M-5V** (U402), an isolated 802.3af
powered-device module, 5 V at up to 1.8 A (9 W at 70 °C), with no class pins, so it
draws class 0 power from the switch.

- **D401** rectifies mode A (T401's centre taps, the data pairs), **D402** mode B (the
  spare pairs), so the board takes power whichever way a switch or injector supplies it.
  **D403**, an SMAJ58A, clamps the rectified input, as SDAPO's application circuit has it.
- U402's output, `EXT_5V`, has 47 µF + 100 nF at the module (C418, C419) and goes to the
  power mux above. ADJ is open: 5.00 V.
- **The module needs 100 mA of load** or it may whine and drop the switch's
  maintain-power signature. The board's own draw is well over that (the W5500 alone takes
  about 130 mA at 3.3 V, plus the S3 and the ADM3053's isoPower), but it has not been
  measured, so there is no bleed resistor.
- **Bob Smith termination**: rev A tied the four 75 Ω resistors (R402-R405) straight to one
  node, about 150 Ω between the PoE pairs: a real switch fails detection, a passive injector
  heats the resistors. Each now has 10 nF / 100 V in series (C414-C417). C415 sits on R403's
  line side rather than its Bob Smith side, where there was room; in series it is the same.
- **T401 is now the CND-tek B1608S** (LCSC C507596), PoE+ rated at 720 mA per port.
  Checked against its drawing: pads 2.00 x 0.75 mm on 1.27 mm pitch, 10.40 mm across the
  rows, so pad centres 4.20 mm from the middle. Rev A's PT61017PEL footprint has them at
  4.26 mm with 1.57 mm pads, which covers the B1608S's feet (tips at 4.75 ± 0.25 mm). Same
  pinout, pin for pin, so the footprint stays and only the part changes.

### Layout and isolation

U402 stands on end in the bottom-right corner, its input pins (5-8) along the board edge
and its output pins (1-4) on the GND side, 10.8 mm across the module. The bridges sit below
it with their AC pins facing the Bob Smith network, the TVS below them. Every PoE
connection is a fixed route (`route.PREROUTES`): VIN- runs down the board edge outside the
module's VIN+ pins, VIN+ runs down under the bridges between their pad rows, mode A's AC
links run on B.Cu under the Bob Smith network, mode B's on F.Cu either side of C411.

`KEEPOUT_POE` keeps every pour off the primary side, on all four layers: the In1 GND and
In2 3V3 planes are cut back under the module's input column, and GND and CHASSIS stop at
least 2 mm from the input pads on the west. The north edge stops 1.4 mm short of pin 8,
because C106's 3V3 via just beyond it needs the plane. The USB shield's B.Cu chassis run
used to end in the chassis pour here; it now carries on into the pour below the TVS.

What this does not do: **rev A's line side was never laid out for a 1500 V hipot.** Its
CHASSIS pour and the edge of its GND pour come within 0.25 mm of the transformer's line-side
traces in places (that is rev A's zone clearance, and the 2 kV Bob Smith capacitor is its
only deliberate barrier). The PoE parts keep their distance; the copper they connect to does
not. Nothing here has seen a hipot tester.

### What to check before ordering

- **The DP9900M footprint is drawn from SDAPO's package drawing** (`hardware/lib/
  canary.pretty/SDAPO_DP9900M.kicad_mod`): pin centres 2.54 mm and 13.57 mm apart, rows
  11.38 mm apart, pads 1.5 x 3.5 mm reaching 5.4-8.9 mm from the middle to take a foot that
  leaves the body at 5.69 mm and ends at 8.46 mm. LCSC's own footprint for C5380106 was not
  compared (its API refused the fetch). Put a real module on a 1:1 print before ordering.
- **71 in stock at LCSC** when this was written. The through-hole DP9900LP-5V (C5380108,
  487 in stock) is the fallback, on a different footprint.
- **Height: 13.35 mm (13.85 max).** The earlier two-shell "lozenge" case (superseded; its
  outputs are not in this repository, see `hardware/enclosure/3dp/README.md`) leaves about
  24 mm above the board at that corner; a flat enclosure needs checking.

### What it costs

Prices fetched on 2026-10-29: LCSC/JLC through JLC's parts API, Silvertel from DigiKey UK
at an assumed $1.30 per £1. Farnell and Mouser refused the fetch.

| Option | Added per board @10 / @100 | Area | Assembly |
|---|---|---|---|
| A: Silvertel **Ag9705-FL** (the docs' "Ag97005-FL" is a typo) | $10.64 / $10.19, plus hand-fitting | ~1,250 mm² | by hand or PCBWay; JLC cannot source it |
| B: TPS23753A + HanRun HR051067 flyback, after Espressif's PoE board | $7.49 / $3.05 (JLC fees included) | ~900 mm² (estimate) | JLC, ~45 parts |
| **C: SDAPO DP9900M-5V (chosen)** | $6.79 / $5.12 | ~550 mm² | JLC, ~6 parts |

The totals include the Bob Smith capacitors, the T401 swap (which saves $0.88 a board) and
the power mux. B stays the fallback if the module's stock runs dry: the cheapest at volume,
at the cost of laying out a flyback.

## Fab package

`fab/` is made from the routed board by `scripts/fab.py` (run it after `build.sh route`):

| Folder | What is in it |
|---|---|
| `fab/generic/` | gerbers and drill files, zipped (rev A's layer set and drill options; `fab.py` also leaves them loose in `gerbers/`, not tracked in git), IPC-D-356 netlist, CPL, and a BOM of every placed part, one line per orderable part |
| `fab/jlcpcb/` | the same gerbers, and the BOM and CPL from the JLC Fabrication Toolkit's own CLI, CPL rotations corrected from kicad-jlcpcb-tools' database as rev A's were |

Sourcing is the board's own LCSC / MPN / Manufacturer fields: rev A's parts keep the ones rev
A's board carries, and every new part's come from `plan.PART_NUMBERS`, written into the
schematic and checked by `check_schematic.py`. The DNP pads (J103, J203, J204, J502) carry
KiCad's DNP attribute and stay out of both BOMs and both CPLs. As on rev A, the etherCONs,
SW201 and the debug header have no LCSC part: hand-fit or customer-supplied.

As generated: 120 placements; the generic BOM is 57 lines of fitted parts plus the four DNP
pads, the JLC BOM 67 lines (the toolkit groups by value string). Five lines have no LCSC
part, the same five as rev A.

**Check every polarised part in JLC's placement preview before paying.** The rotation
database corrected 13 placements (the SOT-23s, SOT-353s, SOT-363, SSOP, SOIC, LQFP, USB-C)
and has no entry for U402 (DP9900M), D401/D402 (TO-269AA), D403 (SMA), D105 (SOD-123F),
U105 (SOT-583) or J501, so those go out at KiCad's rotation. A bridge or the module turned
the wrong way round is a dead board, or a shorted PoE port.

J501's part, the XFCN BH254VS-16P (C19190396), was checked against KiCad's SMD box-header
footprint: same 2.54 mm pitch, and KiCad's 1.02 x 5.0 mm pads (1.3-6.3 mm from the middle)
cover XFCN's recommended 1.1 x 4.0 mm (1.25-5.25 mm) and its feet.

## Firmware

Nothing has to change for the LEDs or buttons: they are the same GPIOs. To use the rest,
`components/board/include/board.h` gains I2C on IO1/IO2 and FN1/FN2 on IO38/IO39; neither is
written yet. IO39 is also MTCK, harmless while JTAG goes over USB as it does now.

The N8R2's PSRAM does nothing until the image enables it: `CONFIG_SPIRAM` with
`CONFIG_SPIRAM_MODE_QUAD`. With `CONFIG_SPIRAM_IGNORE_NOTFOUND` as well, one image should
boot on both revisions, using PSRAM where a rev B has it; that has not been tried. Today's
images leave PSRAM off and run on rev B unchanged.

## What is and is not verified

| | |
|---|---|
| Schematic is rev A + exactly these changes, sourcing included | **yes**, `check_schematic.py`, which fails when the plan is perturbed |
| ERC | **0 errors**; warnings are the same-name local/global labels rev A has too |
| DRC | **0 errors, 0 unconnected**; silkscreen warnings on the new parts remain |
| Rev A copper unchanged | **yes**, 778 items, `finish.py` |
| B1608S on T401's pads | **yes**, against CND-tek's drawing |
| N8R2 for the N8 (2026-10-31) | fields only: copper, gerbers and drill identical to the N8 package apart from timestamps, DRC still 0 / 0. 18,138 at JLC that day ($4.60 each, $3.17 at 100), against the N8's 1,894. Its PSRAM has never run on a board here |
| DP9900M footprint | drawn from SDAPO's package drawing; **not** compared with LCSC's footprint or a real module |
| PoE detection, class, power-up | **no**: never powered from a switch or injector |
| Isolation | **no hipot**; rev A's line side is 0.25 mm from its pours in places |
| Fab package | **made** (`fab/`), never uploaded |
| Built, powered, tested | **no** |
| SW201's positions on the silk | "TERM 120R = BOTH ON", no arrow: the footprint marks "on" on the pins 3/4 side but its 3D model's arrow points the other way. Look at board #1's switch, then add the arrow |
