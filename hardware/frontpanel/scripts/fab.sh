#!/bin/sh
# Fab outputs for the front-panel board, from the routed board build.py left.
#
#   hardware/frontpanel/scripts/fab.sh
#
# fab/gerbers/      Gerbers + Excellon drill, zipped as canary-fp-gerbers.zip
# fab/bom.csv       one line per value+footprint; holes and Fit=DNP parts left out
# fab/cpl.csv       placement for the SMD parts (all on the front)
# fab/panel.dxf     the panel drilling drawing (Dwgs.User + outline), and panel.pdf
#
# Refuses to run unless DRC is clean, schematic parity included.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
FP=$(dirname "$HERE")
OUT="$FP/fab"
KC=${KICAD_CLI:-/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli}
BOARD="$FP/canary-fp.kicad_pcb"
quiet() { grep -v "Fontconfig" || true; }

mkdir -p "$OUT/gerbers" "$FP/route"
"$KC" pcb drc --format json --severity-error --schematic-parity --refill-zones \
    --exit-code-violations -o "$FP/route/drc-fab.json" "$BOARD" 2>&1 | quiet >/dev/null \
    || { echo "DRC not clean: see route/drc-fab.json"; exit 1; }

rm -f "$OUT"/gerbers/*
"$KC" pcb export gerbers --layers F.Cu,B.Cu,F.Mask,B.Mask,F.SilkS,B.SilkS,F.Paste,Edge.Cuts \
    --subtract-soldermask --no-x2 -o "$OUT/gerbers/" "$BOARD" 2>&1 | quiet >/dev/null
"$KC" pcb export drill --format excellon --excellon-separate-th -o "$OUT/gerbers/" "$BOARD" 2>&1 | quiet >/dev/null
(cd "$OUT/gerbers" && rm -f ../canary-fp-gerbers.zip && zip -q ../canary-fp-gerbers.zip ./*)

"$KC" pcb export pos --format csv --units mm --side front --smd-only --exclude-dnp \
    -o "$OUT/cpl-raw.csv" "$BOARD" 2>&1 | quiet >/dev/null
"$KC" sch export bom --fields 'Reference,Value,Footprint,Fit,${QUANTITY}' \
    --group-by 'Value,Footprint,Fit' -o "$OUT/bom-raw.csv" "$FP/canary-fp.kicad_sch" 2>&1 | quiet >/dev/null
python3 -I - "$OUT" <<'EOF'
import csv, sys, os
out = sys.argv[1]
rows = list(csv.DictReader(open(os.path.join(out, "bom-raw.csv"))))
keep = [r for r in rows if r["Fit"] != "DNP" and not r["Reference"].startswith("H")]
with open(os.path.join(out, "bom.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Designators", "Qty", "Value", "Footprint"])
    for r in keep:
        w.writerow([r["Reference"], r["${QUANTITY}"] if "${QUANTITY}" in r else r.get("QUANTITY", ""),
                    r["Value"], r["Footprint"]])
os.remove(os.path.join(out, "bom-raw.csv"))
cpl = list(csv.reader(open(os.path.join(out, "cpl-raw.csv"))))
with open(os.path.join(out, "cpl.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Designator", "Value", "Footprint", "Mid X", "Mid Y", "Rotation", "Layer"])
    for r in cpl[1:]:
        w.writerow(r)
os.remove(os.path.join(out, "cpl-raw.csv"))
print(f"bom: {len(keep)} lines; cpl: {len(cpl) - 1} parts")
EOF

"$KC" pcb export dxf --mode-single --layers Dwgs.User,Edge.Cuts --output-units mm -o "$OUT/panel.dxf" "$BOARD" 2>&1 | quiet >/dev/null
"$KC" pcb export pdf --layers Dwgs.User,Edge.Cuts --include-border-title -o "$OUT/panel.pdf" "$BOARD" 2>&1 | quiet >/dev/null
echo "fab outputs in $OUT"
