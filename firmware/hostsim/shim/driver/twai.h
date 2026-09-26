/*
 * driver/twai.h stand-in, backed by the virtual CAN bus in hostsim/vcan.c.
 *
 * The point is that firmware/components/dbcan/dbcan.c compiles UNCHANGED
 * against this. Anything the real driver exposes that dbcan.c does not call is
 * deliberately absent, so a future call to an unimplemented API fails to build
 * here rather than silently doing nothing.
 *
 * What this does NOT model: bit timing, arbitration, error counters, real
 * bus-off. Those need silicon. See hostsim/README.md.
 */
#ifndef HOSTSIM_TWAI_H
#define HOSTSIM_TWAI_H

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"
#include "freertos/FreeRTOS.h"

typedef int gpio_num_t;

typedef enum {
    TWAI_MODE_NORMAL = 0,
    TWAI_MODE_NO_ACK,
    TWAI_MODE_LISTEN_ONLY,
} twai_mode_t;

typedef enum {
    TWAI_STATE_STOPPED = 0,
    TWAI_STATE_RUNNING,
    TWAI_STATE_BUS_OFF,
    TWAI_STATE_RECOVERING,
} twai_state_t;

typedef struct {
    uint32_t identifier;
    uint8_t  data_length_code;
    uint8_t  data[8];
    bool     extd;
    bool     rtr;
    bool     ss;
    bool     self;
    bool     dlc_non_comp;
} twai_message_t;

typedef struct {
    twai_mode_t mode;
    gpio_num_t  tx_io;
    gpio_num_t  rx_io;
    uint32_t    rx_queue_len;
    uint32_t    tx_queue_len;
} twai_general_config_t;

typedef struct {
    uint32_t brp;
} twai_timing_config_t;

typedef struct {
    uint32_t acceptance_code;
    uint32_t acceptance_mask;
    bool     single_filter;
} twai_filter_config_t;

typedef struct {
    twai_state_t state;
    uint32_t     msgs_to_tx;
    uint32_t     msgs_to_rx;
    uint32_t     tx_error_counter;
    uint32_t     rx_error_counter;
    uint32_t     bus_error_count;
} twai_status_info_t;

#define TWAI_GENERAL_CONFIG_DEFAULT(tx, rx, op_mode)                          \
    ((twai_general_config_t){.mode = (op_mode),                               \
                             .tx_io = (tx),                                   \
                             .rx_io = (rx),                                   \
                             .rx_queue_len = 5,                               \
                             .tx_queue_len = 5})

#define TWAI_TIMING_CONFIG_100KBITS() ((twai_timing_config_t){.brp = 40})

#define TWAI_FILTER_CONFIG_ACCEPT_ALL()                                       \
    ((twai_filter_config_t){.acceptance_code = 0,                             \
                            .acceptance_mask = 0xFFFFFFFF,                    \
                            .single_filter = true})

esp_err_t twai_driver_install(const twai_general_config_t *g,
                              const twai_timing_config_t *t,
                              const twai_filter_config_t *f);
esp_err_t twai_start(void);
esp_err_t twai_stop(void);
esp_err_t twai_driver_uninstall(void);
esp_err_t twai_transmit(const twai_message_t *msg, TickType_t timeout);
esp_err_t twai_receive(twai_message_t *msg, TickType_t timeout);
esp_err_t twai_get_status_info(twai_status_info_t *status);
esp_err_t twai_initiate_recovery(void);

#endif /* HOSTSIM_TWAI_H */
