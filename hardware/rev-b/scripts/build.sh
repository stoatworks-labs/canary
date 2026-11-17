#!/bin/sh
# Rebuild the rev B board from rev A's routed board and the rev B schematic.
# The board is generated: edits made in the GUI are overwritten by the next run.
#
#   hardware/rev-b/scripts/build.sh            # through placement
#   hardware/rev-b/scripts/build.sh route      # and route, finish, DRC
set -e
set -o pipefail   # a stage that fails stops the build, through the quiet() filter
HERE=$(cd "$(dirname "$0")" && pwd)
REVB=$(dirname "$HERE")
KP=${KICAD_PYTHON:-/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3}
quiet() { grep -v "wxApp\|traits\|Debug:" || true; }

python3 -I "$HERE/check_schematic.py" | tail -1
cp "$REVB/../canary.kicad_pcb" "$REVB/canary.kicad_pcb"
"$KP" "$HERE/sync.py" 2>&1 | quiet
for stage in place strip check; do
    "$KP" "$HERE/layout.py" $stage 2>&1 | quiet
done
if [ "$1" = route ]; then
    "$KP" "$HERE/route.py" 2>&1 | quiet
    "$KP" "$HERE/finish.py" 2>&1 | quiet
fi
