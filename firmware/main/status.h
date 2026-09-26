/*
 * Status indication — maps system state onto the LEDs. See status.c for what
 * each pattern means.
 */
#ifndef STATUS_H
#define STATUS_H

#include "esp_err.h"

/* Start the status task. Call after led_start() and after the bridge is up. */
esp_err_t status_start(void);

#endif /* STATUS_H */
