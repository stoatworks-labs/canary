#!/usr/bin/env python3
"""
Refill every zone, save, and run DRC: the last stage of build.sh route.

    <kicad python> hardware/rev-b/scripts/finish.py

Scripted boards keep stale fills (kicad-cli render and the saved file both
show them), so the fill happens here rather than only inside DRC. Prints the
DRC counts by type next to rev A's, from the same kicad-cli.
"""
import collections
import json
import os
import subprocess
import sys

import pcbnew

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plan  # noqa: E402
from layout import DELETE, POUR_NETS, VBUS_FUSED  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REVB = os.path.normpath(os.path.join(HERE, ".."))
BOARD = os.path.join(REVB, "canary.kicad_pcb")
REVA = os.path.normpath(os.path.join(REVB, "..", "canary.kicad_pcb"))
WORK = os.path.join(REVB, "route")
KICAD_CLI = os.environ.get("KICAD_CLI", "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli")


def drc(board, out):
    subprocess.run([KICAD_CLI, "pcb", "drc", "--format", "json", "--severity-all", "-o", out, board],
                   capture_output=True)
    d = json.load(open(out))
    c = collections.Counter((v["severity"], v["type"]) for v in d["violations"])
    c[("error", "unconnected_items")] = len(d.get("unconnected_items", []))
    return c, d


def geometry(b):
    out = {}
    for t in b.GetTracks():
        if t.GetClass() == "PCB_VIA":
            k = ("V", round(pcbnew.ToMM(t.GetPosition().x), 3), round(pcbnew.ToMM(t.GetPosition().y), 3))
        else:
            ends = sorted([(round(pcbnew.ToMM(t.GetStart().x), 3), round(pcbnew.ToMM(t.GetStart().y), 3)),
                           (round(pcbnew.ToMM(t.GetEnd().x), 3), round(pcbnew.ToMM(t.GetEnd().y), 3))])
            k = (t.GetLayer(),) + ends[0] + ends[1]
        out.setdefault(k, []).append(t.GetNetname())
    return out


def frozen():
    """Every rev A track and via is still there on its expected net, unless
    layout.py deliberately removed it. Catches a re-netted via, the failure
    pcbnew's bindings produce without complaint."""
    a, b = geometry(pcbnew.LoadBoard(REVA)), geometry(pcbnew.LoadBoard(BOARD))
    moved = {(pcbnew.F_Cu,) + tuple(sorted([p, q])[0]) + tuple(sorted([p, q])[1]) for p, q in VBUS_FUSED}
    gone = {(pcbnew.F_Cu,) + tuple(sorted([p, q])[0]) + tuple(sorted([p, q])[1]) for p, q in DELETE}
    vbus = "/Power — PoE + USB-C PD, 5V and 3V3/VBUS_FUSED"
    problems = []
    for k, nets in a.items():
        want = vbus if k in moved else plan.RENAMED.get(nets[0], nets[0])
        if k not in b:
            if k in gone or (k[0] == "V" and nets[0].split("/")[-1] in POUR_NETS):
                continue
            problems.append(f"missing {k} ({nets[0]})")
        elif want not in b[k]:
            problems.append(f"re-netted {k}: {nets[0]} -> {b[k]}")
    for p in problems:
        print("FAIL", p)
    print(f"{'FAIL' if problems else 'OK'}: rev A copper, {len(a)} items, {len(problems)} changed unexpectedly")
    return len(problems)


def main():
    os.makedirs(WORK, exist_ok=True)
    b = pcbnew.LoadBoard(BOARD)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(BOARD, b)
    a, _ = drc(REVA, os.path.join(WORK, "drc-reva.json"))
    r, d = drc(BOARD, os.path.join(WORK, "drc.json"))
    print(f"{'severity':8} {'type':32} {'rev A':>6} {'rev B':>6}")
    for k in sorted(set(a) | set(r)):
        if a[k] or r[k]:
            print(f"{k[0]:8} {k[1]:32} {a[k]:6} {r[k]:6}")
    errors = sum(n for (s, _), n in r.items() if s == "error")
    print(f"rev B: {errors} errors")
    errors += frozen()
    sys.stdout.flush()
    os._exit(1 if errors else 0)


if __name__ == "__main__":
    main()
