#!/bin/sh
# Fuzz the two network-facing parsers under ASan + UBSan.
#
# Uses libFuzzer when the toolchain has it (coverage-guided, much stronger) and
# falls back to standalone_main.c when it does not — which is the case for
# Apple's clang, so the fallback is what runs on this project's Macs. The
# fallback finds the same CLASS of bug, because ASan/UBSan are the detectors;
# it just explores less cleverly. Do not read a clean fallback run as the same
# assurance a clean libFuzzer run would give.
#
#   ./run_fuzz.sh                     both targets, default budget
#   ./run_fuzz.sh --iterations 2000000
#   ./run_fuzz.sh --seed 12345        reproduce an exact run
set -e
cd "$(dirname "$0")"

CC=${CC:-cc}
COMPONENTS=../../components
OUTDIR=${OUTDIR:-/tmp/canary-fuzz}
mkdir -p "$OUTDIR"

SAN="-fsanitize=address,undefined -fno-omit-frame-pointer -fno-sanitize-recover=all"
CFLAGS="-std=c99 -Wall -Wextra -Werror -O1 -g $SAN"

# Does this toolchain have libFuzzer?
if echo 'int LLVMFuzzerTestOneInput(const unsigned char*d,unsigned long s){(void)d;(void)s;return 0;}' \
   > "$OUTDIR/probe.c" 2>/dev/null &&
   "$CC" -fsanitize=fuzzer "$OUTDIR/probe.c" -o "$OUTDIR/probe" 2>/dev/null; then
    HAVE_LIBFUZZER=1
    echo "libFuzzer: available (coverage-guided)"
else
    HAVE_LIBFUZZER=0
    echo "libFuzzer: NOT available - using the standalone mutator"
fi
rm -f "$OUTDIR/probe" "$OUTDIR/probe.c"

run_target() {
    name=$1
    src=$2
    component=$3
    include=$4

    echo
    echo "=== fuzzing $name ==="
    if [ "$HAVE_LIBFUZZER" = 1 ]; then
        # shellcheck disable=SC2086
        "$CC" $CFLAGS -fsanitize=fuzzer -I"$include" \
            "$src" "$component" -o "$OUTDIR/$name"
        mkdir -p "$OUTDIR/corpus-$name"
        "$OUTDIR/$name" "$OUTDIR/corpus-$name" \
            -max_total_time="${SECONDS_PER_TARGET:-30}"
    else
        # shellcheck disable=SC2086
        "$CC" $CFLAGS -I"$include" \
            "$src" "$component" standalone_main.c -o "$OUTDIR/$name"
        # shellcheck disable=SC2086
        "$OUTDIR/$name" $DRIVER_ARGS --crash-file "$OUTDIR/$name-crash.bin"
    fi
}

# Pass-through of --iterations / --seed to the standalone driver.
DRIVER_ARGS=""
while [ $# -gt 0 ]; do
    case $1 in
        --iterations) DRIVER_ARGS="$DRIVER_ARGS --iterations $2"; shift 2 ;;
        --seed)       DRIVER_ARGS="$DRIVER_ARGS --seed $2";       shift 2 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

run_target fuzz_rmbcp fuzz_rmbcp.c "$COMPONENTS/rmbcp/rmbcp.c" "$COMPONENTS/rmbcp/include"
run_target fuzz_ddt   fuzz_ddt.c   "$COMPONENTS/r70_ddt/r70_ddt.c" "$COMPONENTS/r70_ddt/include"

echo
echo "fuzzing complete - no crash"
