# dbCANary rev A — layout plan

> ## ⚠ Historical. Placement and routing are **done**.
>
> This was the floorplan written *before* layout, and it is kept as the record of
> intent — the rationale in it is still why the board looks the way it does. But
> the board diverged from it during placement, and **where the two disagree the
> board file wins**:
>
> | This document said | The board actually is |
> |---|---|
> | 92 × 72 mm, outline (20, 20) → (112, 92) | **100 × 81 mm**, Edge.Cuts X 20→120, Y 19→100 |
> | 67 footprints | **76 placements**, top side only |
> | etherCON on 26 mm centres | **28 mm centres** |
> | `J102` at y ≈ 24 | y **22.60, rotation 180** — mouth on the board edge |
> | placement/routing outstanding | **routed: DRC 0 errors, 0 unconnected** |
>
> For the board as built, see [`FAB.md`](FAB.md).
> [`ENCLOSURE.md`](ENCLOSURE.md) is dimensioned from the board file and is correct.

## Board

Planned outline **(20, 20) → (112, 92)** — 92 × 72 mm, 2 mm corner radius.
**Built as 100 × 81 mm**, (20, 19) → (120, 100).

The width is set by the connectors, not by the circuit: the etherCON NE8FBH front
plate is 25 mm wide, so three side by side need ≈ 76 mm plus edge margin. There is
no point trying to make rev A smaller than that.

## Floorplan

Group each block against the connector it serves, so the fast/sensitive nets stay
short and the isolation barrier stays clean.

| Block | Parts | Target | Rationale |
|---|---|---|---|
| CAN A / CAN B | `J201`, `J202` | bottom edge, y ≈ 78, x ≈ 36 and 62 | etherCON on 26 mm centres *(built on 28 mm, at y 92)* |
| LAN | `J401` | bottom edge, y ≈ 78, x ≈ 88 | third etherCON |
| USB-C | `J102` | **top** edge, y ≈ 24, x ≈ 100 | opposite edge to the RJ45s — power/programming cable away from audio-side cabling |
| Isolated CAN | `U201`, `R202/3`, `C207`, `SW201`, `D201`, `FB201`, `C204–206` | x ≈ 40–62, y ≈ 55–70 | directly above the two CAN jacks. **Barrier runs vertically through `U201`** |
| Ethernet PHY | `U401`, `Y401`, `R401`, `C401–410` | x ≈ 82–100, y ≈ 52–70 | above the LAN jack, magnetics between PHY and jack |
| Magnetics | `T401`, `R402–405`, `C411` | x ≈ 88, y ≈ 70–76 | between `U401` and `J401`; keep the line side toward the jack |
| MCU | `U301` | x ≈ 46, y ≈ 36 | centre-left; antenna end must overhang the board edge with no copper beneath |
| Power | `U103`, `L102`, `C105–108`, `R103/4`, `F101` | x ≈ 96–108, y ≈ 30–44 | close to USB-C so `VBUS` is short |
| PD sink | `U104`, `R106/7`, `C109` | x ≈ 88, y ≈ 30 | `CC1/CC2` must be short to `J102` |
| UI | `D301–304`, `R302–305`, `SW301/2`, `J301`, `R301`, `C301–304` | left edge, x ≈ 24–34 | LEDs where a panel can see them |

## Rules that must survive layout

1. **Isolation barrier — full-stack keepout through `U201`.** No copper on any of the
   four layers may cross it, including pours and stitching vias. `CAN_GND` stays
   galvanically separate from `GND` everywhere. Put a keepout zone in before routing,
   not after.
2. **`CHASSIS` bonds to `GND` at exactly one point.** It carries the three etherCON
   shells, the USB-C shell, Bob Smith termination and the mounting hardware. Choose
   the point deliberately — near the LAN jack is conventional.
3. **`U301` antenna keepout.** The ESP32-S3-WROOM-1's antenna end needs board edge
   overhang and no copper on any layer beneath it. WiFi is a fallback path in rev A,
   but breaking it costs nothing to avoid.
4. **USB `D+`/`D-` as a ~90 Ω differential pair**, length-matched, over an unbroken
   plane. Full-speed is forgiving but there is no reason to route it badly.
5. **`Y401` 25 MHz crystal** hard against `U401` with its load caps, and a local
   ground stitch. Keep the SPI bus away from it.
6. **Keep `SW201` reachable** — it is the CAN bus terminator and gets toggled in the
   field, so it must not end up under a connector or behind the panel.

## Layer plan

| Layer | Use |
|---|---|
| F.Cu | components and short signal routing |
| In1.Cu | **solid GND** — the reference plane; do not cut it up |
| In2.Cu | power (`VCC_3V3`, `VCC_5V`), remaining signal |
| B.Cu | signal, plus `GND` pour |

`CAN_GND` gets its own isolated pour on the CAN side of the barrier, on every layer
it appears on.

## Why placement was a manual step

Placement could not be automated with this toolchain. Konnect's `place_component`,
`move_component` and `rotate_component` are all **IPC-only**, and this KiCad build's
IPC API does not implement `GetOpenDocuments`, so every one of them fails with
`AS_UNHANDLED`. There is no file-based placement tool.

It was done in the end by writing the board file directly — see
`hardware/scripts/place.py`, `zones.py`, `route_residual.py`,
`route_j102_refit.py` and `fix_orphan_pads.py`, each of which records in its
docstring what it tried and why the obvious approach failed. Freerouting is
available via Konnect's `autoroute`, but was not what got this board routed.

## Resolved: the ESP32 module drill DFM issue

This document previously flagged **12 × `drill_out_of_range`** — KiCad's stock
`RF_Module:ESP32-S3-WROOM-1` footprint has 0.2 mm thermal vias under the module's
ground pad, below the 0.3 mm minimum then in the rules.

**Resolved by accepting 0.2 mm**, which is exactly JLCPCB's minimum hole size. The
rule was relaxed to match and current DRC reports no `drill_out_of_range`. This is
now a hard constraint on the order: **0.20 mm min hole, and nobody may "optimise"
it smaller** — it is recorded as such in [`FAB.md`](FAB.md#board-specification).
