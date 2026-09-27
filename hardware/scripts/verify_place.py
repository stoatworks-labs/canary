#!/usr/bin/env python3
"""Verify placement from a FRESH load: outline fit, courtyard overlaps, jack spacing."""
import os as _os
_REPO = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import pcbnew

BOARD = _REPO + "/hardware/canary.kicad_pcb"
X0, Y0, X1, Y1 = 20.0, 19.0, 120.0, 100.0
tomm = pcbnew.ToMM

b = pcbnew.LoadBoard(BOARD)
fps = list(b.GetFootprints())

outside = []
for f in fps:
    for p in f.Pads():
        x, y = tomm(p.GetPosition().x), tomm(p.GetPosition().y)
        if not (X0 + 0.3 <= x <= X1 - 0.3 and Y0 + 0.3 <= y <= Y1 - 0.3):
            outside.append((f.GetReference(), p.GetPadName(), round(x, 2), round(y, 2)))

boxes = []
for f in fps:
    bb = f.GetCourtyard(pcbnew.F_CrtYd).BBox()
    if bb.GetWidth():
        boxes.append((f.GetReference(), bb))
overlaps = []
for i in range(len(boxes)):
    for j in range(i + 1, len(boxes)):
        if boxes[i][1].Intersects(boxes[j][1]):
            overlaps.append(f"{boxes[i][0]}<->{boxes[j][0]}")

jm = {f.GetReference(): f for f in fps if f.GetReference() in ("J201", "J202", "J401")}
print(f"pads outside outline : {len(outside)}")
for o in outside[:12]:
    print("   ", o)
print(f"courtyard overlaps   : {len(overlaps)}")
for o in overlaps[:20]:
    print("   ", o)
print("etherCON spacing (courtyard is 14.4mm but the real front plate is 25mm):")
ks = sorted(jm, key=lambda r: tomm(jm[r].GetPosition().x))
for i in range(len(ks) - 1):
    d = tomm(jm[ks[i + 1]].GetPosition().x) - tomm(jm[ks[i]].GetPosition().x)
    print(f"    {ks[i]} -> {ks[i+1]}: {d:.1f} mm  {'OK' if d >= 26 else 'TOO CLOSE'}")

# --- isolation-domain check ------------------------------------------------
# Every part carrying an isolated net (CAN_GND / VISO) must sit BELOW the
# ADM3053 barrier; every part carrying GND must sit above it, in the CAN region.
ISO_NETS = {"CAN_GND", "VISO", "VISO_RAW", "CANH", "CANL", "CAN_RS",
            "TERM_A", "TERM_B", "TERM_MID"}
u201 = {f.GetReference(): f for f in fps}["U201"]
barrier = (tomm(u201.FindPadByNumber("1").GetPosition().y)
           + tomm(u201.FindPadByNumber("11").GetPosition().y)) / 2
bad = []
for f in fps:
    r = f.GetReference()
    if r in ("U201",):
        continue
    nets = {p.GetNetname().split("/")[-1] for p in f.Pads()}
    y = tomm(f.GetPosition().y)
    if nets & ISO_NETS and y < barrier:
        bad.append((r, "isolated net ABOVE barrier", round(y, 1)))
    if "GND" in nets and y > barrier and tomm(f.GetPosition().x) < 80:
        bad.append((r, "GND net BELOW barrier in CAN region", round(y, 1)))
print(f"\nisolation barrier at y={barrier:.2f}; domain violations: {len(bad)}")
for b_ in bad:
    print("   ", b_)
