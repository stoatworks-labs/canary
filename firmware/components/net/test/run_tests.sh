#!/bin/sh
# Host tests for the address-selection logic. net.c itself is ESP-IDF-bound and
# cannot be built here; net_select.c is deliberately kept free of it so the one
# decision that can silently make a unit unreachable is testable off-target.
set -e
cd "$(dirname "$0")"
CC=${CC:-cc}
"$CC" -std=c99 -Wall -Wextra -Werror -I../include ../net_select.c test_net_select.c \
      -o /tmp/canary_test_net_select
exec /tmp/canary_test_net_select
