#!/bin/sh
# Host tests for the R70 device-detection protocol. Pure packet logic, kept
# ESP-IDF-free so it can be checked against the captured R1 probe.
set -e
cd "$(dirname "$0")"
CC=${CC:-cc}
"$CC" -std=c99 -Wall -Wextra -Werror -I../include ../r70_ddt.c test_r70_ddt.c \
      -o /tmp/dbcanary_test_ddt
exec /tmp/dbcanary_test_ddt
