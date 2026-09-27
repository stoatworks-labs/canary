#!/bin/sh
# Host tests for the RM Byte Command Protocol codec. Pure framing logic, kept
# ESP-IDF-free so it can be checked against the vendor spec without hardware.
set -e
cd "$(dirname "$0")"
CC=${CC:-cc}
"$CC" -std=c99 -Wall -Wextra -Werror -I../include ../rmbcp.c test_rmbcp.c \
      -o /tmp/canary_test_rmbcp
exec /tmp/canary_test_rmbcp
