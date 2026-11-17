#!/usr/bin/env python3
"""
Prove the rev B schematic is rev A's netlist plus exactly plan.py's changes.

    python3 -I hardware/rev-b/scripts/check_schematic.py

Exports both netlists with kicad-cli, takes every pin's net in rev A, applies
plan.RENAMED, plan.MOVED and plan.U301, adds plan.PARTS, and requires the rev B
netlist to match pin for pin: same net names, and pins that share a net in one
share it in the other. Also checks each new part's value, footprint and Fit
field, and plan.CHANGED's new values for rev A parts. Exit 0 only if all of it
holds. ERC is a separate check.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import plan  # noqa: E402

REVB = os.path.normpath(os.path.join(HERE, ".."))
REVA = os.path.normpath(os.path.join(REVB, ".."))
KICAD_CLI = os.environ.get("KICAD_CLI", "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli")


def parse(text):
    stack, cur = [], []
    for t in re.findall(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()]+', text):
        if t == "(":
            stack.append(cur)
            cur = []
        elif t == ")":
            done, cur = cur, stack.pop()
            cur.append(done)
        else:
            cur.append(t[1:-1].replace('\\"', '"') if t.startswith('"') else t)
    return cur[0]


def find(node, key):
    return [c for c in node if isinstance(c, list) and c and c[0] == key]


def first(node, key):
    f = find(node, key)
    return f[0] if f else None


def netlist(root):
    out = tempfile.NamedTemporaryFile(suffix=".net", delete=False).name
    subprocess.run([KICAD_CLI, "sch", "export", "netlist", "--format", "kicadsexpr",
                    "-o", out, root], check=True, capture_output=True)
    tree = parse(open(out, encoding="utf-8").read())
    pins, comps = {}, {}
    for n in find(first(tree, "nets"), "net"):
        name = first(n, "name")[1]
        for node in find(n, "node"):
            key = (first(node, "ref")[1], first(node, "pin")[1])
            pins[key] = None if name.startswith("unconnected-") else name
    for c in find(first(tree, "components"), "comp"):
        ref = first(c, "ref")[1]
        fields = {f[1][1]: (f[2] if len(f) > 2 else "") for f in find(first(c, "fields") or [], "field")}
        comps[ref] = {"value": first(c, "value")[1],
                      "footprint": (first(c, "footprint") or [None, ""])[1],
                      "fields": fields}
    return pins, comps


def groups(pins):
    g = {}
    for k, n in pins.items():
        if n is not None:
            g.setdefault(n, set()).add(k)
    return g


def main():
    a_pins, _ = netlist(os.path.join(REVA, "canary.kicad_sch"))
    b_pins, b_comps = netlist(os.path.join(REVB, "canary.kicad_sch"))
    errors = []

    expect = {}
    for k, n in a_pins.items():
        expect[k] = plan.RENAMED.get(n, n) if n else None
    for k, n in plan.MOVED.items():
        expect[k] = n
    for pin, n in plan.U301.items():
        expect[("U301", pin)] = n
    for ref, (sheet, lib, value, fp, pins, fields) in plan.PARTS.items():
        for p, n in pins.items():
            expect[(ref, p)] = n
        for k in plan.NC:
            if k[0] == ref:
                expect[k] = None
        c = b_comps.get(ref)
        if not c:
            errors.append(f"{ref}: not in the rev B schematic")
            continue
        if c["value"] != value:
            errors.append(f"{ref}: value {c['value']!r}, plan {value!r}")
        if c["footprint"] != fp:
            errors.append(f"{ref}: footprint {c['footprint']!r}, plan {fp!r}")
        for f, v in fields.items():
            if c["fields"].get(f) != v:
                errors.append(f"{ref}: field {f}={c['fields'].get(f)!r}, plan {v!r}")

    for ref, want in plan.CHANGED.items():
        c = b_comps.get(ref, {})
        for key, v in want.items():
            have = c.get(key) if key in ("value", "footprint") else c.get("fields", {}).get(key)
            if have != v:
                errors.append(f"{ref}: {key} {have!r}, plan {v!r}")

    for k in sorted(set(expect) | set(b_pins)):
        if k not in b_pins:
            if expect.get(k) is not None:
                errors.append(f"{k[0]}.{k[1]}: missing from rev B (plan {expect[k]})")
            continue
        if k not in expect:
            errors.append(f"{k[0]}.{k[1]}: on {b_pins[k]} in rev B, not in the plan")
        elif b_pins[k] != expect[k]:
            errors.append(f"{k[0]}.{k[1]}: rev B {b_pins[k]}, plan {expect[k]}")

    # Same names can still hide a merge or split: compare the groupings too.
    eg, bg = groups(expect), groups(b_pins)
    for n in sorted(set(eg) | set(bg)):
        if eg.get(n, set()) != bg.get(n, set()):
            extra = sorted(bg.get(n, set()) - eg.get(n, set()))
            lost = sorted(eg.get(n, set()) - bg.get(n, set()))
            if extra or lost:
                errors.append(f"net {n}: extra {extra} missing {lost}")

    for e in errors:
        print("FAIL", e)
    nets = len(bg)
    print(f"{'FAIL' if errors else 'OK'}: {len(b_pins)} pins on {nets} nets, "
          f"{len(plan.PARTS)} new parts, {len(errors)} problems")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
