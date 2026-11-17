#!/usr/bin/env python3
"""
Route rev B's new connections onto rev A's frozen copper.

    <kicad python> hardware/rev-b/scripts/route.py    # run by build.sh route

1. Net class "Power" (0.4 mm) for the 5 V nets rev B adds or re-routes, and
   "PoE" (0.5 mm, 0.3 mm clearance) for the rectified PoE input.
2. Fanout: every new SMD pad on GND or VCC_3V3 gets a short stub and a via
   into the In1 GND / In2 3V3 planes, where the plane can take one.
3. Zones refilled, and DRC asked which nets still have unconnected items.
4. Freerouting, outer layers only (In1/In2 exported as power planes), with
   every existing track and via locked so it cannot move rev A's routing.
5. The session's copper is added to the board only on the nets step 3 listed,
   and only where the board does not already have it. Freerouting cannot see
   pours, so elsewhere it "finishes" power nets the planes already join; and
   importing a session straight into the board drops every track the session
   does not hold, which is all of rev A's.
"""
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
REVB = os.path.normpath(os.path.join(HERE, ".."))
BOARD = os.path.join(REVB, "canary.kicad_pcb")
PRO = os.path.join(REVB, "canary.kicad_pro")
WORK = os.path.join(REVB, "route")   # git-ignored
KICAD_CLI = os.environ.get("KICAD_CLI", "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli")
FREEROUTING = os.environ.get(
    "FREEROUTING", os.path.expanduser("~/.local/share/freerouting/2.5.0/freerouting-2.5.0.jar"))
PASSES = 30
ATTEMPTS = 6
MM = pcbnew.FromMM

sys.path.insert(0, HERE)
from layout import PLACE  # noqa: E402

PWR = "/Power — PoE + USB-C PD, 5V and 3V3/"
EXP = "/Expansion — front-panel header, port pads, mounting/"
ETH = "/Ethernet — W5500 SPI, PoE magjack, etherCON/"
POWER_NETS = ["VCC_5V", "EXT_5V", PWR + "VBUS_FUSED", PWR + "AUX_FUSED", PWR + "VIN_AUX",
              EXP + "FP_5V", EXP + "FP_3V3"]
POE_NETS = [ETH + "POE_VP", ETH + "POE_VN"]
FANOUT_NETS = {"GND": pcbnew.In1_Cu, "VCC_3V3": pcbnew.In2_Cu}
VIA_D, VIA_DRILL, STUB_W, CLEAR = 0.6, 0.3, 0.3, 0.2
EDGE_CLEAR = 0.5   # the board's copper-to-edge rule


def done(code=0):
    sys.stdout.flush()
    os._exit(code)


def set_power_class(b):
    ns = b.GetDesignSettings().m_NetSettings
    for name, width, clear in (("Power", 0.4, 0.2), ("PoE", 0.5, 0.3)):
        nc = pcbnew.NETCLASS(name)
        nc.SetTrackWidth(MM(width))
        nc.SetClearance(MM(clear))
        nc.SetViaDiameter(MM(0.6))
        nc.SetViaDrill(MM(0.3))
        ns.SetNetclass(name, nc)
    old = json.load(open(PRO, encoding="utf-8"))["net_settings"].get("netclass_patterns", [])
    ns.ClearNetclassPatternAssignments()
    for a in old:
        if a["pattern"] not in POWER_NETS + POE_NETS:
            ns.SetNetclassPatternAssignment(a["pattern"], a["netclass"])
    for n in POWER_NETS:
        ns.SetNetclassPatternAssignment(n, "Power")
    for n in POE_NETS:
        ns.SetNetclassPatternAssignment(n, "PoE")
    ns.RecomputeEffectiveNetclasses()
    b.SynchronizeNetsAndNetClasses(True)


def copper(b):
    """(shape, net code, layer set) for everything a new via must clear."""
    out = []
    for f in b.GetFootprints():
        for p in f.Pads():
            out.append((p.GetEffectivePolygon(pcbnew.F_Cu, pcbnew.ERROR_INSIDE), p.GetNetCode(),
                        p.GetLayerSet(), p))
    return out


def via_fits(b, pads, tracks, pt, netcode, keepouts, inside):
    if not inside.Contains(pt):   # the board edge's clearance, which nothing else checks
        return False
    r = MM(VIA_D / 2 + CLEAR)
    for poly, code, layers, p in pads:
        if code == netcode and code != 0:
            continue
        if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD:
            if p.GetLayerSet().Contains(pcbnew.F_Cu) and poly.Collide(pt, r):
                return False
        elif poly.Collide(pt, r) or math.hypot(pt.x - p.GetPosition().x, pt.y - p.GetPosition().y) < \
                MM(VIA_D / 2 + 0.25) + max(p.GetDrillSize().x, p.GetSize(pcbnew.F_Cu).x) // 2:
            return False
    for t in tracks:
        if t.GetClass() == "PCB_VIA":
            # every via, its own net's too: a pad a pre-route already gave a via
            # still gets fanned out, and two drills 0.1 mm apart is a fab problem
            if math.hypot(pt.x - t.GetPosition().x, pt.y - t.GetPosition().y) < \
                    MM(VIA_D / 2 + CLEAR) + t.GetWidth(pcbnew.F_Cu) / 2:
                return False
        elif t.GetNetCode() == netcode:
            continue
        else:
            if pcbnew.SEG(t.GetStart(), t.GetEnd()).Distance(pt) < r + t.GetWidth() / 2:
                return False
    for z in keepouts:
        o = z.Outline()
        if o.Contains(pt) or o.Outline(0).Collide(pt, MM(VIA_D / 2)):
            return False
    return True


