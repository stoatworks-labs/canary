/*
 * FreeRTOS task.h stand-in — tasks become detached pthreads.
 *
 * Stack depth and priority are accepted and ignored: the host has neither the
 * stack pressure nor the fixed-priority scheduling that make them meaningful,
 * and pretending otherwise would give false confidence. Stack sizing has to be
 * checked on target (or under QEMU), not here.
 */
#ifndef HOSTSIM_TASK_H
#define HOSTSIM_TASK_H

#include "freertos/FreeRTOS.h"

typedef void *TaskHandle_t;
typedef void (*TaskFunction_t)(void *);

BaseType_t xTaskCreate(TaskFunction_t fn, const char *name, uint32_t stack,
                       void *arg, UBaseType_t prio, TaskHandle_t *handle);

void       vTaskDelete(TaskHandle_t handle);
void       vTaskDelay(TickType_t ticks);
TickType_t xTaskGetTickCount(void);

#endif /* HOSTSIM_TASK_H */
