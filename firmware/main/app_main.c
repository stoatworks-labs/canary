/*
 * dbCANary — application entry point.
 *
 * An open IP-to-CAN converter compatible with the d&b R70 Ethernet-to-CAN
 * interface's protocol, so R1 can reach dbCAN amplifiers (D6, D12, E-PAC) over a network.
 *
 * Bring-up order:
 *   1. NVS
 *   2. Network (WiFi STA today; wired PHY + PoE once hardware exists, D4/D7)
 *   3. Bridge: dbCAN at 100 kbit/s, UDP 33333 discovery, TCP 30000 data socket
 *
 * The protocol this implements is documented in docs/PROTOCOL.md and was proven
 * end to end against R1 V3.46 by tools/r70_emu.py — that Python emulator is the
 * reference; this is the port. The two pure components (rmbcp, r70_ddt) carry
 * host tests that share vectors with the Python side; run each component's
 * test/run_tests.sh, or ../run_tests.sh for everything.
 *
 * This builds against ESP-IDF v5.5, but has NOT been run on hardware.
 */
#include <stdbool.h>

#include "esp_log.h"
#include "esp_mac.h"
#include "nvs_flash.h"
#include "esp_ota_ops.h"
#include "diag.h"

#include "bridge.h"
#include "board.h"
#include "led.h"
#include "selftest.h"
#include "status.h"
#include "net.h"
#include "usbnet.h"
#include "webui.h"
#include "config_store.h"

static const char *TAG = "dbcanary";

/* Build the bench test firmware instead of the product:
 *
 *     idf.py build -DDBCANARY_SELFTEST=1
 *
 * That image runs the full self-test and then a command console, and does NOT
 * start the bridge. Keeping it a separate image rather than a runtime mode is
 * deliberate: a shipping unit on a show network should have no command
 * interface at all, and the self-test claims SPI2 and TWAI directly, which
 * cannot coexist with the drivers the bridge installs.
 *
 * The product image still runs selftest_post() - identity only, no peripheral
 * claims - so the log says which board this is. */
#ifndef DBCANARY_SELFTEST
#define DBCANARY_SELFTEST 0
#endif

/* TODO: move to NVS/provisioning once the hardware exists. */
#ifndef DBCANARY_WIFI_SSID
#define DBCANARY_WIFI_SSID "set-me"
#endif
#ifndef DBCANARY_WIFI_PASS
#define DBCANARY_WIFI_PASS "set-me"
#endif

/* CAN pins come from board.h - the rev A board fixes them in hardware
 * (ADM3053 on GPIO4/5). Nothing here should hard-code a pin number. */

/* Set DBCANARY_USE_WIFI to build the devkit path instead of wired Ethernet.
 * The rev A board has no Wi-Fi in its signal path: the LAN jack is fed by the
 * W5500 on SPI2, and the S3 has no internal EMAC. */
#ifndef DBCANARY_USE_WIFI
#define DBCANARY_USE_WIFI 0
#endif

void app_main(void)
{
    bool have_usb = false;          /* set once the USB network device is up */
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);

    /* NVS first, then diagnostics: diag keeps its crash summary in NVS, so it
     * cannot come up before NVS does. Everything after this point lands in the
     * in-RAM log ring, which on a headless converter is the only way to see a
     * failed bring-up at all. */
    ESP_ERROR_CHECK(diag_init());

    /* Settings before anything that uses them. cfg_load() cannot fail into an
     * unusable state by design - corrupt or impossible stored values yield the
     * factory ones and say so - so there is nothing here to check. */
    cfg_t cfg;
    cfg_load(&cfg);

#if DBCANARY_SELFTEST
    /* Test image. Nothing else may run: the tests below drive SPI2 and TWAI
     * directly and must be the only owner of both. */
    ESP_LOGW(TAG, "SELF-TEST BUILD - the bridge is not started");
    {
        selftest_report_t report;
        selftest_report_init(&report);
        selftest_run_all(&report);
        selftest_report_print(&report);
    }
    ESP_ERROR_CHECK(selftest_console_start());
    return;
#else
    /* Product image: identity only. This never claims a peripheral, so it
     * cannot change how the bridge behaves. */
    {
        selftest_report_t report;
        selftest_report_init(&report);
        selftest_post(&report);
        selftest_report_print(&report);
    }

    /* Before the network: the lamp test is the earliest visual proof that the
     * MCU booted and the scheduler is running, and net_start_eth() can block
     * for 30 s waiting on DHCP. Without this the board looks dead for half a
     * minute on a bench. */
    ESP_ERROR_CHECK(led_start());

    /* The USB network device, when this image was built with it.
     *
     * BEFORE the wired bring-up, not after, for two reasons. The first is
     * plain: net_start_eth() blocks for up to 30 s waiting for an address, and
     * a laptop plugged into the USB-C port in that window would sit looking at
     * a device that has not enumerated - USB hosts complain, and the operator
     * sees nothing at all. The second is that usbnet_start() returns as soon
     * as the stack is up; it never waits for a host, so it costs the wired
     * path nothing to go first.
     *
     * esp_netif_init() and the default event loop end up owned by whichever of
     * the two runs first; both make them idempotently.
     *
     * ESP_ERR_NOT_SUPPORTED means the image simply has no USB interface, which
     * is the default build and not a fault. Anything else is: say so and carry
     * on, because the wired path is unaffected by a USB stack that would not
     * start, and a converter that refused to bridge amplifiers because of a
     * USB feature would be a worse failure than the one being reported. */
    {
        const usbnet_config_t usb_cfg = USBNET_DEFAULT_CONFIG();
        const esp_err_t usb_err = usbnet_start(&usb_cfg);
        if (usb_err == ESP_ERR_NOT_SUPPORTED) {
            ESP_LOGD(TAG, "no USB network device in this build");
        } else if (usb_err != ESP_OK) {
            ESP_LOGE(TAG, "USB network device failed to start: %s - the wired "
                          "side is unaffected", esp_err_to_name(usb_err));
        } else {
            /* "this image has a USB path and it is coming" - the TinyUSB
             * install is deferred behind the start delay, so whether it
             * succeeds is not known yet and deliberately is not waited for.
             * What this flag decides is only how serious a wired failure is,
             * and an image with a USB path can survive one. */
            have_usb = true;
        }
    }

