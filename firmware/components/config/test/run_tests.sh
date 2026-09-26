#!/bin/sh
# Host tests for settings validation. config_store.c is NVS-bound and cannot
# build here; config_check.c is deliberately free of ESP-IDF so the one piece that
# can strand a board is testable off-target.
set -e
cd "$(dirname "$0")"
CC=${CC:-cc}
"$CC" -std=c11 -Wall -Wextra -Werror -I.. -I../../r70_ddt/include ../config_check.c test_config_check.c -o /tmp/dbcanary_test_config
exec /tmp/dbcanary_test_config