def stub_clear(pads, tracks, a, bpt, netcode):
    seg = pcbnew.SEG(a, bpt)
    r = MM(STUB_W / 2 + CLEAR)
    for poly, code, layers, p in pads:
        if code == netcode or not p.GetLayerSet().Contains(pcbnew.F_Cu):
            continue
        if poly.Collide(seg, r):
            return False
    for t in tracks:
        if t.GetNetCode() == netcode or not t.IsOnLayer(pcbnew.F_Cu):
            continue
        if t.GetClass() == "PCB_VIA":
            if seg.Distance(t.GetPosition()) < r + t.GetWidth(pcbnew.F_Cu) / 2:
                return False
        elif seg.Distance(pcbnew.SEG(t.GetStart(), t.GetEnd())) < r + t.GetWidth() / 2:
            return False
    return True


def fanout(b):
    """Plan every via first, then add them all: pcbnew's bindings go bad when
    queries and mutations interleave (hardware/scripts/README.md)."""
    keepouts = [z for z in b.Zones() if z.GetIsRuleArea() and z.GetDoNotAllowVias()]
    for f in b.GetFootprints():
        keepouts += [z for z in f.Zones() if z.GetDoNotAllowVias()]
    pads, tracks = copper(b), list(b.GetTracks())
    edge = b.GetBoardEdgesBoundingBox()
    inside = pcbnew.BOX2I(edge.GetPosition(), edge.GetSize())
    inside.Inflate(-MM(EDGE_CLEAR + VIA_D / 2))
    planned, failed = [], []   # (net code, pad centre, via point)
    for ref in PLACE:
        f = b.FindFootprintByReference(ref)
        for p in f.Pads():
            name = p.GetNetname()
            if name not in FANOUT_NETS or p.GetAttribute() != pcbnew.PAD_ATTRIB_SMD:
                continue
            code, c, body = p.GetNetCode(), p.GetPosition(), f.GetPosition()
            away = math.atan2(c.y - body.y, c.x - body.x) if c != body else 0.0
            spot = None
            for dist in (0.9, 1.2, 1.5, 1.9):
                for k in range(16):
                    a = away + (k + 1) // 2 * (1 if k % 2 else -1) * math.pi / 8
                    pt = pcbnew.VECTOR2I(int(c.x + MM(dist) * math.cos(a)), int(c.y + MM(dist) * math.sin(a)))
                    if any(math.hypot(pt.x - q.x, pt.y - q.y) < MM(VIA_D + CLEAR) for _, _, q in planned):
                        continue
                    if via_fits(b, pads, tracks, pt, code, keepouts, inside) and stub_clear(pads, tracks, c, pt, code):
                        spot = pt
                        break
                if spot:
                    break
            if spot:
                planned.append((code, c, spot))
            else:
                failed.append(f"{ref}.{p.GetNumber()}")
    for code, c, pt in planned:
        t = pcbnew.PCB_TRACK(b)
        t.SetStart(c)
        t.SetEnd(pt)
        t.SetWidth(MM(STUB_W))
        t.SetLayer(pcbnew.F_Cu)
        t.SetNetCode(code)      # net before Add(), and never touch it after
        b.Add(t)
        v = pcbnew.PCB_VIA(b)
        v.SetPosition(pt)
        v.SetWidth(MM(VIA_D))
        v.SetDrill(MM(VIA_DRILL))
        v.SetNetCode(code)
        b.Add(v)
    print(f"fanout: {len(planned)} vias" + (f", no room for {' '.join(failed)}" if failed else ""))


