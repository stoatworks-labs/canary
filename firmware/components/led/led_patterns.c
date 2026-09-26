/* See led_patterns.h. Deliberately depends on nothing. */
#include "led_patterns.h"

/* Blink geometry for fault codes. on+off is one blink slot; the gap that
 * follows is long enough that you can tell where a cycle starts even if you
 * glance at it mid-count. */
#define BLINK_ON_TICKS   3                  /* 60 ms  */
#define BLINK_OFF_TICKS  9                  /* 180 ms */
#define BLINK_SLOT       (BLINK_ON_TICKS + BLINK_OFF_TICKS)
#define BLINK_GAP        LED_TICKS_PER_S    /* 1 s    */

bool led_pattern_state(int p, uint32_t t)
{
    switch (p) {
    case LEDP_OFF:
        return false;
    case LEDP_ON:
        return true;
    case LEDP_BLINK_SLOW:                   /* 1 Hz, even duty */
        return (t % LED_TICKS_PER_S) < (LED_TICKS_PER_S / 2);
    case LEDP_BLINK_FAST:                   /* 4 Hz, even duty */
        return (t % (LED_TICKS_PER_S / 4)) < (LED_TICKS_PER_S / 8);
    case LEDP_HEARTBEAT: {
        /* Two short pulses then a rest. Reads as "alive" rather than "faulty" -
         * which matters, because a steady blink on a green LED next to a red
         * one is easy to misread as a warning. */
        const uint32_t ph = t % LED_TICKS_PER_S;
        return ph < 2 || (ph >= 5 && ph < 7);
    }
    default:
        return false;
    }
}

uint32_t led_fault_cycle_ticks(int code)
{
    if (code < 1) {
        return 0;
    }
    return (uint32_t)code * BLINK_SLOT + BLINK_GAP;
}

bool led_fault_state(int code, uint32_t t)
{
    if (code < 1) {
        return false;
    }
    const uint32_t cycle = led_fault_cycle_ticks(code);
    const uint32_t ph = t % cycle;
    if (ph >= (uint32_t)code * BLINK_SLOT) {
        return false;                       /* in the long gap */
    }
    return (ph % BLINK_SLOT) < BLINK_ON_TICKS;
}