#if DBCANARY_USE_WIFI
    ESP_LOGW(TAG, "Wi-Fi build - devkit only, not the rev A board");
    ESP_ERROR_CHECK(net_start_sta(DBCANARY_WIFI_SSID, DBCANARY_WIFI_PASS));
#else
    const net_ipv4_static_t static_ipv4 = {
        .ip = cfg.eth_ip, .netmask = cfg.eth_netmask, .gw = cfg.eth_gw,
    };
    err = net_start_eth(cfg.eth_mode == CFG_IPV4_STATIC ? &static_ipv4 : NULL);
    if (err == ESP_ERR_TIMEOUT) {
        /* Not "no DHCP" any more: with AUTOIP on, a rig with no DHCP server
         * self-assigns a link-local address inside this window. Getting here
         * means no usable link, so nothing has an address to advertise and R1
         * cannot reach us - say so loudly rather than sitting there looking
         * alive. The bridge still starts: the link may come back, and
         * bridge_local_ip() reads the address per discovery answer. */
        ESP_LOGE(TAG, "no address and no link; check the LAN cable - "
                      "R1 will not be able to reach us until this clears");
    } else if (err != ESP_OK && have_usb) {
        /* A hard failure bringing up the W5500 - not merely no link. It used
         * to be fatal, and ESP_ERROR_CHECK still makes it fatal on an image
         * with no other way in: a converter that cannot reach the network it
         * exists to serve should say so by rebooting, loudly, rather than sit
         * on a bench looking healthy.
         *
         * With a USB interface up that reasoning inverts. The unit IS
         * reachable, R1 can drive the amplifiers over the cable in front of
         * the operator, and abort()ing would take away the one path left - and
         * with it any chance of reading why the wired side failed. So carry
         * on, and make the log say plainly which half is broken. */
        ESP_LOGE(TAG, "wired Ethernet failed to start: %s - continuing on USB "
                      "only. The LAN jack will not work until this is fixed.",
                 esp_err_to_name(err));
    } else {
        ESP_ERROR_CHECK(err);
    }
#endif

    /* These were compile-time constants until components/config existed. The
     * defaults are unchanged - "db-70", 30000, four sockets, the R70's own -
     * so a unit that has never been configured behaves exactly as it always
     * did. bridge_start() copies the host name: `cfg` is on this task's
     * stack, which is freed when app_main returns. */
    bridge_config_t bridge_cfg = {
        .hostname = cfg.hostname,
        .base_port = cfg.base_port,
        .socket_count = cfg.socket_count,
        .can_tx_gpio = BOARD_CAN_TX_GPIO,
        .can_rx_gpio = BOARD_CAN_RX_GPIO,
    };
    /* R1 never validates the OUI, so our own address is fine. Using the ESP32's
     * factory MAC keeps every unit unique without buying an OUI. */
#if DBCANARY_USE_WIFI
    ESP_ERROR_CHECK(esp_read_mac(bridge_cfg.mac, ESP_MAC_WIFI_STA));
#else
    /* Must match the MAC actually programmed into the W5500, or R1's interface
     * list and the ARP table disagree about who we are. */
    ESP_ERROR_CHECK(esp_read_mac(bridge_cfg.mac, ESP_MAC_ETH));
#endif

    ESP_ERROR_CHECK(bridge_start(&bridge_cfg));
    ESP_ERROR_CHECK(status_start());

    /* The configuration UI, on the USB link and nowhere else. It never listens
     * until a host attaches, so this costs a watcher task and no open port.
     * ESP_ERR_NOT_SUPPORTED just means this image has no USB network device. */
    {
        const esp_err_t ui_err = webui_start();
        if (ui_err != ESP_OK && ui_err != ESP_ERR_NOT_SUPPORTED) {
            ESP_LOGE(TAG, "configuration UI did not start: %s",
                     esp_err_to_name(ui_err));
        }
    }

    /* THE LAST THING, and only once everything above has come up. With
     * CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE a freshly flashed OTA image is on
     * probation: if it reboots without reaching this call the bootloader
     * reverts to the previous one. Reaching it means the bridge is listening
     * and the LEDs are running, which is the definition of a good image worth
     * keeping. Putting it any earlier would mark an image valid that had not
     * yet proved it could serve anything. */
    {
        const esp_err_t ota_err = esp_ota_mark_app_valid_cancel_rollback();
        if (ota_err == ESP_OK) {
            ESP_LOGI(TAG, "this image is marked valid; no rollback pending");
        } else if (ota_err != ESP_ERR_NOT_SUPPORTED) {
            ESP_LOGW(TAG, "could not mark the image valid: %s",
                     esp_err_to_name(ota_err));
        }
    }
    ESP_LOGI(TAG, "dbCANary up — in R1: scan, go Offline, tick the interface, "
                  "then back Online");
#endif /* DBCANARY_SELFTEST */
}
