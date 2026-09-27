/*
 * Bench console for the test build.
 *
 * A line-oriented command set that a person can type and a script can drive.
 * Two decisions matter for the script case:
 *
 *  - linenoise is forced into DUMB MODE. In normal mode it probes the terminal
 *    with escape sequences and rewrites the line as you type; a program on the
 *    other end sees that as garbage interleaved with its own echo. Dumb mode
 *    makes the stream exactly "prompt, echo, output", which tools/board_test.py
 *    can parse.
 *
 *  - Every command prints a terminator line. Without one, a reader cannot tell
 *    "still working" from "finished with no output", and ends up guessing with
 *    a timeout.
 *
 * The console exists only in the test build. The shipping firmware has no
 * command interface at all, which is the right default for a box that sits on
 * a show network.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "selftest.h"

#include "board.h"
#include "driver/gpio.h"
#include "driver/twai.h"
#include "esp_console.h"
#include "esp_log.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "linenoise/linenoise.h"

static const char *TAG = "console";

/* A CAN session started by the `can` command outlives that command, so it can
 * still be installed when `selftest` runs. selftest_can_loopback() installs
 * its own driver and would fail with "invalid state" - which reads as a dead
 * transceiver. Tear the session down first instead. */
static void can_session_stop(void);

/* Printed after every command so a script knows the reply is complete. */
#define DONE()  do { printf("OK\n"); fflush(stdout); } while (0)
#define FAILED(...) do { printf("ERR "); printf(__VA_ARGS__); printf("\n"); \
                         fflush(stdout); } while (0)

/* ------------------------------------------------------------------------ */
static int cmd_selftest(int argc, char **argv)
{
    selftest_report_t report;
    selftest_report_init(&report);

    can_session_stop();

    if (argc >= 2) {
        if (strcmp(argv[1], "eth") == 0) {
            selftest_eth(&report);
        } else if (strcmp(argv[1], "can") == 0) {
            selftest_can_loopback(&report);
        } else if (strcmp(argv[1], "led") == 0) {
            selftest_leds(&report);
        } else if (strcmp(argv[1], "post") == 0) {
            selftest_post(&report);
        } else {
            FAILED("unknown group %s (eth|can|led|post)", argv[1]);
            return 1;
        }
    } else {
        selftest_run_all(&report);
    }

    selftest_report_print(&report);

    static char json[2048];
    const size_t need = selftest_report_json(&report, json, sizeof(json));
    if (need >= sizeof(json)) {
        /* Say so rather than emitting truncated JSON that a parser will
         * reject with a confusing message. */
        FAILED("report JSON needs %u bytes, buffer is %u",
               (unsigned)need + 1, (unsigned)sizeof(json));
    } else {
        printf("JSON %s\n", json);
    }
    DONE();
    return 0;
}

static int cmd_id(int argc, char **argv)
{
    (void)argc; (void)argv;
    selftest_report_t report;
    selftest_report_init(&report);
    selftest_post(&report);
    selftest_report_print(&report);
    DONE();
    return 0;
}

/* ------------------------------------------------------------------------ */
static int led_index(const char *name)
{
    if (strcmp(name, "lan") == 0) { return 0; }
    if (strcmp(name, "err") == 0) { return 1; }
    if (strcmp(name, "can") == 0) { return 2; }
    return -1;
}

static int cmd_led(int argc, char **argv)
{
    const int pins[3] = {BOARD_LED_LAN_GPIO, BOARD_LED_ERR_GPIO, BOARD_LED_CAN_GPIO};

    if (argc != 3) {
        FAILED("usage: led <lan|err|can|all> <on|off>");
        return 1;
    }
    const bool on = strcmp(argv[2], "on") == 0;
    if (!on && strcmp(argv[2], "off") != 0) {
        FAILED("state must be on or off");
        return 1;
    }

    gpio_config_t cfg = {
        .pin_bit_mask = (1ULL << pins[0]) | (1ULL << pins[1]) | (1ULL << pins[2]),
        .mode = GPIO_MODE_OUTPUT,
    };
    gpio_config(&cfg);

    const int level = on ? BOARD_LED_ACTIVE_LEVEL : !BOARD_LED_ACTIVE_LEVEL;
    if (strcmp(argv[1], "all") == 0) {
        for (int i = 0; i < 3; i++) {
            gpio_set_level(pins[i], level);
        }
    } else {
        const int idx = led_index(argv[1]);
        if (idx < 0) {
            FAILED("unknown LED %s", argv[1]);
            return 1;
        }
        gpio_set_level(pins[idx], level);
    }
    printf("LED %s %s (GPIO drive level %d)\n", argv[1], argv[2], level);
    DONE();
    return 0;
}

