#!/usr/bin/env python3
"""
dbCANary rev A — copper zones and rule areas.

Run with KiCad's bundled Python:
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 zones.py

WHY THE GEOMETRY IS EXPLICIT
----------------------------
Three separations on this board are safety- or signal-critical, and none of them
can be left to DRC clearance (0.15 mm) or to zone-priority semantics:

  1. GALVANIC ISOLATION. The ADM3053 splits GND from CAN_GND. Measured pad-edge
     to pad-edge across the package there is 7.25 mm of room, so a 7.0 mm band
     is cut as an all-layer rule area: no pour, no tracks, no vias, no pads.
     The GND and CAN_GND zone outlines are then drawn to STOP at that band, so
     the gap exists geometrically and does not depend on fill order.

  2. CHASSIS MOAT. CHASSIS (RJ45 shield + Bob Smith return) must stay >=2.03 mm
     from system GND. Rather than trust zone priority, GND's outline has the
     chassis area cut out of it and the CHASSIS island is inset 2.03 mm inside
     that cut. The moat is therefore a property of the polygons.

  3. PLANE VOID UNDER THE MAGNETICS. WIZnet require no plane under the
     transformer's line side or under the RJ45. Voided on In1/In2 from y=76
     (T401's isolation line) down. It deliberately does NOT start at x=80.5,
     because U401's decoupling C403-C407 sits at x=98 and must keep its plane.
"""
import os as _os
_REPO = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import sys

import pcbnew

BOARD = _REPO + "/hardware/dbcanary.kicad_pcb"

# --- region geometry, mm ----------------------------------------------------
INSET = 0.5                      # pour pull-back from the board edge
BAR_TOP, BAR_BOT = 66.5, 73.5    # isolation band (7.0 mm inside the 7.25 available)
BAR_RIGHT = 80.5                 # isolated domain is everything left of this
MOAT = 2.03                      # chassis-to-GND, IPC creepage for mains-adjacent
CHASSIS_CUT = (80.0, 81.0, 116.0, 99.5)   # GND stays out of here entirely
VOID = (80.0, 76.0, 119.5, 99.5)          # In1/In2 void: magnetics line side + jack

# System domain: an L. Full width above the barrier, right of it below.
SYSTEM = [(20.5, 19.5), (119.5, 19.5), (119.5, 99.5),
          (BAR_RIGHT, 99.5), (BAR_RIGHT, BAR_TOP), (20.5, BAR_TOP)]
ISOLATED = [(20.5, BAR_BOT), (BAR_RIGHT, BAR_BOT), (BAR_RIGHT, 99.5), (20.5, 99.5)]
BARRIER = [(20.0, BAR_TOP), (BAR_RIGHT, BAR_TOP), (BAR_RIGHT, BAR_BOT), (20.0, BAR_BOT)]


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def poly_minus_rect(poly, r):
    """
    Subtract a rectangle from a polygon via SHAPE_POLY_SET booleans.

    Used so the chassis moat and the plane void are baked into the GND outline
    rather than relying on KiCad's zone-priority fill order.
    """
    a = pcbnew.SHAPE_POLY_SET()
    a.NewOutline()
    for x, y in poly:
        a.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
    b = pcbnew.SHAPE_POLY_SET()
    b.NewOutline()
    for x, y in rect(*r):
        b.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
    a.BooleanSubtract(b)
    return a


def net_by_suffix(board, suffix):
    """Nets are sheet-prefixed ('/Ethernet .../ETH_TCT'); match the leaf name."""
    names = [str(n) for n in board.GetNetsByName().keys()]
    # An exact match always wins. Renaming a net in the schematic leaves the old
    # sheet-prefixed name behind on the board as an empty net, so a suffix match
    # alone reports a false ambiguity.
    if suffix in names:
        return board.FindNet(suffix)
    hits = [n for n in names if n.endswith("/" + suffix)]
    if not hits:
        raise SystemExit(f"no net matching {suffix!r}")
    if len(hits) > 1:
        raise SystemExit(f"ambiguous net {suffix!r}: {hits}")
    return board.FindNet(hits[0])


