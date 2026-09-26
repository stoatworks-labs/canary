/* Status LED pattern driver. See include/led.h.
 *
 * This file is the ESP-IDF half: GPIOs, a tick task, and the lamp test. The
 * pattern arithmetic lives in led_patterns.c so it can be host-tested without
 * hardware or an IDF install. */
#include "led.h"

#include "board.h"
#include "driver/gpio.h"
#include "esp_check.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "led_patterns.h"

static const char *TAG = "led";

/* led_patterns.h restates the pattern values as plain ints so it can stay
 * IDF-free. Pin the two together here, so a new pattern added to the enum
 * without adding it to the maths is a compile error rather than an LED that
 * silently stays off. */
_Static_assert((int)LED_OFF        == LEDP_OFF,        "LED_OFF mismatch");
_Static_assert((int)LED_ON         == LEDP_ON,         "LED_ON mismatch");
_Static_assert((int)LED_BLINK_SLOW == LEDP_BLINK_SLOW, "LED_BLINK_SLOW mismatch");
_Static_assert((int)LED_BLINK_FAST == LEDP_BLINK_FAST, "LED_BLINK_FAST mismatch");
_Static_assert((int)LED_HEARTBEAT  == LEDP_HEARTBEAT,  "LED_HEARTBEAT mismatch");

static const int PIN[LED_COUNT] = {
    [LED_LAN] = BOARD_LED_LAN_GPIO,
    [LED_ERR] = BOARD_LED_ERR_GPIO,
    [LED_CAN] = BOARD_LED_CAN_GPIO,
};

static volatile led_pattern_t s_pattern[LED_COUNT];
static volatile int s_blip[LED_COUNT];       /* ticks of forced-on remaining */
static volatile int s_fault;                 /* 0 = none, else blink count */

static void drive(led_id_t id, bool lit)
{
    /* Polarity lives in board.h, not here - see its LED POLARITY note. */
    gpio_set_level(PIN[id], lit ? BOARD_LED_ACTIVE_LEVEL
                                : !BOARD_LED_ACTIVE_LEVEL);
}

static void lamp_test(void)
{
    /* Each in turn, then all three. If one stays dark here it is fitted
     * backwards or its GPIO is wrong - far easier to spot now than later. This
     * is step A.6 of hardware/fab/test/FUNCTIONAL-TEST-SPEC.md. */
    for (int i = 0; i < LED_COUNT; i++) {
        drive((led_id_t)i, true);
        vTaskDelay(pdMS_TO_TICKS(180));
        drive((led_id_t)i, false);
    }
    for (int i = 0; i < LED_COUNT; i++) {
        drive((led_id_t)i, true);
    }
    vTaskDelay(pdMS_TO_TICKS(300));
    for (int i = 0; i < LED_COUNT; i++) {
        drive((led_id_t)i, false);
    }
}

static void led_task(void *arg)
{
    (void)arg;
    lamp_test();

    uint32_t t = 0;
    for (;;) {
        for (int i = 0; i < LED_COUNT; i++) {
            bool lit;
            if (s_blip[i] > 0) {
                s_blip[i]--;
                lit = true;                    /* blip overrides everything */
            } else if (i == LED_ERR && s_fault != LED_FAULT_NONE) {
                lit = led_fault_state(s_fault, t);
            } else {
                lit = led_pattern_state((int)s_pattern[i], t);
            }
            drive((led_id_t)i, lit);
        }
        t++;
        vTaskDelay(pdMS_TO_TICKS(LED_TICK_MS));
    }
}

esp_err_t led_start(void)
{
    uint64_t mask = 0;
    for (int i = 0; i < LED_COUNT; i++) {
        mask |= 1ULL << PIN[i];
    }
    const gpio_config_t cfg = {
        .pin_bit_mask = mask,
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_RETURN_ON_ERROR(gpio_config(&cfg), TAG, "gpio_config");

    for (int i = 0; i < LED_COUNT; i++) {
        drive((led_id_t)i, false);
        s_pattern[i] = LED_OFF;
        s_blip[i] = 0;
    }
    s_fault = LED_FAULT_NONE;

    /* Small stack: this task only toggles pins. Low priority - status display
     * must never delay the bridge. */
    if (xTaskCreate(led_task, "led", 2048, NULL, 2, NULL) != pdPASS) {
        return ESP_ERR_NO_MEM;
    }
    ESP_LOGI(TAG, "LEDs on GPIO %d/%d/%d (active %s)",
             PIN[LED_LAN], PIN[LED_ERR], PIN[LED_CAN],
             BOARD_LED_ACTIVE_LEVEL ? "high" : "low");
    return ESP_OK;
}

void led_set(led_id_t id, led_pattern_t pattern)
{
    if (id < LED_COUNT) {
        s_pattern[id] = pattern;
    }
}

void led_blip(led_id_t id)
{
    if (id < LED_COUNT) {
        s_blip[id] = 3;                        /* 75 ms */
    }
}

void led_fault(int code)
{
    s_fault = code;
}
