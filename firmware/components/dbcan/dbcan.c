/* dbCAN bus interface. See include/dbcan.h. */
#include "dbcan.h"

#include "driver/twai.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "dbcan";

static dbcan_rx_cb_t s_cb;
static void *s_ctx;
static volatile uint16_t s_busload;

static void rx_task(void *arg)
{
    (void)arg;
    uint32_t count = 0;
    TickType_t window = xTaskGetTickCount();

    for (;;) {
        twai_message_t msg;
        if (twai_receive(&msg, pdMS_TO_TICKS(100)) == ESP_OK) {
            count++;
            if (!msg.rtr && s_cb) {
                dbcan_frame_t frame = {
                    .id = msg.identifier,
                    .dlc = msg.data_length_code,
                    .extended = msg.extd,
                };
                for (int i = 0; i < msg.data_length_code && i < 8; i++) {
                    frame.data[i] = msg.data[i];
                }
                s_cb(&frame, s_ctx);
            }
        }
        /* Busload is reported in messages per interval; R1 sets the interval
         * with RMBCP 0xA4 (default 1000 ms). */
        if (xTaskGetTickCount() - window >= pdMS_TO_TICKS(1000)) {
            s_busload = (uint16_t)(count > 0xFFFF ? 0xFFFF : count);
            count = 0;
            window = xTaskGetTickCount();
        }
    }
}

esp_err_t dbcan_start(int tx_gpio, int rx_gpio, dbcan_rx_cb_t cb, void *ctx)
{
    s_cb = cb;
    s_ctx = ctx;

    twai_general_config_t g =
        TWAI_GENERAL_CONFIG_DEFAULT((gpio_num_t)tx_gpio, (gpio_num_t)rx_gpio,
                                    TWAI_MODE_NORMAL);
    g.rx_queue_len = 32;
    g.tx_queue_len = 32;
    /* dbCAN's rate is fixed; nothing else is legal on this bus. */
    const twai_timing_config_t t = TWAI_TIMING_CONFIG_100KBITS();
    /* Transparent bridge: accept everything, like the R70's default filters. */
    const twai_filter_config_t f = TWAI_FILTER_CONFIG_ACCEPT_ALL();

    esp_err_t err = twai_driver_install(&g, &t, &f);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "twai_driver_install: %s", esp_err_to_name(err));
        return err;
    }
    err = twai_start();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "twai_start: %s", esp_err_to_name(err));
        return err;
    }

    ESP_LOGI(TAG, "dbCAN up at 100 kbit/s on TX=%d RX=%d", tx_gpio, rx_gpio);
    xTaskCreate(rx_task, "dbcan_rx", 4096, NULL, 10, NULL);
    return ESP_OK;
}

esp_err_t dbcan_transmit(const dbcan_frame_t *frame, uint32_t timeout_ms)
{
    twai_message_t msg = {
        .identifier = frame->id,
        .data_length_code = frame->dlc > 8 ? 8 : frame->dlc,
        .extd = frame->extended,
    };
    for (int i = 0; i < msg.data_length_code; i++) {
        msg.data[i] = frame->data[i];
    }
    return twai_transmit(&msg, pdMS_TO_TICKS(timeout_ms));
}

uint16_t dbcan_busload(void) { return s_busload; }

void dbcan_poll_recovery(void)
{
    twai_status_info_t status;
    if (twai_get_status_info(&status) != ESP_OK) {
        return;
    }
    if (status.state == TWAI_STATE_BUS_OFF) {
        ESP_LOGW(TAG, "bus-off; initiating recovery");
        twai_initiate_recovery();
    } else if (status.state == TWAI_STATE_STOPPED) {
        twai_start();
    }
}

dbcan_bus_state_t dbcan_bus_state(void)
{
    twai_status_info_t status;
    if (twai_get_status_info(&status) != ESP_OK) {
        return DBCAN_BUS_STOPPED;
    }
    switch (status.state) {
    case TWAI_STATE_RUNNING:    return DBCAN_BUS_RUNNING;
    case TWAI_STATE_BUS_OFF:    return DBCAN_BUS_BUS_OFF;
    case TWAI_STATE_RECOVERING: return DBCAN_BUS_RECOVERING;
    default:                    return DBCAN_BUS_STOPPED;
    }
}