# Connections Freerouting leaves open, drawn by hand onto copper that does not
# move between builds (rev A's, or a placed part's pads). (net, layer, width
# mm, points mm). Each segment is clearance-checked before it goes on.
PREROUTES = [
    # U105 (TPS2116, turned 180) at 0.5 mm pitch: west pins MODE, VIN2, VOUT,
    # ST; east PR1, VIN1, VOUT, GND. VOUT's two pins joined under the body, out
    # west to a via on rev A's In2 VCC_5V run, which carries it to everything.
    ("VCC_5V", pcbnew.F_Cu, 0.3, [(114.86, 40.55), (116.34, 40.55)]),
    ("VCC_5V", pcbnew.F_Cu, 0.3, [(114.86, 40.55), (114.3, 40.55), (113.8, 41.05)]),
    ("VCC_5V", pcbnew.F_Cu, 0.5, [(113.8, 41.05), (105.33, 41.05), (104.83, 41.55)]),
    ("VCC_5V", "via", 0.6, [(104.83, 41.55)]),
    # On west between J501's last two pad rows to rev A's via at (80.5, 42.8), the
    # ADM3053's In2 feed, whose F.Cu run across J501 is gone, and up to F501.
    # Freerouting found this only some of the time once EXT_5V shared the corridor.
    ("VCC_5V", pcbnew.F_Cu, 0.4, [(104.83, 41.55), (104.18, 42.2), (81.116, 42.2), (80.497, 42.819)]),
    ("VCC_5V", pcbnew.F_Cu, 0.4, [(80.4, 37.4), (80.4, 42.72)]),
    # USB side: down from rev A's F101 -> R107 copper on B.Cu, under the CH224K's
    # PD traces, up beside C110 and into VIN2
    (PWR + "VBUS_FUSED", "via", 0.6, [(113.829, 34.7), (113.829, 38.2)]),
    (PWR + "VBUS_FUSED", pcbnew.B_Cu, 0.4, [(113.829, 34.7), (113.829, 38.2)]),
    (PWR + "VBUS_FUSED", pcbnew.F_Cu, 0.3, [(113.829, 38.2), (114.72, 38.2)]),
    (PWR + "VBUS_FUSED", pcbnew.F_Cu, 0.3, [(113.829, 38.2), (113.7, 38.33), (113.7, 40.05), (114.86, 40.05)]),
    # EXT_5V: MODE to VIN1 under the body, then C112 and R108. Route.py's
    # Freerouting run takes it on to U402.
    ("EXT_5V", pcbnew.F_Cu, 0.25, [(114.86, 39.55), (115.6, 39.55), (115.6, 40.05), (116.34, 40.05)]),
    ("EXT_5V", pcbnew.F_Cu, 0.25, [(116.34, 40.05), (117.0, 40.05), (117.6, 40.65), (117.6, 40.72)]),
    ("EXT_5V", pcbnew.F_Cu, 0.25, [(117.6, 40.72), (118.5, 40.72), (118.91, 40.31), (118.91, 39.35)]),
    (PWR + "MUX_PR1", pcbnew.F_Cu, 0.25, [(116.34, 39.55), (117.5, 39.55), (117.89, 39.16), (117.89, 38.25)]),
    # U402's output pins joined, out to C418 and U106's output
    ("EXT_5V", pcbnew.F_Cu, 0.8, [(102.45, 57.775), (102.45, 60.315)]),
    ("EXT_5V", pcbnew.F_Cu, 0.5, [(102.45, 57.775), (102.45, 56.0), (101.5, 55.05)]),
    ("EXT_5V", pcbnew.F_Cu, 0.3, [(102.45, 56.0), (102.862, 55.588), (102.862, 55.15)]),
    # and to U105: along the strip's lower edge, up the empty B.Cu corridor west of
    # the chassis run, along under L102 and into C112/R108. Freerouting's version
    # took the corridor VCC_5V needs.
    ("EXT_5V", pcbnew.F_Cu, 0.4, [(102.45, 56.0), (109.6, 56.0)]),
    ("EXT_5V", pcbnew.F_Cu, 0.4, [(102.45, 56.0), (96.4, 56.0), (95.92, 55.52), (95.92, 54.5)]),   # C419, round C418's GND pad
    ("EXT_5V", "via", 0.6, [(109.6, 56.0), (109.6, 42.9)]),
    ("EXT_5V", pcbnew.B_Cu, 0.4, [(109.6, 56.0), (109.6, 42.9)]),
    ("EXT_5V", pcbnew.F_Cu, 0.4,
     [(109.6, 42.9), (118.2, 42.9), (118.7, 42.4), (118.7, 41.0), (118.5, 40.72)]),
    # PoE primary, all of it fixed. VIN- runs down the board edge outside U402's
    # VIN+ pins; VIN+ runs down under the bridges between their pad rows.
    (ETH + "POE_VN", pcbnew.F_Cu, 0.5, [(116.75, 57.775), (116.75, 60.315)]),
    (ETH + "POE_VN", pcbnew.F_Cu, 0.5,
     [(118.2, 60.315), (119.25, 61.365), (119.25, 89.6), (118.25, 90.6), (117.0, 90.6)]),
    (ETH + "POE_VN", pcbnew.F_Cu, 0.5, [(119.25, 79.43), (117.075, 79.43)]),
    (ETH + "POE_VN", pcbnew.F_Cu, 0.5, [(119.25, 84.83), (117.075, 84.83)]),
    (ETH + "POE_VP", pcbnew.F_Cu, 0.5, [(116.75, 73.885), (116.75, 76.425)]),
    (ETH + "POE_VP", pcbnew.F_Cu, 0.5, [(115.6, 76.6), (115.6, 87.9), (113.0, 90.5)]),
    (ETH + "POE_VP", pcbnew.F_Cu, 0.5, [(115.6, 81.97), (117.075, 81.97)]),
    (ETH + "POE_VP", pcbnew.F_Cu, 0.5, [(115.6, 87.37), (117.075, 87.37)]),
    # Bridge AC inputs. Mode A: CT_TD from a via on rev A's diagonal, along B.Cu
    # under the Bob Smith network; CT_RD on from rev A's B.Cu run to its via.
    # Mode B: the spares on F.Cu, either side of C411.
    (ETH + "ETH_CT_TD", "via", 0.6, [(98.0, 82.825), (108.9, 81.97)]),
    (ETH + "ETH_CT_TD", pcbnew.B_Cu, 0.3, [(98.0, 82.825), (98.7, 82.125), (108.745, 82.125), (108.9, 81.97)]),
    (ETH + "ETH_CT_TD", pcbnew.F_Cu, 0.3, [(108.9, 81.97), (110.925, 81.97)]),
    (ETH + "ETH_CT_RD", pcbnew.B_Cu, 0.3,
     [(103.5, 93.5), (104.1, 92.9), (108.95, 92.9), (109.75, 92.1), (109.75, 79.43)]),
    (ETH + "ETH_CT_RD", "via", 0.6, [(109.75, 79.43)]),
    (ETH + "ETH_CT_RD", pcbnew.F_Cu, 0.3, [(109.75, 79.43), (110.925, 79.43)]),
    (ETH + "ETH_CT_RD", pcbnew.F_Cu, 0.25, [(102.0, 92.98), (102.52, 93.5), (103.5, 93.5)]),
    (ETH + "ETH_SPARE_1", pcbnew.F_Cu, 0.3,
     [(105.0, 86.825), (106.0, 86.825), (106.0, 85.9), (106.6, 85.3), (109.9, 85.3), (110.37, 84.83),
      (110.925, 84.83)]),
    (ETH + "ETH_SPARE_2", pcbnew.F_Cu, 0.3,
     [(105.0, 90.825), (105.0, 91.6), (105.4, 92.0), (109.2, 92.0), (109.6, 91.6), (109.6, 88.2),
      (110.43, 87.37), (110.925, 87.37)]),
    # Bob Smith: each 75R to its DC block; the blocks' far ends, R403 and C411
    # joined, crossing the spares on B.Cu
    (ETH + "BS_TD", pcbnew.F_Cu, 0.25, [(102.0, 85.175), (102.0, 83.98)]),
    (ETH + "BS_SPARE_1", pcbnew.F_Cu, 0.25, [(105.0, 85.175), (105.0, 83.98)]),
    (ETH + "BS_SPARE_2", pcbnew.F_Cu, 0.25, [(105.3, 89.175), (106.265, 89.42)]),
    (ETH + "BS_RD", pcbnew.F_Cu, 0.25, [(102.0, 90.825), (102.0, 92.02)]),
    (ETH + "BOB_SMITH", pcbnew.F_Cu, 0.25, [(102.0, 83.02), (105.0, 83.02)]),
    (ETH + "BOB_SMITH", "via", 0.6, [(103.5, 83.02), (103.5, 88.2)]),
    (ETH + "BOB_SMITH", pcbnew.B_Cu, 0.25, [(103.5, 83.02), (103.5, 88.2)]),
    (ETH + "BOB_SMITH", pcbnew.F_Cu, 0.25, [(103.5, 88.2), (102.6, 88.2), (102.0, 88.8)]),
    (ETH + "BOB_SMITH", pcbnew.F_Cu, 0.25, [(103.5, 88.2), (107.4, 88.2), (108.0, 88.8), (108.0, 89.1)]),
    (ETH + "BOB_SMITH", pcbnew.F_Cu, 0.25, [(106.265, 90.38), (106.9, 90.38), (107.4, 89.88)]),
    # CHASSIS: the USB shield's B.Cu run ended in the chassis pour here, which
    # KEEPOUT_POE now clears; carry it on into the pour below the TVS
    ("CHASSIS", pcbnew.B_Cu, 0.5, [(112.5, 90.0), (112.5, 91.0), (110.6, 92.9)]),
    # J502 pin 1 down the B.Cu gap between J502's pins and the CHASSIS track,
    # onto rev A's USB_DM meander
    ("USB_DM", pcbnew.B_Cu, 0.2,
     [(98.8, 21.6), (100.2, 23.0), (100.2, 29.2), (101.11, 30.11), (101.11, 30.9)]),
    # U301's IO0 pad straight to R502, then R503's BOOT pin below it
    ("BOOT", pcbnew.F_Cu, 0.2, [(62.75, 37.75), (65.74, 37.75), (66.49, 37.0), (66.49, 38.4)]),
    # J203 pin 2 round pin 1 onto rev A's CANL run between the CAN etherCONs
    ("/dbCAN — ADM3053 isolated, 2x etherCON/CANL", pcbnew.F_Cu, 0.25,
     [(46.5, 89.04), (47.75, 87.79), (47.75, 85.5), (47.40, 84.62)]),
    # EN and the three LED nets cross under U301 on B.Cu, which rev A leaves
    # empty above PD_PG (y 32.28) except for the through-via field of the
    # module's GND pad (y 27.0-30.9). EN starts at rev A's EN via; each LED
    # net gets a via on its F.Cu trace at x 40.5, west of rev A's EN, CAN_TX
    # and CAN_RX runs on In2. Three lanes pass above the via field, CAN below
    # it; they keep their starting order, so none cross, and surface at x 69
    # beside the parts they feed.
    ("EN", pcbnew.B_Cu, 0.2, [(42.0, 23.25), (42.0, 21.9), (68.8, 21.9)]),
    ("EN", "via", 0.6, [(68.8, 21.9)]),
    ("EN", pcbnew.F_Cu, 0.2, [(68.8, 21.9), (69.3, 21.4), (71.99, 21.4)]),
    ("LED_LAN", "via", 0.6, [(40.5, 30.13), (69.6, 24.0)]),
    ("LED_LAN", pcbnew.B_Cu, 0.2, [(40.5, 30.13), (40.5, 24.0), (69.6, 24.0)]),
    ("LED_LAN", pcbnew.F_Cu, 0.2, [(69.6, 24.0), (70.0, 24.4), (71.66, 24.4)]),
    ("LED_ERR", "via", 0.6, [(40.5, 31.4), (68.6, 24.7)]),
    ("LED_ERR", pcbnew.B_Cu, 0.2, [(40.5, 31.4), (41.2, 30.7), (41.2, 24.7), (68.6, 24.7)]),
    ("LED_ERR", pcbnew.F_Cu, 0.2, [(68.6, 24.7), (68.6, 26.7), (69.5, 27.6), (71.66, 27.6)]),
    ("LED_CAN", "via", 0.6, [(40.5, 32.67), (69.4, 31.62)]),
    ("LED_CAN", pcbnew.B_Cu, 0.2, [(40.5, 32.67), (41.55, 31.62), (69.4, 31.62)]),
    ("LED_CAN", pcbnew.F_Cu, 0.2, [(69.4, 31.62), (70.22, 30.8), (71.66, 30.8)]),
    # R510 (FP_SDA) to its ESD pin along the clear strip under the antenna
    # keep-out (which ends at y 19.75): the EN stub, R501 and JP501 wall it in
    # on every other side, and Freerouting mostly never found the way out
    (EXP + "FP_SDA", pcbnew.F_Cu, 0.2, [(67.51, 21.2), (68.45, 20.15), (80.6, 20.15), (81.29, 20.84), (81.29, 21.55)]),
    # U503's GND pin: the LED_CAN stub takes the room fanout would use, and
    # without a via the pin sat in a pour island of its own (DRC calls that a
    # zone-to-zone unconnected item, so it reads like a sliver, not a floating IC)
    # (the via sits between that stub and rev A's PD_PG on B.Cu at y 32.28)
    ("GND", pcbnew.F_Cu, 0.3, [(71.66, 31.45), (70.6, 31.55)]),
    ("GND", "via", 0.6, [(70.6, 31.55)]),
    # U402's output return: one pad carrying the whole load, two vias under the body
    ("GND", pcbnew.F_Cu, 0.8, [(102.45, 73.885), (106.0, 73.885)]),
    ("GND", "via", 0.6, [(105.0, 73.885), (106.0, 73.885)]),
    # U105's GND pin, the east column's last, straight down to a via
    ("GND", pcbnew.F_Cu, 0.25, [(116.34, 41.05), (116.4, 41.95)]),
    ("GND", "via", 0.6, [(116.4, 41.95)]),
]


