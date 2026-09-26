/*
 * Maps system state onto the three status LEDs.
 *
 * This lives in main/ rather than in components/led/ on purpose. The LED driver
 * is deliberately dumb and depends on nothing; main/ is the layer already
 * allowed to see net, dbcan and bridge, so the mapping belongs here. That keeps
 * the dependency arrow pointing one way.
 *
 * WHAT THE LEDS MEAN
 *
 *   D301 LAN (green)   off        nothing to reach us on
 *                      4 Hz       a link, but no address yet
 *                      heartbeat  USB host attached, but it has taken no
 *                                 address of its own (and Ethernet has none)
 *                      1 Hz       we are addressable, waiting for R1
 *                      solid      R1 connected and the session is open
 *
 *   D303 CAN (green)   off        TWAI not running
 *                      heartbeat  bus up, idle
 *                      flicker    bus traffic (one blip per busy sample)
 *
 *   D302 ERR (red)     off        nothing wrong
 *                      1 blink    no link at all, on either interface
 *                      2 blinks   a link, but no address
 *                      3 blinks   CAN bus-off
 *                      4 blinks   CAN stopped / never started
 *
 * D301 IS A REACHABILITY LAMP, NOT AN ETHERNET LAMP. It is silkscreened LAN
 * because when the board was drawn the LAN jack was the only way in; since
 * components/usbnet there can be a USB host as well, and the question the lamp
 * answers - can R1 get to us - is the same either way. A unit on a bench with
 * no LAN cable and a laptop on USB is working, and must not sit there blinking
 * a fault code at an operator who can see it is working.
 *
 * The one state that IS worth its own pattern is a USB host that has attached
 * but not configured itself: macOS and Windows both fall back to a self-
 * assigned 169.254 address when a DHCP offer does not arrive, and a host that
 * has done that will never reach us however healthy we are. From this end it
 * looks identical to a working link, which is exactly why it gets the
 * heartbeat rather than being folded into "addressable". On a board whose
 * J301 is a DNP that pattern may be the only thing telling you which half
 * failed - see docs/USB-NIC.md.
 *
 * The progression on LAN is deliberately faster-when-worse, so "still settling"
 * looks urgent and "ready" looks calm. Fault codes are blink COUNTS because a
 * count is readable across a dark stage in a way a colour or a duty cycle is
 * not.
 *
 * ERR shows only the most significant fault. Ethernet outranks CAN: without an
 * address R1 cannot reach us at all, so the CAN state is moot.
 *
 * An address is an address: these do not distinguish a DHCP lease from the
 * link-local one AUTOIP claims when no server answers, because a converter on
 * either is equally reachable by an R1 on the same network. The boot log names
 * which one is held.
 */
#include "status.h"

#include "dbcan.h"
#include "bridge.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "led.h"
#include "net.h"
#include "usbnet.h"

static const char *TAG = "status";

#define POLL_MS 100

/* usbnet_host_ip() walks the DHCP server's lease table, which is more work
 * than the rest of this loop put together and cannot change faster than a
 * lease is granted. Once per second is plenty. */
#define HOST_IP_EVERY (1000 / POLL_MS)

static void status_task(void *arg)
{
    (void)arg;
    bool logged_ready = false;
    bool logged_usb = false;
    int host_ip_countdown = 0;
    bool usb_host_addressed = false;

    for (;;) {
        const bool eth_link = net_link_up();
        const bool eth_ip = net_local_ip() != 0;
        const bool r1 = bridge_client_connected();
        const dbcan_bus_state_t bus = dbcan_bus_state();

        /* On a build without usbnet these are compile-time false and every
         * expression below collapses to exactly what it was before. */
        const bool usb_link = usbnet_link_up();
        if (!usb_link) {
            usb_host_addressed = false;
            host_ip_countdown = 0;
        } else if (!usb_host_addressed && --host_ip_countdown <= 0) {
            usb_host_addressed = usbnet_host_ip() != 0;
            host_ip_countdown = HOST_IP_EVERY;
        }

        /* Either interface can carry R1, so these are the questions the lamps
         * actually answer. The USB address is static: once the link is up we
         * are addressable on it, whatever the host has done about itself. */
        const bool any_link = eth_link || usb_link;
        const bool any_addr = eth_ip || usb_link;

        /* --- LAN / reachability ---------------------------------------- */
        if (r1) {
            led_set(LED_LAN, LED_ON);
        } else if (!any_link) {
            led_set(LED_LAN, LED_OFF);
        } else if (!any_addr) {
            led_set(LED_LAN, LED_BLINK_FAST);
        } else if (usb_link && !usb_host_addressed && !eth_ip) {
            /* We are ready and the host is not. Nothing we can do about it
             * from here, but it is the difference between "did not enumerate"
             * and "enumerated and then did not ask for a lease". */
            led_set(LED_LAN, LED_HEARTBEAT);
        } else {
            led_set(LED_LAN, LED_BLINK_SLOW);
        }

        if (usb_link && !logged_usb) {
            ESP_LOGI(TAG, "USB host attached");
            logged_usb = true;
        } else if (!usb_link && logged_usb) {
            ESP_LOGW(TAG, "USB host gone");
            logged_usb = false;
        }

        /* --- CAN ------------------------------------------------------- */
        if (bus == DBCAN_BUS_RUNNING) {
            led_set(LED_CAN, LED_HEARTBEAT);
            /* dbcan_busload() is messages seen in the last interval, which is
             * already what RMBCP 0x47 reports - so activity indication costs
             * nothing extra. */
            if (dbcan_busload() > 0) {
                led_blip(LED_CAN);
            }
        } else {
            led_set(LED_CAN, LED_OFF);
        }

        /* --- ERR: most significant fault only -------------------------- */
        int fault = LED_FAULT_NONE;
        if (!any_link) {
            fault = LED_FAULT_NO_LINK;
        } else if (!any_addr) {
            fault = LED_FAULT_NO_IP;
        } else if (bus == DBCAN_BUS_BUS_OFF) {
            fault = LED_FAULT_CAN_BUS_OFF;
        } else if (bus == DBCAN_BUS_STOPPED) {
            fault = LED_FAULT_CAN_STOPPED;
        }
        led_fault(fault);

        if (fault == LED_FAULT_NONE && !logged_ready) {
            /* "address held" covers a DHCP lease and a self-assigned
             * link-local one alike - the LEDs do not distinguish them, because
             * either one is a working converter. The boot log says which. */
            ESP_LOGI(TAG, "all indicators nominal: link up, %s, CAN running",
                     eth_ip ? (net_ip_is_link_local() ? "link-local address held"
                                                      : "DHCP address held")
                            : "reachable over USB only");
            logged_ready = true;
        } else if (fault != LED_FAULT_NONE) {
            logged_ready = false;
        }

        vTaskDelay(pdMS_TO_TICKS(POLL_MS));
    }
}

esp_err_t status_start(void)
{
    if (xTaskCreate(status_task, "status", 3072, NULL, 2, NULL) != pdPASS) {
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}
