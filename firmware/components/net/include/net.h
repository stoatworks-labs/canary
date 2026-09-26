/*
 * Network bring-up.
 *
 * TWO paths, deliberately:
 *
 *   net_start_eth()  wired Ethernet over the W5500 on SPI2. This is what the
 *                    rev A board has - the ESP32-S3 has no internal EMAC, so
 *                    there is no RMII option, and the etherCON LAN jack is fed
 *                    entirely through the W5500. Pins come from board.h.
 *
 *   net_start_sta()  Wi-Fi STA. Kept only so the bridge is testable on a plain
 *                    ESP32-S3 devkit plus a CAN transceiver, with no dbCANary
 *                    hardware. NOT the shipping path: the rev A board's antenna
 *                    keepout exists for the module but Wi-Fi is not part of the
 *                    product's signal path.
 */
#ifndef NET_H
#define NET_H

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

/* Bring up wired Ethernet and wait for an IPv4 address.
 *
 * DHCP first; if no server answers, lwip's AUTOIP self-assigns a link-local
 * 169.254.x.x (RFC 3927) and that address is used instead - see the AUTOIP
 * block in sdkconfig.defaults. The two cooperate, so a lease that turns up late
 * replaces the link-local address; net_local_ip() and the discovery answer
 * follow it.
 *
 * Returns ESP_ERR_TIMEOUT if neither has produced an address within 30 s, which
 * now means no usable link rather than no DHCP. The caller should carry on
 * anyway: the address is picked up whenever it arrives. */
/* A static IPv4 configuration, host byte order. gw of 0 means no gateway,
 * which is the normal case on a show network. */
typedef struct {
    uint32_t ip;
    uint32_t netmask;
    uint32_t gw;
} net_ipv4_static_t;

/* `ipv4` NULL asks for DHCP (with the link-local fallback described above),
 * which is what every unit did before there were settings. Non-NULL stops the
 * DHCP client before the interface starts and uses the address given - so
 * AUTOIP never runs either, and the address is exactly the one configured. */
esp_err_t net_start_eth(const net_ipv4_static_t *ipv4);

/* Join a Wi-Fi network and block until we have an IPv4 address. Devkit only. */
esp_err_t net_start_sta(const char *ssid, const char *password);

/* Current IPv4 address in host byte order, 0 if not up yet. */
uint32_t net_local_ip(void);

/* True when the address we hold is a self-assigned link-local one (169.254/16)
 * rather than a DHCP lease - i.e. nothing on this network is serving DHCP. */
bool net_ip_is_link_local(void);

/* Physical link state. On Wi-Fi this tracks association. */
bool net_link_up(void);

#endif /* NET_H */