def preroute(b):
    """Add PREROUTES, all of a net's pieces or none of them. Each track and via
    is checked against every other net's pads, tracks and vias first."""
    pads = [(p, p.GetEffectivePolygon(pcbnew.F_Cu, pcbnew.ERROR_INSIDE)) for f in b.GetFootprints()
            for p in f.Pads()]
    tracks = list(b.GetTracks())
    nets = {}
    for net, layer, w, pts in PREROUTES:
        nets.setdefault(net, []).append((layer, w, pts))
    made, refused = [], []
    accepted = []   # (code, kind, shape, layers, half-width) of nets already passed
    for net, pieces in nets.items():
        code = b.FindNet(net).GetNetCode()
        bad, planned = [], []
        for layer, w, pts in pieces:
            r = MM(w / 2 + CLEAR)
            if layer == "via":
                shapes = [("via", pcbnew.VECTOR2I(MM(x), MM(y))) for x, y in pts]
                layers = (pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu)   # it goes through them all
            else:
                shapes = [("seg", pcbnew.SEG(pcbnew.VECTOR2I(MM(x1), MM(y1)), pcbnew.VECTOR2I(MM(x2), MM(y2))))
                          for (x1, y1), (x2, y2) in zip(pts, pts[1:])]
                layers = (layer,)
            for kind, sh in shapes:
                for p, poly in pads:
                    if p.GetNetCode() == code or not any(p.IsOnLayer(l) for l in layers):
                        continue
                    if poly.Collide(sh, r):
                        bad.append(f"pad {p.GetParentFootprint().GetReference()}.{p.GetNumber()}")
                for t in tracks:
                    if t.GetNetCode() == code or not any(t.IsOnLayer(l) for l in layers):
                        continue
                    if t.GetClass() == "PCB_VIA":
                        d = (math.hypot(sh.x - t.GetPosition().x, sh.y - t.GetPosition().y) if kind == "via"
                             else sh.Distance(t.GetPosition()))
                        if d < r + t.GetWidth(pcbnew.F_Cu) / 2:
                            bad.append(f"via {t.GetNetname().split('/')[-1]}")
                    else:
                        seg = pcbnew.SEG(t.GetStart(), t.GetEnd())
                        d = seg.Distance(sh) if kind == "via" else sh.Distance(seg)
                        if d < r + t.GetWidth() / 2:
                            bad.append(f"track {t.GetNetname().split('/')[-1]}")
                # and against the pre-routes of the nets before it, which are
                # not on the board yet
                for ocode, okind, osh, olayers, ohalf, oname in accepted:
                    if ocode == code or not set(layers) & set(olayers):
                        continue
                    if kind == "via" and okind == "via":
                        d = math.hypot(sh.x - osh.x, sh.y - osh.y)
                    elif kind == "via":
                        d = osh.Distance(sh)
                    elif okind == "via":
                        d = sh.Distance(osh)
                    else:
                        d = sh.Distance(osh)
                    if d < r + ohalf:
                        bad.append(f"pre-route {oname}")
                planned.append((kind, sh, layer, w, layers))
        if bad:
            refused.append(f"{net.split('/')[-1]} ({', '.join(sorted(set(bad)))})")
        else:
            made.append((code, planned))
            accepted += [(code, kind, sh, layers, MM(w / 2), net.split("/")[-1])
                         for kind, sh, layer, w, layers in planned]
    for code, planned in made:
        for kind, sh, layer, w, layers in planned:
            if kind == "via":
                v = pcbnew.PCB_VIA(b)
                v.SetPosition(sh)
                v.SetWidth(MM(VIA_D))
                v.SetDrill(MM(VIA_DRILL))
                v.SetNetCode(code)
                b.Add(v)
            else:
                t = pcbnew.PCB_TRACK(b)
                t.SetStart(sh.A)
                t.SetEnd(sh.B)
                t.SetWidth(MM(w))
                t.SetLayer(layer)
                t.SetNetCode(code)
                b.Add(t)
    print(f"pre-routed {len(made)} nets" + (f"; refused {'; '.join(refused)}" if refused else ""))
    if refused:
        # These are fixed geometry: a refusal means the placement around one
        # changed, and routing on would hide it (one hid a floating GND pin).
        sys.exit("a pre-route no longer fits: move it in PREROUTES")


