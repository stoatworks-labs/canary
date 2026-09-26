#!/bin/sh
# Integration tests for the host build: the shipping bridge C on real sockets.
#
# Unlike the component suites these need Python and start processes, so they
# are slower and are kept out of firmware/components/*/test. The top-level
# run_tests.sh calls this after the unit tests.
#
# FUZZ_ITERATIONS=0 skips fuzzing; the default is a short smoke budget. For a
# real fuzzing run use hostsim/fuzz/run_fuzz.sh directly with a large budget.
set -e
cd "$(dirname "$0")"

HOSTSIM=..
ROOT=../../..
FUZZ_ITERATIONS=${FUZZ_ITERATIONS:-200000}

# Prefer the project venv; these tests import tools/rmbcp.py but need no
# third-party packages, so a bare python3 works too.
if [ -x "$ROOT/.venv/bin/python" ]; then
    PY="$ROOT/.venv/bin/python"
else
    PY=$(command -v python3)
fi

echo "--- building dbcanaryd"
"$HOSTSIM/build.sh" >/dev/null

echo
echo "--- end-to-end: client -> bridge -> virtual CAN -> simulated amp"
"$PY" test_loop.py

echo
echo "--- adversarial soak"
"$PY" test_soak.py

if [ "$FUZZ_ITERATIONS" != "0" ]; then
    echo
    echo "--- fuzzing the network-facing parsers (smoke budget)"
    "$HOSTSIM/fuzz/run_fuzz.sh" --iterations "$FUZZ_ITERATIONS" | tail -6
fi
