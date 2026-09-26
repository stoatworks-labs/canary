/* Host tests for the LED pattern arithmetic.
 *
 * These matter more than they look. The ERR LED communicates a fault by a blink
 * COUNT, so an off-by-one in the phase maths does not produce a slightly wrong
 * display — it produces a technician chasing the wrong fault. The tests count
 * actual rising edges over a whole cycle rather than checking the formula, so
 * they would catch a rewrite that is arithmetically different but visually
 * identical, and reject one that is not.
 *
 * Frequencies are checked as edge counts over exactly one second of ticks,
 * because "1 Hz" is the observable claim; the modulo expression is not. */
#include <stdio.h>

#include "led_patterns.h"

static int checks = 0, fails = 0;
#define CHECK(c, ...) do { checks++; if (!(c)) { \
    fails++; printf("  FAIL %s:%d  ", __FILE__, __LINE__); printf(__VA_ARGS__); \
    printf("\n"); } } while (0)

/* Rising edges of a pattern over `ticks`, starting from tick 0. */
static int pattern_edges(int p, uint32_t ticks)
{
    int edges = 0;
    bool prev = false;
    for (uint32_t t = 0; t < ticks; t++) {
        const bool now = led_pattern_state(p, t);
        if (now && !prev) {
            edges++;
        }
        prev = now;
    }
    return edges;
}

/* Rising edges of a fault code over `ticks`. */
static int fault_edges(int code, uint32_t ticks)
{
    int edges = 0;
    bool prev = false;
    for (uint32_t t = 0; t < ticks; t++) {
        const bool now = led_fault_state(code, t);
        if (now && !prev) {
            edges++;
        }
        prev = now;
    }
    return edges;
}

/* Ticks a pattern spends lit over `ticks`. */
static int pattern_on_ticks(int p, uint32_t ticks)
{
    int on = 0;
    for (uint32_t t = 0; t < ticks; t++) {
        if (led_pattern_state(p, t)) {
            on++;
        }
    }
    return on;
}