def drc_json(name):
    out = os.path.join(WORK, name)
    subprocess.run([KICAD_CLI, "pcb", "drc", "--format", "json", "--refill-zones", "-o", out, BOARD],
                   capture_output=True)
    return json.load(open(out))


def net_of(item):
    m = re.search(r"\[([^\]]+)\]", item["description"])
    return m.group(1) if m else None


def unconnected_nets(d):
    """Nets with an open connection. A pair that is only zone pieces is an
    island, which routing cannot fix: leave it to the DRC report."""
    nets = set()
    for u in d.get("unconnected_items", []):
        if all(it["description"].startswith("Zone") for it in u["items"]):
            continue
        nets.update(n for n in map(net_of, u["items"]) if n)
    return nets


def item_key(t):
    if t.GetClass() == "PCB_VIA":
        return (t.GetNetname(), "V") + rounded(t.GetPosition().x, t.GetPosition().y)
    ends = sorted([rounded(t.GetStart().x, t.GetStart().y), rounded(t.GetEnd().x, t.GetEnd().y)])
    return (t.GetNetname(), t.GetLayer()) + ends[0] + ends[1]


def frozen_keys():
    return {tuple(k) for k in json.load(open(os.path.join(WORK, "frozen.json")))}


def freeroute(nets, n):
    """Route `nets`. Only frozen copper (rev A's, the fanout, the pre-routes) is
    locked, so from the second round on Freerouting can rip up and redo its own
    earlier work, which is what frees a connection it boxed in."""
    frozen = frozen_keys()
    b = pcbnew.LoadBoard(BOARD)   # the export copy: never saved
    for t in b.GetTracks():
        t.SetLocked(item_key(t) in frozen)
    for layer in (pcbnew.In1_Cu, pcbnew.In2_Cu):
        b.SetLayerType(layer, pcbnew.LT_POWER)
    dsn, ses = os.path.join(WORK, f"canary-{n}.dsn"), os.path.join(WORK, f"canary-{n}.ses")
    for p in (dsn, ses):
        if os.path.exists(p):
            os.remove(p)
    if not pcbnew.ExportSpecctraDSN(b, dsn):
        sys.exit("DSN export failed")
    cmd = ["java", "-jar", FREEROUTING, "-de", dsn, "-do", ses, "-mp", str(PASSES),
           "--gui.enabled=false", "--router.neck_width_um=150", "--router.automatic_neckdown=false"]
    for tries in (1, 2):   # the JVM has died once without a word in its log
        t0 = time.time()
        with open(os.path.join(WORK, f"freerouting-{n}.log"), "w") as log:
            r = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT)
        print(f"run {n}: freerouting exit {r.returncode} after {time.time() - t0:.0f} s")
        if os.path.exists(ses):
            break
    else:
        print(f"run {n}: no session file twice, see route/freerouting-{n}.log")
        return
    # The session holds only what Freerouting wrote, not rev A's locked copper:
    # importing it into the board replaces the routing wholesale. So import into
    # a scratch copy, lift the target nets' copper out, and add it to the board.
    scratch = pcbnew.LoadBoard(BOARD)
    if not pcbnew.ImportSpecctraSES(scratch, ses):
        sys.exit("SES import failed")
    items = []
    for t in scratch.GetTracks():
        if t.GetNetname() not in nets:
            continue
        if t.GetClass() == "PCB_VIA":
            items.append({"via": True, "net": t.GetNetname(), "x": t.GetPosition().x, "y": t.GetPosition().y,
                          "w": t.GetWidth(pcbnew.F_Cu), "drill": t.GetDrillValue()})
        else:
            items.append({"via": False, "net": t.GetNetname(), "layer": t.GetLayer(),
                          "x1": t.GetStart().x, "y1": t.GetStart().y, "x2": t.GetEnd().x, "y2": t.GetEnd().y,
                          "w": t.GetWidth()})
    if str(n).endswith("b"):
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "--ripup", json.dumps(sorted(nets))],
                           capture_output=True, text=True)
        print("\n".join(l for l in r.stdout.splitlines() if "ripped" in l))
    add_items(items)


