/*
 * FreeRTOS.h stand-in for the host build.
 *
 * One tick is one millisecond here, so pdMS_TO_TICKS is the identity. The
 * firmware only uses ticks for the busload window and receive timeouts, both
 * of which are expressed in ms anyway.
 */
#ifndef HOSTSIM_FREERTOS_H
#define HOSTSIM_FREERTOS_H

#include <stdint.h>

typedef uint32_t TickType_t;
typedef int      BaseType_t;
typedef unsigned UBaseType_t;

#define pdTRUE  1
#define pdFALSE 0
#define pdPASS  1

#define portTICK_PERIOD_MS 1u
#define portMAX_DELAY      ((TickType_t)0xFFFFFFFFu)

#define pdMS_TO_TICKS(ms) ((TickType_t)(ms))

#endif /* HOSTSIM_FREERTOS_H */
