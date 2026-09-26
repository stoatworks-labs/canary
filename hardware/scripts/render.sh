#!/usr/bin/env bash
# Regenerate the board renders in docs/renders/.
# High quality raytracing; each view takes a few seconds.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
BOARD="$HERE/dbcanary.kicad_pcb"
OUT="$HERE/../docs/renders"
mkdir -p "$OUT"

common=(--quality high --width 1600 --height 1300 --background opaque)

kicad-cli pcb render -o "$OUT/top.png"    --side top    "${common[@]}" "$BOARD"
kicad-cli pcb render -o "$OUT/bottom.png" --side bottom "${common[@]}" "$BOARD"
kicad-cli pcb render -o "$OUT/iso.png"    --side top --rotate "-30,0,25" \
    --perspective --floor --quality high --width 1600 --height 1200 \
    --background opaque "$BOARD"

echo "renders written to $OUT"
ls -la "$OUT"/*.png