def ripup(nets):
    """Take every non-frozen item off `nets`, ready for the new session's."""
    frozen = frozen_keys()
    b = pcbnew.LoadBoard(BOARD)
    gone = [t for t in b.GetTracks() if t.GetNetname() in nets and item_key(t) not in frozen]
    for t in gone:
        b.Remove(t)
    pcbnew.SaveBoard(BOARD, b)
    print(f"ripped up {len(gone)} router items on {len(nets)} nets")


# DRC findings on copper the router added that are cheaper to delete and route
# again than to patch: Freerouting knows no hole-to-hole rule.
BAD = {"hole_to_hole", "via_dangling", "track_dangling", "clearance", "shorting_items",
       "copper_edge_clearance", "hole_clearance"}


def cleanup(d):
    """Positions of router-made vias and tracks DRC objects to, for --remove."""
    added = json.load(open(os.path.join(WORK, "added.json")))
    mine = {(a["net"], a["x"], a["y"]) for a in added}
    doomed = []
    for v in d["violations"]:
        if v["type"] not in BAD:
            continue
        for it in v["items"]:
            n = net_of(it)
            x, y = round(it["pos"]["x"], 2), round(it["pos"]["y"], 2)
            if (n, x, y) in mine:
                doomed.append({"net": n, "x": x, "y": y})
    return doomed


