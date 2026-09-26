/*
 * dbCAN bus interface — ESP32 TWAI at the fixed 100 kbit/s dbCAN rate.
 *
 * dbCAN is CAN 2.0A with 11-bit identifiers at 100 kbit/s, and the rate "can not
 * be changed" (R70 software manual §1.3.1). R1 confirms it on every connect by
 * sending RMBCP 0x57 with the baud code 0xFE = 100 kbit/s.
 *
 * The bridge is transparent: no filtering by default, exactly as the R70 ships
 * (mask and arbitration both 0x000 pass everything).
 */
#ifndef DBCAN_H
#define DBCAN_H

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

typedef struct {
    uint32_t id;
    uint8_t data[8];
    uint8_t dlc;
    bool extended;
} dbcan_frame_t;

/* Called from the RX task for every frame received from the bus. */
typedef void (*dbcan_rx_cb_t)(const dbcan_frame_t *frame, void *ctx);

/* Bring up TWAI on the given pins and start the RX task. */
esp_err_t dbcan_start(int tx_gpio, int rx_gpio, dbcan_rx_cb_t cb, void *ctx);

/* Queue a frame for transmission. */
esp_err_t dbcan_transmit(const dbcan_frame_t *frame, uint32_t timeout_ms);

/* Messages seen on the bus in the last calculation interval, for RMBCP 0x47. */
uint16_t dbcan_busload(void);

/* Recover from a bus-off condition if one is latched. */
void dbcan_poll_recovery(void);

typedef enum {
    DBCAN_BUS_STOPPED = 0,   /* not started, or stopped after a fatal error */
    DBCAN_BUS_RUNNING,       /* normal - able to transmit and receive */
    DBCAN_BUS_BUS_OFF,       /* too many TX errors; needs recovery */
    DBCAN_BUS_RECOVERING,    /* recovery in progress */
} dbcan_bus_state_t;

/* Current controller state, for status indication. Distinguishing bus-off from
 * never-started matters during bring-up: one means the bus is wired and angry,
 * the other means nothing was initialised. */
dbcan_bus_state_t dbcan_bus_state(void);

#endif /* DBCAN_H */
