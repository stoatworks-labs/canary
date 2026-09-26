/*
 * The host stand-ins for the slice of ESP-IDF the bridge needs: error names,
 * log level, and FreeRTOS tasks as pthreads.
 *
 * See hostsim/README.md for what this does and does not prove.
 */
#include "esp_err.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* --- esp_err ------------------------------------------------------------- */

const char *esp_err_to_name(esp_err_t code)
{
    switch (code) {
    case ESP_OK:                  return "ESP_OK";
    case ESP_FAIL:                return "ESP_FAIL";
    case ESP_ERR_NO_MEM:          return "ESP_ERR_NO_MEM";
    case ESP_ERR_INVALID_ARG:     return "ESP_ERR_INVALID_ARG";
    case ESP_ERR_INVALID_STATE:   return "ESP_ERR_INVALID_STATE";
    case ESP_ERR_TIMEOUT:         return "ESP_ERR_TIMEOUT";
    case ESP_ERR_NOT_FOUND:       return "ESP_ERR_NOT_FOUND";
    default:                      return "UNKNOWN";
    }
}

/* --- logging ------------------------------------------------------------- */

int hostsim_log_level(void)
{
    static int cached = -1;
    if (cached < 0) {
        const char *env = getenv("DBCANARY_LOG_LEVEL");
        cached = env ? atoi(env) : 3; /* INFO */
    }
    return cached;
}

/* --- tasks --------------------------------------------------------------- */

typedef struct {
    TaskFunction_t fn;
    void          *arg;
} task_start_t;

static void *task_trampoline(void *raw)
{
    task_start_t *start = raw;
    TaskFunction_t fn = start->fn;
    void *arg = start->arg;
    free(start);
    fn(arg);
    return NULL;
}

BaseType_t xTaskCreate(TaskFunction_t fn, const char *name, uint32_t stack,
                       void *arg, UBaseType_t prio, TaskHandle_t *handle)
{
    (void)name;
    (void)stack; /* host stacks are not the target's — see task.h */
    (void)prio;

    task_start_t *start = malloc(sizeof(*start));
    if (!start) {
        return pdFALSE;
    }
    start->fn = fn;
    start->arg = arg;

    pthread_t thread;
    if (pthread_create(&thread, NULL, task_trampoline, start) != 0) {
        free(start);
        return pdFALSE;
    }
    pthread_detach(thread);
    if (handle) {
        *handle = (TaskHandle_t)thread;
    }
    return pdPASS;
}

void vTaskDelete(TaskHandle_t handle)
{
    if (handle == NULL) {
        pthread_exit(NULL);
    }
    /* Deleting another task has no safe pthread equivalent and the firmware
     * never does it. Fail loudly rather than silently doing nothing. */
    abort();
}

void vTaskDelay(TickType_t ticks)
{
    struct timespec ts = {
        .tv_sec = (time_t)(ticks / 1000u),
        .tv_nsec = (long)((ticks % 1000u) * 1000000u),
    };
    nanosleep(&ts, NULL);
}

TickType_t xTaskGetTickCount(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (TickType_t)((uint64_t)ts.tv_sec * 1000u +
                        (uint64_t)ts.tv_nsec / 1000000u);
}
