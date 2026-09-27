#!/bin/sh
# Build a CANary case plate for the Bambu Lab H2C and slice it to prove it.
#
#   ./build.sh                      # default variant, all four parts
#   ./build.sh absgf-0.4            # named variant (see variants.py)
#   ./build.sh pla-0.4 frontplate   # just the front end piece -- the fit-check article
#   ./build.sh absgf-0.4-flat rearplate   # just the rear end piece (the USB-C step)
#   ./build.sh pla-0.4-flat ledinsert     # the LED window insert, in PLA
#   ./build.sh pla-0.4-flat switchcover   # the cap over the pinholes and SW201 slot
#   ./build.sh pla-0.4-tube white-x4      # four LED inserts + four switch covers, one set
#                                         # per body of the 4-up bed
#   ./build.sh absgf-0.4-tube-x4 tube-x4  # four bodies + eight end plates, one bed
#   ./build.sh pla-0.4-jig jig            # the heat-set insert jig for the press
#   ./build.sh absgf-0.4-flat       # the flat-section case, from print-flat/
#   ./build.sh absgf-0.4-tube       # the one-piece body + end plates, from print-tube/
#
# Must run under $HOME: the Mac BambuStudio is sandboxed away from /tmp.
#
# Needs CANARY_H2C_REF_3MF set to a Bambu Studio-made H2C project (.3mf) -- see
# make_project_config.py for why.
set -e
cd "$(dirname "$0")"
BS=/Applications/BambuStudio.app/Contents/MacOS/BambuStudio
test -x "$BS" || { echo "BambuStudio not found at $BS"; exit 1; }

VARIANT="${1:-}"
PARTSET="${2:-all}"
ARRANGE=1

WORK="work/$PARTSET-${VARIANT:-default}"
rm -rf "$WORK" && mkdir -p "$WORK"
python3 flatten_preset.py $VARIANT

V=$(python3 -c "import json;print(json.load(open('presets/paths.json'))['variant'])")
# Which CASE the variant is for. The flat-section geometry (gen_case_3dp.py --flat) has
# its own oriented STLs in print-flat/; the variant name carries the -flat suffix.
G=$(python3 -c "import json;print(json.load(open('presets/paths.json')).get('geometry','lozenge'))")
PRINT=print
[ "$G" = flat ] && PRINT=print-flat
[ "$G" = tube ] && PRINT=print-tube
# The insert jig is not the case: gen_insert_jig.py writes its parts print-ready to ../jig.
[ "$G" = jig ] && PRINT=../jig
test -d "$PRINT" || { echo "run orient_for_print.py first (no $PRINT/ dir)"; exit 1; }

# The one-piece body is three parts, not four.
BODY="$PRINT/canary_shell_bottom.stl $PRINT/canary_shell_top.stl"
[ "$G" = tube ] && BODY="$PRINT/canary_tube.stl"

case "$PARTSET" in
  all)        STLS="$BODY $PRINT/canary_end_front.stl $PRINT/canary_end_rear.stl"
              STEM="canary-case" ;;
  frontplate) STLS="$PRINT/canary_end_front.stl"
              STEM="canary-frontplate" ;;
  rearplate)  STLS="$PRINT/canary_end_rear.stl"
              STEM="canary-rearplate" ;;
  ledinsert)  STLS="$PRINT/canary_led_insert.stl"
              STEM="canary-ledinsert" ;;
  switchcover) STLS="$PRINT/canary_switch_cover.stl"
              STEM="canary-switchcover" ;;
  white-x4)   # everything that prints in the white PLA, four units' worth
              STLS=""
              for i in 1 2 3 4; do
                  STLS="$STLS $PRINT/canary_led_insert.stl $PRINT/canary_switch_cover.stl"
              done
              STEM="canary-white-x4" ;;
  tube-x4)    # four one-piece bodies and their ends on one bed (tube geometry only),
              # laid out by place_x4.py and exported without arranging -- see that file
              # needs trimesh, so the CAD venv (the one gen_case_3dp.py runs under)
              CADPY="${CADPY:-$(cd ../../.. && pwd)/.venv-cad/bin/python}"
              test -x "$CADPY" || { echo "no CAD venv at $CADPY (set CADPY)"; exit 1; }
              "$CADPY" place_x4.py "$PRINT" || exit 1
              STLS="$(ls work/x4-stls/*/*.stl | tr '\n' ' ')"
              ARRANGE=0
              STEM="canary-4up" ;;
  jig)        # the heat-set insert jig (gen_insert_jig.py): plate, nest, peg
              STLS="$PRINT/canary_jig_plate.stl $PRINT/canary_jig_nest.stl $PRINT/canary_jig_peg.stl"
              STEM="canary-insert-jig" ;;
  ends)       STLS="$PRINT/canary_end_front.stl $PRINT/canary_end_rear.stl"
              STEM="canary-ends" ;;
  *) echo "unknown part set '$PARTSET' (all | ends | frontplate | rearplate | ledinsert | switchcover | white-x4 | tube-x4 | jig)"; exit 1 ;;
