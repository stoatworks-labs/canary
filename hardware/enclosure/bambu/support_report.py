#!/usr/bin/env python3
"""What did the support actually cost?

`slice_info.config` reports one weight per FILAMENT, which answers the question only when
the support is on a filament of its own. For a single-material plate it reports one number
covering model and support together, and the only way to separate them is to integrate the
G-code: every extruding move is tagged with a `; FEATURE:` comment, and three of those
features are support.

    support_report.py work/all-absgf-0.4-dualsupport/gcode/*.gcode

Written because 3dp/README.md carried support figures that nothing had measured -- they
were out by 13 points. Run this instead of estimating.
"""
import re
import sys
from collections import defaultdict

SUPPORT_FEATURES = {'Support', 'Support interface', 'Support transition'}

RE_FEATURE = re.compile(r'^; FEATURE:\s*(.+?)\s*$')
RE_MOVE = re.compile(r'^G[01]\b')
RE_E = re.compile(r'\bE(-?\d*\.?\d+)')
RE_TOOL = re.compile(r'^T(\d+)\b')
RE_DENSITY = re.compile(r'^; filament_density:?\s*=?\s*(.+?)\s*$')
RE_DIAM = re.compile(r'^; filament_diameter:?\s*=?\s*(.+?)\s*$')


def parse(path):
    feature, tool, relative, last_e = 'None', 0, None, 0.0
    used = defaultdict(float)          # (tool, feature) -> mm of filament
    density, diameter = [1.24], [1.75]
    with open(path, errors='ignore') as fh:
        for line in fh:
            if line.startswith('; FEATURE:'):
                m = RE_FEATURE.match(line)
                if m:
                    feature = m.group(1)
                continue
            if line.startswith('; filament_density'):
                m = RE_DENSITY.match(line)
                if m:
                    density = [float(x) for x in m.group(1).replace(',', ';').split(';') if x]
                continue
            if line.startswith('; filament_diameter'):
                m = RE_DIAM.match(line)
                if m:
                    diameter = [float(x) for x in m.group(1).replace(',', ';').split(';') if x]
                continue
            s = line.strip()
            if not s or s.startswith(';'):
                continue
            if s.startswith('M83'):
                relative = True
                continue
            if s.startswith('M82'):
                relative = False
                continue
            m = RE_TOOL.match(s)
            if m:
                # Bambu emits large synthetic tool numbers for its own bookkeeping;
                # anything past the filament list is not a real change.
                t = int(m.group(1))
                if t < 16:
                    tool = t
                continue
            if s.startswith('G92'):
                m = RE_E.search(s)
                if m:
                    last_e = float(m.group(1))
                continue
            if RE_MOVE.match(s):
                m = RE_E.search(s)
                if not m:
                    continue
                v = float(m.group(1))
                if relative:
                    if v > 0:
                        used[(tool, feature)] += v
                else:
                    if v - last_e > 0:
                        used[(tool, feature)] += v - last_e
                    last_e = v
    return used, density, diameter


def grams(mm, tool, density, diameter):
    d = diameter[tool] if tool < len(diameter) else diameter[0]
    rho = density[tool] if tool < len(density) else density[0]
    return mm * 3.141592653589793 * (d / 2) ** 2 * rho / 1000.0


def main(paths):
    for path in paths:
        used, density, diameter = parse(path)
        print(f"\n=== {path} ===")
        tools = sorted({t for t, _ in used})
        grand = 0.0
        per_tool = defaultdict(float)
        per_tool_support = defaultdict(float)
        print(f"{'tool':>4}  {'feature':30} {'mm':>11} {'g':>9}")
        for t in tools:
            for (tt, f), mm in sorted(used.items(), key=lambda kv: -kv[1]):
                if tt != t:
                    continue
                g = grams(mm, t, density, diameter)
                grand += g
                per_tool[t] += g
                if f in SUPPORT_FEATURES:
                    per_tool_support[t] += g
                print(f"{t:>4}  {f:30} {mm:11.1f} {g:9.2f}")
        print("-" * 58)
        support = sum(per_tool_support.values())
        for t in tools:
            print(f"  filament {t + 1}: {per_tool[t]:7.2f} g "
                  f"({per_tool_support[t]:.2f} g of it support)")
        print(f"  TOTAL      {grand:7.2f} g   support {support:6.2f} g "
              f"({100 * support / grand:.1f}%)   model {grand - support:6.2f} g")
        if grand - support > 0:
            print(f"  model : support = {(grand - support) / support:.2f} : 1"
                  if support else "  no support in this plate")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    main(sys.argv[1:])
