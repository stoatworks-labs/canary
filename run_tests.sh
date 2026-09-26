#!/bin/sh
# Every test in the project: the Python reference implementation and the C
# firmware components. Both carry the same vendor-spec vectors.
set -e
cd "$(dirname "$0")"

echo "=== tools (Python reference implementation) ==="
if [ -x .venv/bin/python ]; then
    .venv/bin/python -m pytest tools/ -q
else
    echo "  no .venv; create with: python3 -m venv .venv && ./.venv/bin/pip install pytest"
fi

for suite in firmware/components/*/test/run_tests.sh; do
    echo
    echo "=== $(basename "$(dirname "$(dirname "$suite")")") (firmware, host build) ==="
    "$suite"
done

# The integration suite: the same C, but linked into a process and put on real
# sockets, so the protocol is exercised end to end rather than one component at
# a time. Slower than the unit tests and needs python3 — SKIP_HOSTSIM=1 to omit.
if [ -z "$SKIP_HOSTSIM" ]; then
    echo
    echo "=== hostsim (integration: the bridge on real sockets) ==="
    firmware/hostsim/test/run_tests.sh
fi