/* ------------------------------------------------------------------------ */
/* A CAN session that outlives one command, so an operator can put the bus in
 * listen-only, go and plug something in, and come back to read the counters. */
static bool s_can_up;

static void can_session_stop(void)
{
    if (s_can_up) {
        twai_stop();
        twai_driver_uninstall();
        s_can_up = false;
    }
}

static int can_up(twai_mode_t mode, const char *what)
{
    can_session_stop();
    twai_general_config_t g =
        TWAI_GENERAL_CONFIG_DEFAULT((gpio_num_t)BOARD_CAN_TX_GPIO,
                                    (gpio_num_t)BOARD_CAN_RX_GPIO, mode);
    g.rx_queue_len = 32;
    g.tx_queue_len = 32;
    const twai_timing_config_t t = TWAI_TIMING_CONFIG_100KBITS();
    const twai_filter_config_t f = TWAI_FILTER_CONFIG_ACCEPT_ALL();

    esp_err_t err = twai_driver_install(&g, &t, &f);
    if (err == ESP_OK) {
        err = twai_start();
        if (err != ESP_OK) {
            twai_driver_uninstall();
        }
    }
    if (err != ESP_OK) {
        FAILED("%s: %s", what, esp_err_to_name(err));
        return 1;
    }
    s_can_up = true;
    printf("CAN %s at 100 kbit/s\n", what);
    DONE();
    return 0;
}

static int parse_hex_bytes(const char *s, uint8_t *out, int max)
{
    int n = 0;
    while (*s && n < max) {
        char pair[3] = {s[0], s[1], 0};
        if (!s[1]) {
            return -1;
        }
        char *end = NULL;
        const long v = strtol(pair, &end, 16);
        if (end != pair + 2) {
            return -1;
        }
        out[n++] = (uint8_t)v;
        s += 2;
    }
    return *s ? -1 : n;
}

static int cmd_can(int argc, char **argv)
{
    if (argc < 2) {
        FAILED("usage: can <normal|listen|selftest|off|tx|stats>");
        return 1;
    }
    if (strcmp(argv[1], "normal") == 0) {
        return can_up(TWAI_MODE_NORMAL, "normal");
    }
    if (strcmp(argv[1], "listen") == 0) {
        /* Listen-only never acknowledges, so it cannot disturb a live d&b bus.
         * This is the mode to use when probing customer equipment. */
        return can_up(TWAI_MODE_LISTEN_ONLY, "listen-only");
    }
    if (strcmp(argv[1], "selftest") == 0) {
        return can_up(TWAI_MODE_NO_ACK, "no-ack self-test");
    }
    if (strcmp(argv[1], "off") == 0) {
        can_session_stop();
        printf("CAN stopped\n");
        DONE();
        return 0;
    }
    if (!s_can_up) {
        FAILED("CAN is not started - run 'can normal' or 'can listen' first");
        return 1;
    }
    if (strcmp(argv[1], "stats") == 0) {
        twai_status_info_t st;
        twai_get_status_info(&st);
        printf("CAN state=%d rx_q=%u tx_q=%u tx_err=%u rx_err=%u "
               "tx_fail=%u rx_miss=%u bus_err=%u arb_lost=%u\n",
               (int)st.state, (unsigned)st.msgs_to_rx, (unsigned)st.msgs_to_tx,
               (unsigned)st.tx_error_counter, (unsigned)st.rx_error_counter,
               (unsigned)st.tx_failed_count, (unsigned)st.rx_missed_count,
               (unsigned)st.bus_error_count, (unsigned)st.arb_lost_count);
        DONE();
        return 0;
    }
    if (strcmp(argv[1], "tx") == 0) {
        if (argc < 3) {
            FAILED("usage: can tx <id-hex> [data-hex]");
            return 1;
        }
        twai_message_t msg = {0};
        msg.identifier = (uint32_t)strtoul(argv[2], NULL, 16);
        msg.extd = msg.identifier > 0x7FF;
        if (argc >= 4) {
            const int n = parse_hex_bytes(argv[3], msg.data, 8);
            if (n < 0) {
                FAILED("data must be an even number of hex digits, up to 16");
                return 1;
            }
            msg.data_length_code = (uint8_t)n;
        }
        const esp_err_t err = twai_transmit(&msg, pdMS_TO_TICKS(500));
        if (err != ESP_OK) {
            /* In NORMAL mode with nothing else on the bus this ALWAYS fails
             * eventually: a CAN transmitter needs another node to acknowledge.
             * That is the bus working correctly, not a fault. */
            FAILED("transmit: %s (in normal mode this needs a second node to ACK)",
                   esp_err_to_name(err));
            return 1;
        }
        printf("CAN tx id=%03lX dlc=%u\n", (unsigned long)msg.identifier,
               msg.data_length_code);
        DONE();
        return 0;
    }
    if (strcmp(argv[1], "rx") == 0) {
        const int ms = argc >= 3 ? atoi(argv[2]) : 2000;
        const TickType_t end = xTaskGetTickCount() + pdMS_TO_TICKS(ms);
        int n = 0;
        while (xTaskGetTickCount() < end) {
            twai_message_t msg;
            if (twai_receive(&msg, pdMS_TO_TICKS(50)) != ESP_OK) {
                continue;
            }
            printf("CAN rx id=%03lX dlc=%u data=", (unsigned long)msg.identifier,
                   msg.data_length_code);
            for (int i = 0; i < msg.data_length_code; i++) {
                printf("%02X", msg.data[i]);
            }
            printf("\n");
            n++;
        }
        printf("CAN rx-window %d ms, %d frame(s)\n", ms, n);
        DONE();
        return 0;
    }
    FAILED("unknown subcommand %s", argv[1]);
    return 1;
}

