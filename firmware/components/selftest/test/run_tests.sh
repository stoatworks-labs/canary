#!/bin/sh
# Host tests for the self-test report. selftest_report.c is deliberately free
# of ESP-IDF so the accept/reject logic and the output format that
# tools/board_test.py parses can both be checked without hardware.
set -e
cd "$(dirname "$0")"
CC=${CC:-cc}
"$CC" -std=c11 -Wall -Wextra -Werror -I../include ../selftest_report.c \
      test_selftest_report.c -o /tmp/dbcanary_test_selftest_report
exec /tmp/dbcanary_test_selftest_report