def remove(doomed):
    b = pcbnew.LoadBoard(BOARD)
    want = {(d["net"], d["x"], d["y"]) for d in doomed}
    gone = [t for t in b.GetTracks()
            if (t.GetNetname(), round(pcbnew.ToMM(t.GetPosition().x), 2),
                round(pcbnew.ToMM(t.GetPosition().y), 2)) in want]
    for t in gone:
        b.Remove(t)
    pcbnew.SaveBoard(BOARD, b)
    print(f"removed {len(gone)} router items DRC objected to")


def route():
    os.makedirs(WORK, exist_ok=True)
    b = pcbnew.LoadBoard(BOARD)
    set_power_class(b)
    preroute(b)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(BOARD, b)
    b = pcbnew.LoadBoard(BOARD)   # fanout must see the pre-routes
    fanout(b)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(BOARD, b)
    b = pcbnew.LoadBoard(BOARD)
    json.dump([item_key(t) for t in b.GetTracks()], open(os.path.join(WORK, "frozen.json"), "w"))
    start = os.path.join(WORK, "start.kicad_pcb")
    shutil.copy(BOARD, start)
    targets = unconnected_nets(drc_json("drc-start.json"))
    print(f"{len(targets)} nets to route: {' '.join(sorted(t.split('/')[-1] for t in targets))}")

    # Freerouting is not deterministic (it routes on 15 threads), and on this
    # board a run typically leaves zero to two connections open. So: fresh
    # attempts from the same start, each followed by one rip-up round on what
    # it left, keeping the best board and stopping at the first complete one.
    best = None
    for n in range(1, ATTEMPTS + 1):
        shutil.copy(start, BOARD)
        json.dump([], open(os.path.join(WORK, "added.json"), "w"))
        freeroute(targets, f"{n}a")
        left = settle(f"{n}a")
        if left:
            freeroute(targets, f"{n}b")
            left = settle(f"{n}b")
        print(f"attempt {n}: {len(left)} nets open" + (f" ({' '.join(sorted(t.split('/')[-1] for t in left))})" if left else ""))
        if best is None or len(left) < best[0]:
            keep = os.path.join(WORK, "best.kicad_pcb")
            shutil.copy(BOARD, keep)
            best = (len(left), keep)
        if not left:
            break
    shutil.copy(best[1], BOARD)