esac

M=$(python3 -c "import json;print(json.load(open('presets/paths.json'))['machine'])")
P=$(python3 -c "import json;print(json.load(open('presets/paths.json'))['process'])")
F=$(python3 -c "import json;print(json.load(open('presets/paths.json'))['filament'])")
# Empty unless the variant is dual-material. Semicolon-joined, so filament 2 is the
# support spool -- which is what `support_filament: "2"` in variants.py indexes.
S=$(python3 -c "import json;print(json.load(open('presets/paths.json')).get('support_filament',''))")
[ -n "$S" ] && F="$F;$S"
# Arrange against the bed BOTH nozzles can reach, not the union of the two. Only the
# placement pass uses this; the project that ships carries the real machine. See
# write_arrange_machine() in flatten_preset.py.
A=$(python3 -c "import json;print(json.load(open('presets/paths.json')).get('arrange_machine',''))")
MARRANGE="$M"
[ -n "$A" ] && MARRANGE="$A"
OUT="../$STEM-$V.3mf"

"$BS" --load-settings "$MARRANGE;$P" --load-filaments "$F" --arrange $ARRANGE \
      --export-3mf "$PWD/$WORK/raw.3mf" $STLS > "$WORK/export.log" 2>&1 || true
test -f "$WORK/raw.3mf" || { echo "export failed:"; tail -20 "$WORK/export.log"; exit 1; }

python3 make_project_config.py "$WORK/raw.3mf"
python3 inject_config.py "$WORK/raw.3mf" "$WORK/injected.3mf" project_settings.json

# Slice to verify. Separate invocation: --outputdir conflicts with --export-3mf.
"$BS" --slice 0 --outputdir "$PWD/$WORK/gcode" "$WORK/injected.3mf" \
      > "$WORK/slice.log" 2>&1 || true
ls "$WORK"/gcode/*.gcode >/dev/null 2>&1 || {
    echo "slice produced no gcode:"
    grep -iE "error|fail|nozzle|invalid" "$WORK/slice.log" | head -20; exit 1; }

# The DELIVERABLE is Studio's own re-export, not our hand-built project.
#
# A config assembled by hand carries preset-system leftovers that the CLI tolerates and
# the GUI does not -- `include` was the one that bit. Round-tripping through Studio makes
# it normalise the project to whatever it actually expects, so what ships is a file Studio
# itself serialised. It arrives pre-sliced too, which is what you want to send to a printer.
"$BS" --slice 0 --export-3mf "$PWD/$WORK/final.3mf" "$WORK/injected.3mf" \
      > "$WORK/export2.log" 2>&1 || true
test -f "$WORK/final.3mf" || { echo "re-export failed:"; tail -20 "$WORK/export2.log"; exit 1; }
python3 verify_3mf.py "$WORK/final.3mf" || exit 1
cp "$WORK/final.3mf" "$OUT"

echo
echo "--- $STEM / $V ---"
for g in "$WORK"/gcode/*.gcode; do
    grep -m1 "total estimated time" "$g" || true
    grep -m1 "total filament weight" "$g" || true
    grep -m1 "filament used \[g\]" "$g" || true
done
echo "wrote $OUT"
