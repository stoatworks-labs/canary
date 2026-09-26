/*
 * Status LEDs — a dumb pattern driver.
 *
 * Deliberately knows NOTHING about networks, CAN or the bridge. It sets
 * patterns on three GPIOs and nothing else, so it stays reusable and the
 * dependency arrow only ever points this way. The mapping from system state to
 * pattern lives in main/, which is the layer that can legitimately see
 * everything.
 *
 * The board has three MCU-driven LEDs, all ACTIVE HIGH — cathode to GND, anode
 * to the GPIO through 1k, so driving the pin high lights the LED. Pins and
 * active level come from board.h; nothing here hard-codes them, and board.h
 * carries the derivation and the caveat that it is not yet confirmed on
 * hardware.
 *
 * D304 "ON" is NOT one of these. It is wired from VCC_3V3 through R305, so it
 * lights whenever the rail is up, with or without firmware. That is what makes
 * it the only thing a factory operator can verify on an unprogrammed board.
 */
#ifndef LED_H
#define LED_H

#include <stdbool.h>

#include "esp_err.h"

typedef enum {
    LED_LAN = 0,   /* D301, green */
    LED_ERR,       /* D302, red   */
    LED_CAN,       /* D303, green */
    LED_COUNT
} led_id_t;

typedef enum {
    LED_OFF = 0,
    LED_ON,             /* solid */
    LED_BLINK_SLOW,     /* 1 Hz, even duty */
    LED_BLINK_FAST,     /* 4 Hz, even duty */
    LED_HEARTBEAT,      /* short double-pulse, ~1 s apart */
} led_pattern_t;

/* Claim the GPIOs and start the driver task. Runs a lamp test first: each LED
 * in turn, then all three together. That proves the MCU booted, the scheduler
 * runs and all three LEDs are fitted the right way round - which is the whole
 * point of having them during bring-up. */
esp_err_t led_start(void);

/* Set a repeating pattern. Cheap and idempotent; safe to call every tick. */
void led_set(led_id_t id, led_pattern_t pattern);

/* One short flash, overriding the pattern for ~75 ms. For bus activity: call it
 * per event and the LED flickers naturally with traffic. Never blocks. */
void led_blip(led_id_t id);

/* Blink a fault code on the ERR LED: `code` short blinks, then a long gap,
 * repeating. code 0 clears it and hands ERR back to led_set(). A count is
 * readable across a dark stage in a way a colour or duty cycle is not. */
void led_fault(int code);

/* Fault codes. Keep these in sync with the table in
 * hardware/fab/test/FUNCTIONAL-TEST-SPEC.md and the README. */
#define LED_FAULT_NONE          0
#define LED_FAULT_NO_LINK       1   /* Ethernet PHY reports no link */
#define LED_FAULT_NO_IP         2   /* link up but no DHCP lease */
#define LED_FAULT_CAN_BUS_OFF   3   /* TWAI went bus-off */
#define LED_FAULT_CAN_STOPPED   4   /* TWAI not running */

#endif /* LED_H */