def restitch():
    """GND vias back into any GND pour piece that has none. Placement strips
    rev A's stitching from under the new parts, and new tracks can then cut a
    piece of F.Cu or B.Cu pour off from everything: DRC reports that as a
    zone-to-zone unconnected pair. Two vias per orphaned piece, each clear of
    every other net on every layer and inside the In1 GND plane's fill."""
    b = pcbnew.LoadBoard(BOARD)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    gnd = b.FindNet("GND").GetNetCode()
    tracks = list(b.GetTracks())
    pads = [p for f in b.GetFootprints() for p in f.Pads()]
    keepouts = [z for z in b.Zones() if z.GetIsRuleArea() and z.GetDoNotAllowVias()]
    for f in b.GetFootprints():
        keepouts += [z for z in f.Zones() if z.GetDoNotAllowVias()]
    plane = [z for z in b.Zones() if z.GetZoneName() == "GND_PLANE_In1"][0].GetFilledPolysList(pcbnew.In1_Cu)
    gvias = [t.GetPosition() for t in tracks if t.GetClass() == "PCB_VIA" and t.GetNetCode() == gnd]
    gtht = [p.GetPosition() for p in pads if p.GetNetCode() == gnd and p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH]
    r = MM(VIA_D / 2)

    def fits(pt):
        if not plane.Contains(pt):   # the via has to land in the GND plane
            return False
        for z in keepouts:
            if z.Outline().Contains(pt) or z.Outline().Outline(0).Collide(pt, r):
                return False
        for t in tracks:
            if t.GetNetCode() == gnd:
                continue
            if t.GetClass() == "PCB_VIA":
                if math.hypot(pt.x - t.GetPosition().x, pt.y - t.GetPosition().y) < r + MM(CLEAR) + t.GetWidth(pcbnew.F_Cu) / 2:
                    return False
            elif pcbnew.SEG(t.GetStart(), t.GetEnd()).Distance(pt) < r + MM(CLEAR) + t.GetWidth() / 2:
                return False
        for p in pads:
            if p.GetNetCode() == gnd:
                continue
            layer = pcbnew.F_Cu if p.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu
            if p.GetEffectivePolygon(layer, pcbnew.ERROR_INSIDE).Collide(pt, r + MM(CLEAR)):
                return False
        return True

    planned = []
    for z in b.Zones():
        if z.GetIsRuleArea() or z.GetNetCode() != gnd or z.GetLayer() not in (pcbnew.F_Cu, pcbnew.B_Cu):
            continue
        fill = z.GetFilledPolysList(z.GetLayer())
        for i in range(fill.OutlineCount()):
            piece = pcbnew.SHAPE_POLY_SET()
            piece.AddOutline(fill.Outline(i))
            if any(piece.Contains(q) for q in gvias + gtht + [p for p in planned]):
                continue
            bb = fill.Outline(i).BBox()
            found = 0
            for y in range(bb.GetTop(), bb.GetBottom(), MM(0.5)):
                for x in range(bb.GetLeft(), bb.GetRight(), MM(0.5)):
                    pt = pcbnew.VECTOR2I(x, y)
                    if not piece.Contains(pt):
                        continue
                    if any(math.hypot(pt.x - q.x, pt.y - q.y) < MM(3) for q in planned):
                        continue
                    if fits(pt):
                        planned.append(pt)
                        found += 1
                        if found == 2:
                            break
                if found == 2:
                    break
    for pt in planned:
        v = pcbnew.PCB_VIA(b)
        v.SetPosition(pt)
        v.SetWidth(MM(VIA_D))
        v.SetDrill(MM(VIA_DRILL))
        v.SetNetCode(gnd)
        b.Add(v)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(BOARD, b)
    print(f"restitch: {len(planned)} GND vias into orphaned pour pieces")


def settle(tag):
    """Delete the router items DRC objects to; return the nets still open."""
    d = drc_json(f"drc-{tag}.json")
    doomed = cleanup(d)
    if doomed:
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "--remove", json.dumps(doomed)],
                           capture_output=True, text=True)
        print("\n".join(l for l in r.stdout.splitlines() if "removed" in l))
        d = drc_json(f"drc-{tag}-clean.json")
    return unconnected_nets(d)


def rounded(*v):
    return tuple(round(pcbnew.ToMM(x), 2) for x in v)


def add_items(items):
    b = pcbnew.LoadBoard(BOARD)
    have = set()
    for t in b.GetTracks():
        if t.GetClass() == "PCB_VIA":
            have.add((t.GetNetname(), "V") + rounded(t.GetPosition().x, t.GetPosition().y))
        else:
            ends = sorted([rounded(t.GetStart().x, t.GetStart().y), rounded(t.GetEnd().x, t.GetEnd().y)])
            have.add((t.GetNetname(), t.GetLayer()) + ends[0] + ends[1])
    codes = {n: b.FindNet(n).GetNetCode() for n in {it["net"] for it in items}}
    added = skipped = 0
    for it in items:
        if it["via"]:
            k = (it["net"], "V") + rounded(it["x"], it["y"])
            if k in have:
                skipped += 1
                continue
            v = pcbnew.PCB_VIA(b)
            v.SetPosition(pcbnew.VECTOR2I(it["x"], it["y"]))
            v.SetWidth(it["w"])
            v.SetDrill(it["drill"])
            v.SetNetCode(codes[it["net"]])   # net before Add(), never touch after
            b.Add(v)
        else:
            ends = sorted([rounded(it["x1"], it["y1"]), rounded(it["x2"], it["y2"])])
            k = (it["net"], it["layer"]) + ends[0] + ends[1]
            if k in have:
                skipped += 1
                continue
            t = pcbnew.PCB_TRACK(b)
            t.SetStart(pcbnew.VECTOR2I(it["x1"], it["y1"]))
            t.SetEnd(pcbnew.VECTOR2I(it["x2"], it["y2"]))
            t.SetWidth(it["w"])
            t.SetLayer(it["layer"])
            t.SetNetCode(codes[it["net"]])
            b.Add(t)
        have.add(k)
        added += 1
    # Fill before saving: Save() re-nets a via that sits in a stale fill.
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(BOARD, b)
    log = os.path.join(WORK, "added.json")
    prev = json.load(open(log)) if os.path.exists(log) else []
    for it in items:
        x, y = (it["x"], it["y"]) if it["via"] else ((it["x1"] + it["x2"]) / 2, (it["y1"] + it["y2"]) / 2)
        prev.append({"net": it["net"], "x": round(pcbnew.ToMM(x), 2), "y": round(pcbnew.ToMM(y), 2)})
    json.dump(prev, open(log, "w"))
    print(f"added {added} routed items from the session, {skipped} already on the board")


if __name__ == "__main__":
    if "--remove" in sys.argv:
        remove(json.loads(sys.argv[sys.argv.index("--remove") + 1]))
    elif "--restitch" in sys.argv:
        restitch()
    elif "--ripup" in sys.argv:
        ripup(set(json.loads(sys.argv[sys.argv.index("--ripup") + 1])))
    else:
        route()
    done()
