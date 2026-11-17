# CANary front panel

> **Status (2026-10-29): designed, routed, fab files made; never ordered or built.** DRC is
> clean with schematic parity on. The panel it sits behind has not been drawn beyond the
> drilling drawing here.

The front panel for a rack-mounted CANary: the four status LEDs and the RESET and BOOT
buttons, on an 84 x 26 mm board behind a 1U panel, fed by a 16-way ribbon from a rev B main
board's J501. Pinout and what each line does: [`../rev-b/REV-B.md`](../rev-b/REV-B.md).

| | |
|---|---|
| LEDs | D1 ON, D2 LAN, D3 CAN (green), D4 ERR (red), 3 mm, anode from FP_5V through 1 k |
| Buttons | SW2 BOOT, SW1 RESET, 6 mm tact switches |
| J1 | 2x8 IDC box header on the back, pin 1 = FP_5V |
| J2 (DNP) | 3V3, GND, SDA, SCL, FN1, FN2 for a display or more buttons |
| Holes | four M3, copper kept 3.6 mm clear, for standoffs to the panel |

The LEDs light exactly when the board's own do: the main board sinks each cathode with an
open-drain buffer. 1 k gives about 3 mA, dim on purpose for dark venues. Lower it for
brighter, 20 mA at most per line.

## Fitting it behind a panel

Board stood off 7 mm behind a 2 mm panel (M3 standoffs on the four holes).

- **LEDs**: raise them on 4 mm spacers so the dome sits in the 3.2 mm panel hole.
- **BOOT** is the 9.5 mm-tall switch: it stands 0.5 mm proud of the panel face.
- **RESET** is the 7.3 mm one: 1.7 mm behind the face, through a 2.5 mm hole, so it takes a
  pin or a paperclip and not a stray elbow.
- Hold BOOT and tap RESET for the ROM download mode. At run time BOOT is free for firmware
  (GPIO0); nothing uses it yet.

`fab/panel.dxf` and `fab/panel.pdf` are the drilling drawing: every panel hole at its place
relative to the board outline, drawn on Dwgs.User.

## Building it

```sh
<kicad python> hardware/frontpanel/scripts/build.py   # board from the schematic, routed, DRC
hardware/frontpanel/scripts/fab.sh                    # Gerbers, drill, BOM, CPL, panel drawing
```

`<kicad python>` is `/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3`.
The board is generated, so GUI edits are lost on the next build. Freerouting is not
deterministic; `build.py` routes again until DRC is clean. The BOM leaves out the holes and
anything with `Fit=DNP` (J2). Rev A's convention, since Konnect cannot set KiCad's DNP flag.
