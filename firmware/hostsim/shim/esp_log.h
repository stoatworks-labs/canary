/*
 * ESP-IDF esp_log.h stand-in for the host build.
 *
 * Same call sites, same tags, same levels — written to stderr so the daemon's
 * stdout stays clean for machine-readable output. CANARY_LOG_LEVEL (0-5)
 * sets verbosity, defaulting to INFO, matching esp_log_level_t ordering.
 */
#ifndef HOSTSIM_ESP_LOG_H
#define HOSTSIM_ESP_LOG_H

#include <stdio.h>

/* NONE=0 ERROR=1 WARN=2 INFO=3 DEBUG=4 VERBOSE=5 — as esp_log_level_t. */
int hostsim_log_level(void);

#define HOSTSIM_LOG(lvl, letter, tag, fmt, ...)                               \
    do {                                                                      \
        if (hostsim_log_level() >= (lvl)) {                                   \
            fprintf(stderr, "%c (%s) " fmt "\n", letter, tag, ##__VA_ARGS__); \
        }                                                                     \
    } while (0)

#define ESP_LOGE(tag, fmt, ...) HOSTSIM_LOG(1, 'E', tag, fmt, ##__VA_ARGS__)
#define ESP_LOGW(tag, fmt, ...) HOSTSIM_LOG(2, 'W', tag, fmt, ##__VA_ARGS__)
#define ESP_LOGI(tag, fmt, ...) HOSTSIM_LOG(3, 'I', tag, fmt, ##__VA_ARGS__)
#define ESP_LOGD(tag, fmt, ...) HOSTSIM_LOG(4, 'D', tag, fmt, ##__VA_ARGS__)
#define ESP_LOGV(tag, fmt, ...) HOSTSIM_LOG(5, 'V', tag, fmt, ##__VA_ARGS__)

#endif /* HOSTSIM_ESP_LOG_H */