/* ------------------------------------------------------------------------ */
static int cmd_reboot(int argc, char **argv)
{
    (void)argc; (void)argv;
    printf("rebooting\n");
    fflush(stdout);
    vTaskDelay(pdMS_TO_TICKS(100));
    esp_restart();
    return 0;
}

/* ------------------------------------------------------------------------ */
static void register_commands(void)
{
    const esp_console_cmd_t cmds[] = {
        {
            .command = "selftest",
            .help = "Run the board self-test. Optional group: eth | can | led | post",
            .func = &cmd_selftest,
        },
        {
            .command = "id",
            .help = "Chip, flash, MAC and reset reason",
            .func = &cmd_id,
        },
        {
            .command = "led",
            .help = "led <lan|err|can|all> <on|off>",
            .func = &cmd_led,
        },
        {
            .command = "can",
            .help = "can normal|listen|selftest|off | can tx <id> [data] | can rx [ms] | can stats",
            .func = &cmd_can,
        },
        {
            .command = "reboot",
            .help = "Restart the board",
            .func = &cmd_reboot,
        },
    };
    for (size_t i = 0; i < sizeof(cmds) / sizeof(cmds[0]); i++) {
        ESP_ERROR_CHECK(esp_console_cmd_register(&cmds[i]));
    }
    ESP_ERROR_CHECK(esp_console_register_help_command());
}

esp_err_t selftest_console_start(void)
{
    esp_console_repl_t *repl = NULL;
    esp_console_repl_config_t cfg = ESP_CONSOLE_REPL_CONFIG_DEFAULT();
    cfg.prompt = "canary> ";
    cfg.max_cmdline_length = 128;
    /* The IDF default is 4096 bytes, and `selftest` runs with a
     * selftest_report_t (~2 KB) on THIS task's stack plus the SPI and TWAI
     * driver frames under it. On the first rev A board that overflowed the
     * stack straight past the canary into the heap and the scheduler fell over
     * in prvSelectHighestPriorityTaskSMP with 0xa5a5a5a5 for a TCB pointer -
     * the boot-time run on the 6 KB main task passed, the console re-run
     * panicked. Size it like the main task, with headroom. */
    cfg.task_stack_size = 8192;

    esp_err_t err;
#if defined(CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG)
    esp_console_dev_usb_serial_jtag_config_t dev =
        ESP_CONSOLE_DEV_USB_SERIAL_JTAG_CONFIG_DEFAULT();
    err = esp_console_new_repl_usb_serial_jtag(&dev, &cfg, &repl);
#elif defined(CONFIG_ESP_CONSOLE_USB_CDC)
    esp_console_dev_usb_cdc_config_t dev = ESP_CONSOLE_DEV_CDC_CONFIG_DEFAULT();
    err = esp_console_new_repl_usb_cdc(&dev, &cfg, &repl);
#else
    esp_console_dev_uart_config_t dev = ESP_CONSOLE_DEV_UART_CONFIG_DEFAULT();
    err = esp_console_new_repl_uart(&dev, &cfg, &repl);
#endif
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "console init failed: %s", esp_err_to_name(err));
        return err;
    }

    register_commands();

    /* See the header comment: a script on the other end cannot cope with
     * linenoise's terminal probing and line rewriting. */
    linenoiseSetDumbMode(1);

    printf("\nCANARY-TEST-CONSOLE " SELFTEST_SCHEMA "\n"
           "Type 'help' for commands, 'selftest' to run everything.\n");
    fflush(stdout);

    return esp_console_start_repl(repl);
}
