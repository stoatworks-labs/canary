/*
 * Board self-test. See include/selftest.h.
 *
 * Design rule: every test here must be able to run with NOTHING plugged into
 * the board. A test that needs a cable, a switch or a bus partner belongs in
 * hardware/fab/test/BENCH-BRINGUP.md, not here, because a production operator
 * will not have those and will report a false failure.
 *
 * Two tests carry most of the value:
 *
 *   eth.versionr    One SPI read of the W5500's VERSIONR at 0x0039 must return
 *                   0x04. That single byte proves the SPI bus in both
 *                   directions, the W5500's 3.3 V supply, its 25 MHz crystal
 *                   and its reset line. Nothing else on this board is one read
 *                   away from that much coverage.
 *
 *   can.loopback    TWAI in NO_ACK mode with a self-reception request drives a
 *                   real frame out of GPIO4, through the ADM3053, ACROSS THE
 *                   ISOLATION BARRIER, onto CANH/CANL, back through the
 *                   receiver and into GPIO5. It therefore proves the isolated
 *                   DC-DC started, which is the one thing on the CAN side that
 *                   cannot be checked from the system domain.
 *
 * NONE OF THIS HAS RUN ON HARDWARE. The limits are predicted from the
 * schematic and the datasheets.
 */
#include <string.h>

#include "selftest.h"

#include "board.h"
#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "driver/twai.h"
#include "esp_chip_info.h"
#include "esp_flash.h"
#include "esp_idf_version.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "selftest";

/* --- W5500 registers, common register block (BSB = 0) -------------------- */
#define W5500_REG_VERSIONR   0x0039   /* read-only, always 0x04 */
#define W5500_REG_RTR        0x0019   /* retry time, 16-bit, safely writable */
#define W5500_RTR_RESET      0x07D0   /* datasheet reset value, 200 ms */
#define W5500_VERSION_VALUE  0x04

/* SPI control byte: BSB[7:3] | RWB[2] | OM[1:0]. Common block, VDM. */
#define W5500_CTL_READ       0x00
#define W5500_CTL_WRITE      0x04

/* ------------------------------------------------------------------------ */
/* Non-invasive identity checks                                             */
/* ------------------------------------------------------------------------ */
static const char *reset_reason_str(esp_reset_reason_t r)
{
    switch (r) {
    case ESP_RST_POWERON:  return "power-on";
    case ESP_RST_EXT:      return "external-reset";   /* SW301 */
    case ESP_RST_SW:       return "software";
    case ESP_RST_PANIC:    return "panic";
    case ESP_RST_INT_WDT:  return "int-watchdog";
    case ESP_RST_TASK_WDT: return "task-watchdog";
    case ESP_RST_WDT:      return "other-watchdog";
    case ESP_RST_BROWNOUT: return "brownout";
    case ESP_RST_USB:      return "usb";
    default:               return "unknown";
    }
}