def add_zone(board, layers, net, poly_or_set, name, prio=0):
    z = pcbnew.ZONE(board)
    ls = pcbnew.LSET()
    for lay in layers:
        ls.addLayer(lay)
    z.SetLayerSet(ls)
    if net is not None:
        z.SetNet(net)
    z.SetZoneName(name)
    z.SetAssignedPriority(prio)
    z.SetLocalClearance(pcbnew.FromMM(0.25))
    # Remove orphan islands rather than keeping them. The autorouter puts ~70
    # tracks through In2 and 450 through F.Cu, which chops the pours up; kept
    # islands are copper that connects to nothing and DRC rightly calls each one
    # an unconnected item (14 of them).
    z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    z.SetMinThickness(pcbnew.FromMM(0.20))
    # Solid, not thermal relief. F.Cu carries 450+ tracks, so a thermal-relieved
    # pour fragments into islands; island removal then orphans the pads and DRC
    # reports them unconnected (plus 10 starved_thermal for spokes pruned below
    # min thickness). The board is reflow-assembled by the fab, where solid
    # connections are routine, so this trades hand-rework convenience for a
    # pour that actually connects.
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    if isinstance(poly_or_set, pcbnew.SHAPE_POLY_SET):
        z.SetOutline(poly_or_set)
    else:
        pts = pcbnew.VECTOR_VECTOR2I()
        for x, y in poly_or_set:
            pts.append(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
        z.AddPolygon(pts)
    board.Add(z)
    return z


def add_rule_area(board, layers, poly, name, pour=True, tracks=True, vias=True,
                  pads=True):
    z = pcbnew.ZONE(board)
    ls = pcbnew.LSET()
    for lay in layers:
        ls.addLayer(lay)
    z.SetLayerSet(ls)
    z.SetIsRuleArea(True)
    z.SetDoNotAllowZoneFills(pour)
    z.SetDoNotAllowTracks(tracks)
    z.SetDoNotAllowVias(vias)
    z.SetDoNotAllowPads(pads)
    z.SetZoneName(name)
    pts = pcbnew.VECTOR_VECTOR2I()
    for x, y in poly:
        pts.append(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
    z.AddPolygon(pts)
    board.Add(z)
    return z


def main():
    board = pcbnew.LoadBoard(BOARD)

    # Resolve nets BEFORE removing anything. board.Remove() on the existing
    # zones leaves GetNetInfo() returning a bare SwigPyObject, so a re-run of
    # this script would die on its first net lookup. Same SWIG ordering hazard
    # as in place.py and sync_pcb.py: query first, mutate second.
    gnd = net_by_suffix(board, "GND")
    can_gnd = net_by_suffix(board, "CAN_GND")
    v3v3 = net_by_suffix(board, "VCC_3V3")
    chassis = net_by_suffix(board, "CHASSIS")

    for z in list(board.Zones()):
        board.Remove(z)

    F, B = pcbnew.F_Cu, pcbnew.B_Cu
    IN1, IN2 = pcbnew.In1_Cu, pcbnew.In2_Cu

    # System GND: L-shape with the chassis area cut out so the moat is geometric.
    gnd_poly = poly_minus_rect(SYSTEM, CHASSIS_CUT)
    # Inner layers additionally lose the magnetics/jack void.
    gnd_inner = poly_minus_rect(SYSTEM, CHASSIS_CUT)
    b2 = pcbnew.SHAPE_POLY_SET()
    b2.NewOutline()
    for x, y in rect(*VOID):
        b2.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
    gnd_inner.BooleanSubtract(b2)

    made = []
    made.append(add_zone(board, [F], gnd, gnd_poly, "GND_F"))
    made.append(add_zone(board, [B], gnd, poly_minus_rect(SYSTEM, CHASSIS_CUT), "GND_B"))
    made.append(add_zone(board, [IN1], gnd, gnd_inner, "GND_PLANE_In1"))

    # In2 stays a VCC_3V3 plane. Swapping it to a GND pour was tried and made
    # things worse (18 -> 42 unconnected): a large share of the 3V3 pads reach
    # their rail THROUGH this plane, not by track. The fragmentation it suffers
    # from the ~70 In2 tracks is real but is handled by island removal above.
    v3_inner = poly_minus_rect(SYSTEM, CHASSIS_CUT)
    b3 = pcbnew.SHAPE_POLY_SET()
    b3.NewOutline()
    for x, y in rect(*VOID):
        b3.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
    v3_inner.BooleanSubtract(b3)
    made.append(add_zone(board, [IN2], v3v3, v3_inner, "VCC_3V3_PLANE_In2"))

    # Isolated domain: CAN_GND on all four layers, its own solid reference.
    for lay, nm in ((F, "CAN_GND_F"), (IN1, "CAN_GND_In1"),
                    (IN2, "CAN_GND_In2"), (B, "CAN_GND_B")):
        made.append(add_zone(board, [lay], can_gnd, ISOLATED, nm))

    # Chassis island, inset MOAT inside the cut taken out of GND above.
    cx0, cy0, cx1, cy1 = CHASSIS_CUT
    island = rect(cx0 + MOAT, cy0 + MOAT, cx1 - MOAT, 99.5)
    made.append(add_zone(board, [F], chassis, island, "CHASSIS_F", prio=1))
    made.append(add_zone(board, [B], chassis, island, "CHASSIS_B", prio=1))

    # Rule areas.
    add_rule_area(board, [F, IN1, IN2, B], BARRIER, "ISOLATION_BARRIER")
    # No POUR and no TRACKS on the inner layers here. Allowing inner-layer
    # routing under the magnetics let the autorouter run a CHASSIS track across
    # In2 where no chassis copper exists, stranding it. Vias stay permitted so
    # the F.Cu and B.Cu chassis islands can still be stitched to each other -
    # they only pass through plane area that is voided anyway.
    # pads=False is essential: J401 and T401 LIVE in this region, and coupling
    # the pad rule to the track rule banned J401's own 11 through-hole pads.
    add_rule_area(board, [IN1, IN2], rect(*VOID), "MAGNETICS_PLANE_VOID",
                  pour=True, tracks=True, vias=False, pads=False)

    print("filling...")
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())

    pcbnew.SaveBoard(BOARD, board)
    print(f"zones: {len(made)} filled, 2 rule areas -> saved")
    # Reporting deliberately lives in verify_zones.py, a separate process: after
    # ZONE_FILLER runs, board.Zones() hands back untyped SwigPyObjects.
    return 0


if __name__ == "__main__":
    sys.exit(main())