int main(void)
{
    const uint32_t one_second = LED_TICKS_PER_S;

    printf("tick geometry\n");
    /* The whole file assumes a tick divides a second evenly and that 4 Hz and
     * its half-duty both land on whole ticks. If someone retunes TICK_MS to
     * something like 30 ms, these fire before any pattern test misleads them. */
    CHECK(1000 % LED_TICK_MS == 0, "tick %d ms does not divide 1 s", LED_TICK_MS);
    CHECK(LED_TICKS_PER_S % 8 == 0,
          "TICKS_PER_S %d not divisible by 8; 4 Hz half-duty will be uneven",
          LED_TICKS_PER_S);

    printf("static patterns\n");
    for (uint32_t t = 0; t < 3 * one_second; t++) {
        CHECK(!led_pattern_state(LEDP_OFF, t), "OFF lit at t=%u", t);
        CHECK(led_pattern_state(LEDP_ON, t), "ON dark at t=%u", t);
    }

    printf("blink rates are what the README claims\n");
    CHECK(pattern_edges(LEDP_BLINK_SLOW, one_second) == 1,
          "BLINK_SLOW: %d edges in 1 s, want 1",
          pattern_edges(LEDP_BLINK_SLOW, one_second));
    CHECK(pattern_edges(LEDP_BLINK_FAST, one_second) == 4,
          "BLINK_FAST: %d edges in 1 s, want 4",
          pattern_edges(LEDP_BLINK_FAST, one_second));

    printf("blink duty is even\n");
    /* An uneven duty is how "1 Hz" quietly becomes "a flicker" - visible on a
     * bench, invisible in the source. */
    CHECK(pattern_on_ticks(LEDP_BLINK_SLOW, one_second) == (int)one_second / 2,
          "BLINK_SLOW lit %d of %u ticks, want half",
          pattern_on_ticks(LEDP_BLINK_SLOW, one_second), one_second);
    CHECK(pattern_on_ticks(LEDP_BLINK_FAST, one_second) == (int)one_second / 2,
          "BLINK_FAST lit %d of %u ticks, want half",
          pattern_on_ticks(LEDP_BLINK_FAST, one_second), one_second);

    printf("heartbeat is a double pulse, once a second, mostly dark\n");
    CHECK(pattern_edges(LEDP_HEARTBEAT, one_second) == 2,
          "HEARTBEAT: %d edges in 1 s, want 2",
          pattern_edges(LEDP_HEARTBEAT, one_second));
    {
        /* Must be clearly dim overall, or it reads as a blink rather than a
         * heartbeat and looks like a warning next to the red LED. */
        const int on = pattern_on_ticks(LEDP_HEARTBEAT, one_second);
        CHECK(on > 0 && on < (int)one_second / 4,
              "HEARTBEAT lit %d of %u ticks, want a small fraction",
              on, one_second);
    }
    /* Repeats every second, not merely once. */
    CHECK(pattern_edges(LEDP_HEARTBEAT, 5 * one_second) == 10,
          "HEARTBEAT: %d edges in 5 s, want 10",
          pattern_edges(LEDP_HEARTBEAT, 5 * one_second));

    printf("unknown pattern values are dark, not stuck on\n");
    /* Defensive: a garbage value must fail safe to off, never to a lit LED that
     * looks like a real state. */
    for (uint32_t t = 0; t < one_second; t++) {
        CHECK(!led_pattern_state(99, t), "unknown pattern lit at t=%u", t);
        CHECK(!led_pattern_state(-1, t), "negative pattern lit at t=%u", t);
    }

    printf("fault codes blink exactly their own number\n");
    /* The headline property: code N must be countable as N, over one cycle and
     * over several. Codes 1-4 are the ones in led.h; 5 and 6 are checked so the
     * arithmetic is not merely tuned to the current set. */
    for (int code = 1; code <= 6; code++) {
        const uint32_t cycle = led_fault_cycle_ticks(code);
        CHECK(cycle > 0, "code %d: zero-length cycle", code);
        CHECK(fault_edges(code, cycle) == code,
              "code %d: %d blinks in one cycle, want %d",
              code, fault_edges(code, cycle), code);
        CHECK(fault_edges(code, 4 * cycle) == 4 * code,
              "code %d: %d blinks in four cycles, want %d",
              code, fault_edges(code, 4 * cycle), 4 * code);
    }

    printf("fault cycles start lit and end dark\n");
    /* Both halves of "countable": the cycle must open on a blink, and the gap
     * must be long enough to separate one group from the next. Without the
     * trailing-dark check, code 3 and code 6 would look identical. */
    for (int code = 1; code <= 6; code++) {
        const uint32_t cycle = led_fault_cycle_ticks(code);
        CHECK(led_fault_state(code, 0), "code %d: cycle does not start lit", code);
        CHECK(!led_fault_state(code, cycle - 1),
              "code %d: cycle does not end dark", code);

        /* The gap must be at least as long as one blink slot, or the groups
         * merge. Measure the actual dark run at the end of the cycle. */
        uint32_t dark = 0;
        for (uint32_t t = cycle; t > 0; t--) {
            if (led_fault_state(code, t - 1)) {
                break;
            }
            dark++;
        }
        CHECK(dark >= LED_TICKS_PER_S / 2,
              "code %d: only %u dark ticks before the next group; groups will "
              "run together", code, dark);
    }

    printf("code 0 and negatives are dark - led_fault(0) must clear ERR\n");
    /* status.c calls led_fault(LED_FAULT_NONE) on every poll when nothing is
     * wrong. If 0 blinked, ERR would never go out. */
    for (uint32_t t = 0; t < 3 * one_second; t++) {
        CHECK(!led_fault_state(0, t), "code 0 lit at t=%u", t);
        CHECK(!led_fault_state(-1, t), "code -1 lit at t=%u", t);
    }
    CHECK(led_fault_cycle_ticks(0) == 0, "code 0 has a nonzero cycle");

    printf("no wraparound glitch at the 32-bit tick rollover\n");
    /* The tick counter is a uint32_t incrementing every 20 ms, so it wraps after
     * ~994 days. A unit left powered on an installed system will get there. The
     * patterns are pure functions of t, so this cannot break - but assert it, so
     * that a future rewrite carrying state cannot break it silently. */
    for (uint32_t i = 0; i < 200; i++) {
        const uint32_t t = 0xFFFFFFFFu - 100 + i;   /* deliberately wraps */
        (void)led_pattern_state(LEDP_HEARTBEAT, t);
        (void)led_fault_state(3, t);
    }
    CHECK(led_pattern_state(LEDP_ON, 0xFFFFFFFFu), "ON dark at max tick");
    CHECK(!led_pattern_state(LEDP_OFF, 0xFFFFFFFFu), "OFF lit at max tick");

    printf("\n%d checks, %d failures\n", checks, fails);
    return fails ? 1 : 0;
}