void selftest_post(selftest_report_t *r)
{
    esp_chip_info_t chip;
    esp_chip_info(&chip);
    selftest_report_add(r, "chip", SELFTEST_INFO,
                        "ESP32-S3 rev v%d.%d, %d core(s), idf %s",
                        chip.revision / 100, chip.revision % 100, chip.cores,
                        IDF_VER);

    uint32_t flash_size = 0;
    if (esp_flash_get_size(NULL, &flash_size) == ESP_OK) {
        /* The BOM part is an ESP32-S3-WROOM-1-N8: 8 MB of flash. A module that
         * reports less is either the wrong variant or a bad SPI connection
         * inside the module, and both look identical from software. */
        selftest_report_add(r, "flash.size",
                            flash_size >= 8u * 1024 * 1024 ? SELFTEST_PASS : SELFTEST_FAIL,
                            "%u MB (expect >= 8 MB for the -N8 module)",
                            (unsigned)(flash_size / (1024 * 1024)));
    } else {
        selftest_report_add(r, "flash.size", SELFTEST_FAIL, "could not read flash size");
    }

    uint8_t mac[6] = {0};
    if (esp_read_mac(mac, ESP_MAC_ETH) == ESP_OK) {
        const bool blank = (mac[0] | mac[1] | mac[2] | mac[3] | mac[4] | mac[5]) == 0;
        const bool broadcast = (mac[0] & mac[1] & mac[2] & mac[3] & mac[4] & mac[5]) == 0xFF;
        selftest_report_add(r, "mac.eth",
                            (blank || broadcast) ? SELFTEST_FAIL : SELFTEST_PASS,
                            "%02X:%02X:%02X:%02X:%02X:%02X",
                            mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    } else {
        selftest_report_add(r, "mac.eth", SELFTEST_FAIL, "eFuse MAC unreadable");
    }

    selftest_report_add(r, "reset.reason", SELFTEST_INFO, "%s",
                        reset_reason_str(esp_reset_reason()));

    /* PD_PG is an open-drain output from the CH224K with no external pull-up
     * on this board, so it needs the S3's internal one. The ASSERTED LEVEL IS
     * NOT VERIFIED: record what a known-good board shows and make that the
     * limit in rev B of the test spec. */
    gpio_config_t pg = {
        .pin_bit_mask = 1ULL << BOARD_PD_PG_GPIO,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
    };
    if (gpio_config(&pg) == ESP_OK) {
        selftest_report_add(r, "pd.pg", SELFTEST_INFO, "GPIO%d reads %d (polarity unverified)",
                            BOARD_PD_PG_GPIO, gpio_get_level(BOARD_PD_PG_GPIO));
    } else {
        selftest_report_add(r, "pd.pg", SELFTEST_SKIP, "could not configure GPIO%d",
                            BOARD_PD_PG_GPIO);
    }
}

/* ------------------------------------------------------------------------ */
/* Ethernet: raw SPI, no esp_eth driver                                      */
/* ------------------------------------------------------------------------ */
/*
 * Deliberately NOT using esp_eth's W5500 driver. The driver reports "failed to
 * detect W5500" for a dozen different reasons and hides which one; a raw
 * transaction lets the report say what actually came back on MISO, which is
 * the difference between 0x00 (nothing driving) and 0xFF (stuck high) and
 * 0x04 (working). It also means this test still works if the driver changes.
 */
static esp_err_t w5500_xfer(spi_device_handle_t dev, uint16_t addr, uint8_t ctl,
                            const uint8_t *tx, uint8_t *rx, size_t len)
{
    uint8_t buf[3 + 4];
    if (len > 4) {
        return ESP_ERR_INVALID_SIZE;
    }
    buf[0] = (uint8_t)(addr >> 8);
    buf[1] = (uint8_t)(addr & 0xFF);
    buf[2] = ctl;
    memset(&buf[3], 0, len);
    if (tx) {
        memcpy(&buf[3], tx, len);
    }

    uint8_t in[sizeof(buf)];
    memset(in, 0, sizeof(in));

    spi_transaction_t t = {
        .length = (3 + len) * 8,
        .rxlength = (3 + len) * 8,
        .tx_buffer = buf,
        .rx_buffer = in,
    };
    const esp_err_t err = spi_device_polling_transmit(dev, &t);
    if (err == ESP_OK && rx) {
        memcpy(rx, &in[3], len);
    }
    return err;
}

void selftest_eth(selftest_report_t *r)
{
    /* Hold the W5500 in reset briefly, then release. The datasheet asks for
     * 500 us low and ~1 ms before the first access; be generous. */
    gpio_config_t rst = {
        .pin_bit_mask = 1ULL << BOARD_ETH_RST_GPIO,
        .mode = GPIO_MODE_OUTPUT,
    };
    ESP_ERROR_CHECK(gpio_config(&rst));
    gpio_set_level(BOARD_ETH_RST_GPIO, 0);
    vTaskDelay(pdMS_TO_TICKS(5));
    gpio_set_level(BOARD_ETH_RST_GPIO, 1);
    vTaskDelay(pdMS_TO_TICKS(20));

    const spi_bus_config_t bus = {
        .mosi_io_num = BOARD_ETH_MOSI_GPIO,
        .miso_io_num = BOARD_ETH_MISO_GPIO,
        .sclk_io_num = BOARD_ETH_SCK_GPIO,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = 64,
    };
    esp_err_t err = spi_bus_initialize(BOARD_ETH_SPI_HOST, &bus, SPI_DMA_CH_AUTO);
    if (err != ESP_OK) {
        selftest_report_add(r, "eth.spi", SELFTEST_FAIL,
                            "spi_bus_initialize: %s", esp_err_to_name(err));
        return;
    }

    /* Run the self-test slower than the application does. If a board works at
     * 4 MHz and fails at 20 MHz, that is a signal-integrity finding worth
     * having, and it is only visible if the two speeds are separate tests. */
    const spi_device_interface_config_t devcfg = {
        .clock_speed_hz = 4 * 1000 * 1000,
        .mode = 0,
        .spics_io_num = BOARD_ETH_CS_GPIO,
        .queue_size = 1,
    };
    spi_device_handle_t dev = NULL;
    err = spi_bus_add_device(BOARD_ETH_SPI_HOST, &devcfg, &dev);
    if (err != ESP_OK) {
        selftest_report_add(r, "eth.spi", SELFTEST_FAIL,
                            "spi_bus_add_device: %s", esp_err_to_name(err));
        spi_bus_free(BOARD_ETH_SPI_HOST);
        return;
    }

    uint8_t version = 0;
    err = w5500_xfer(dev, W5500_REG_VERSIONR, W5500_CTL_READ, NULL, &version, 1);
    if (err != ESP_OK) {
        selftest_report_add(r, "eth.versionr", SELFTEST_FAIL,
                            "SPI transaction failed: %s", esp_err_to_name(err));
    } else if (version == W5500_VERSION_VALUE) {
        selftest_report_add(r, "eth.versionr", SELFTEST_PASS,
                            "0x%02X at 4 MHz - SPI, 3V3, 25 MHz crystal and reset all good",
                            version);
    } else {
        selftest_report_add(r, "eth.versionr", SELFTEST_FAIL,
                            "read 0x%02X, expected 0x04 (0x00 = MISO idle low, 0xFF = idle high)",
                            version);
    }

    /* A read alone only proves MISO. Writing a register and reading it back
     * proves MOSI too, which is the difference between "the W5500 is there"
     * and "the W5500 can be configured". RTR is chosen because it is 16-bit,
     * has a documented reset value, and affects nothing until a socket opens.
     */
    if (version == W5500_VERSION_VALUE) {
        const uint8_t pattern[2] = {0x5A, 0xA5};
        uint8_t back[2] = {0, 0};
        const uint8_t restore[2] = {W5500_RTR_RESET >> 8, W5500_RTR_RESET & 0xFF};

        if (w5500_xfer(dev, W5500_REG_RTR, W5500_CTL_WRITE, pattern, NULL, 2) == ESP_OK &&
            w5500_xfer(dev, W5500_REG_RTR, W5500_CTL_READ, NULL, back, 2) == ESP_OK) {
            selftest_report_add(r, "eth.regwalk",
                                (back[0] == pattern[0] && back[1] == pattern[1])
                                    ? SELFTEST_PASS : SELFTEST_FAIL,
                                "wrote 5AA5 to RTR, read %02X%02X", back[0], back[1]);
        } else {
            selftest_report_add(r, "eth.regwalk", SELFTEST_FAIL, "RTR access failed");
        }
        w5500_xfer(dev, W5500_REG_RTR, W5500_CTL_WRITE, restore, NULL, 2);

        /* Repeat the version read at the speed the application will use. */
        spi_device_handle_t fast = NULL;
        const spi_device_interface_config_t fastcfg = {
            .clock_speed_hz = BOARD_ETH_SPI_CLOCK_MHZ * 1000 * 1000,
            .mode = 0,
            .spics_io_num = BOARD_ETH_CS_GPIO,
            .queue_size = 1,
        };
        if (spi_bus_add_device(BOARD_ETH_SPI_HOST, &fastcfg, &fast) == ESP_OK) {
            uint8_t v2 = 0;
            w5500_xfer(fast, W5500_REG_VERSIONR, W5500_CTL_READ, NULL, &v2, 1);
            selftest_report_add(r, "eth.versionr.fast",
                                v2 == W5500_VERSION_VALUE ? SELFTEST_PASS : SELFTEST_FAIL,
                                "0x%02X at %d MHz", v2, BOARD_ETH_SPI_CLOCK_MHZ);
            spi_bus_remove_device(fast);
        }
    }

    spi_bus_remove_device(dev);
    spi_bus_free(BOARD_ETH_SPI_HOST);
}

/* ------------------------------------------------------------------------ */
/* CAN loopback through the real transceiver                                 */
/* ------------------------------------------------------------------------ */
void selftest_can_loopback(selftest_report_t *r)
{
    twai_general_config_t g =
        TWAI_GENERAL_CONFIG_DEFAULT((gpio_num_t)BOARD_CAN_TX_GPIO,
                                    (gpio_num_t)BOARD_CAN_RX_GPIO,
                                    TWAI_MODE_NO_ACK);
    g.rx_queue_len = 4;
    g.tx_queue_len = 4;
    const twai_timing_config_t t = TWAI_TIMING_CONFIG_100KBITS();
    const twai_filter_config_t f = TWAI_FILTER_CONFIG_ACCEPT_ALL();

    esp_err_t err = twai_driver_install(&g, &t, &f);
    if (err != ESP_OK) {
        selftest_report_add(r, "can.loopback", SELFTEST_FAIL,
                            "twai_driver_install: %s", esp_err_to_name(err));
        return;
    }
    if ((err = twai_start()) != ESP_OK) {
        selftest_report_add(r, "can.loopback", SELFTEST_FAIL,
                            "twai_start: %s", esp_err_to_name(err));
        twai_driver_uninstall();
        return;
    }

    /* 0x123 is arbitrary, but the payload is not: alternating bits force real
     * transitions on the bus, so a stuck-dominant or stuck-recessive
     * transceiver cannot pass by accident. */
    twai_message_t tx = {
        .identifier = 0x123,
        .data_length_code = 8,
        .flags = TWAI_MSG_FLAG_SELF,
        .data = {0x55, 0xAA, 0x00, 0xFF, 0x0F, 0xF0, 0x5A, 0xA5},
    };

    bool ok = false;
    const char *why = "no frame returned";
    if ((err = twai_transmit(&tx, pdMS_TO_TICKS(200))) != ESP_OK) {
        why = "transmit queue timed out";
    } else {
        twai_message_t rx;
        if (twai_receive(&rx, pdMS_TO_TICKS(200)) != ESP_OK) {
            why = "nothing received within 200 ms";
        } else if (rx.identifier != tx.identifier) {
            why = "identifier mismatch";
        } else if (rx.data_length_code != tx.data_length_code ||
                   memcmp(rx.data, tx.data, tx.data_length_code) != 0) {
            why = "payload mismatch - suspect bit timing or a marginal transceiver";
        } else {
            ok = true;
        }
    }

    twai_status_info_t st;
    twai_get_status_info(&st);
    twai_stop();
    twai_driver_uninstall();

    if (ok) {
        selftest_report_add(r, "can.loopback", SELFTEST_PASS,
                            "8-byte frame round-tripped through the ADM3053 (tx_err=%u rx_err=%u)",
                            (unsigned)st.tx_error_counter, (unsigned)st.rx_error_counter);
    } else {
        /* The most likely cause on a first board is SW201 left UNTERMINATED:
         * with no 120 ohm load the bus does not settle within a bit time. Say
         * so, because otherwise this reads as a dead transceiver. */
        selftest_report_add(r, "can.loopback", SELFTEST_FAIL,
                            "%s (tx_err=%u rx_err=%u) - check SW201 is TERMINATED",
                            why, (unsigned)st.tx_error_counter,
                            (unsigned)st.rx_error_counter);
    }
}

/* ------------------------------------------------------------------------ */
/* LEDs                                                                      */
/* ------------------------------------------------------------------------ */
/*
 * This cannot verify anything on its own - no light sensor - so it reports
 * INFO and drives a pattern a human can check. It exists because the pin
 * mapping and the drive polarity are the parts most likely to be wrong, and a
 * board where all three LEDs are inverted looks alive and reports every state
 * backwards.
 */
void selftest_leds(selftest_report_t *r)
{
    const int pins[3] = {BOARD_LED_LAN_GPIO, BOARD_LED_ERR_GPIO, BOARD_LED_CAN_GPIO};
    const char *names[3] = {"D301 LAN", "D302 ERR", "D303 CAN"};

    gpio_config_t cfg = {
        .pin_bit_mask = (1ULL << pins[0]) | (1ULL << pins[1]) | (1ULL << pins[2]),
        .mode = GPIO_MODE_OUTPUT,
    };
    ESP_ERROR_CHECK(gpio_config(&cfg));

    for (int i = 0; i < 3; i++) {
        for (int j = 0; j < 3; j++) {
            gpio_set_level(pins[j], i == j ? BOARD_LED_ACTIVE_LEVEL
                                           : !BOARD_LED_ACTIVE_LEVEL);
        }
        ESP_LOGI(TAG, "LED walk: %s should be the ONLY one lit", names[i]);
        vTaskDelay(pdMS_TO_TICKS(700));
    }
    for (int j = 0; j < 3; j++) {
        gpio_set_level(pins[j], !BOARD_LED_ACTIVE_LEVEL);
    }

    selftest_report_add(r, "led.walk", SELFTEST_INFO,
                        "GPIO%d/%d/%d driven, active level %d - confirm by eye",
                        pins[0], pins[1], pins[2], BOARD_LED_ACTIVE_LEVEL);
}

/* ------------------------------------------------------------------------ */
void selftest_run_all(selftest_report_t *r)
{
    selftest_post(r);
    selftest_eth(r);
    selftest_can_loopback(r);
    selftest_leds(r);
}
