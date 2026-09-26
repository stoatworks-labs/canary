/*
 * Pattern maths, split out of led.c so it can be host-tested.
 *
 * ESP-IDF-free on purpose: these two functions decide, for a given tick, whether
 * a LED is lit. A blink count that reads as 4 when it means 3 sends a technician
 * to the wrong fault, so the arithmetic is pinned by tests in test/ rather than
 * eyeballed on a bench that does not exist yet.
 *
 * Not a public interface — led.h is. Nothing outside this component includes it.
 */
#ifndef LED_PATTERNS_H
#define LED_PATTERNS_H

#include <stdbool.h>
#include <stdint.h>

/* 25 ms tick, giving 40 ticks per second.
 *
 * 25 rather than the obvious 20: a 4 Hz blink is a 250 ms period, which is 12.5
 * ticks at 20 ms. Integer division silently rounded that to 12, making the
 * "4 Hz" pattern actually 4.17 Hz with a period that does not divide into a
 * second - so it visibly beat against the 1 Hz pattern next to it. At 25 ms both
 * 1 Hz (40 ticks) and 4 Hz (10 ticks) are whole numbers with exact even duty.
 * The host tests assert this; see test/test_led_patterns.c. */
#define LED_TICK_MS      25
#define LED_TICKS_PER_S  (1000 / LED_TICK_MS)

/* Pattern values, mirroring led_pattern_t. Duplicated as plain ints so this
 * header does not drag esp_err.h in behind led.h; led.c static-asserts that the
 * two agree, so they cannot drift. */
#define LEDP_OFF         0
#define LEDP_ON          1
#define LEDP_BLINK_SLOW  2
#define LEDP_BLINK_FAST  3
#define LEDP_HEARTBEAT   4

/* Is the LED lit at tick `t` under pattern `p`? */
bool led_pattern_state(int p, uint32_t t);

/* Is the ERR LED lit at tick `t` while blinking fault code `code` (>= 1)?
 * `code` short blinks, then a gap about a second long, repeating. */
bool led_fault_state(int code, uint32_t t);

/* Length of one full fault-code cycle in ticks. Exposed for the tests, which
 * need to count blinks over exactly one cycle. */
uint32_t led_fault_cycle_ticks(int code);

#endif /* LED_PATTERNS_H */
