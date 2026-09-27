#!/bin/sh
# Host tests for the LED pattern arithmetic. Kept ESP-IDF-free so the blink
# geometry can be checked without hardware - which matters, because a fault code
# that blinks the wrong number of times sends a technician to the wrong fault.
set -e
cd "$(dirname "$0")"
CC=${CC:-cc}
"$CC" -std=c11 -Wall -Wextra -Werror -I.. ../led_patterns.c test_led_patterns.c \
      -o /tmp/canary_test_led_patterns
exec /tmp/canary_test_led_patterns
