/*
 * CANary bridge — R1 over Ethernet <-> dbCAN.
 *
 * Owns the UDP 33333 discovery responder, the TCP data socket speaking the RM
 * Byte Command Protocol, and the forwarding between that socket and the CAN
 * controller. See docs/PROTOCOL.md.
 */
#ifndef BRIDGE_H
#define BRIDGE_H

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

typedef struct {
    const char *hostname;   /* shown in R1's interface list; default "CANary" */
    uint8_t mac[6];         /* advertised in discovery; R1 never checks the OUI */
    uint16_t base_port;     /* socket 1, R70 default 30000 */
    uint8_t socket_count;   /* 0 -> 4, the number a real R70 offers */
    int can_tx_gpio;
    int can_rx_gpio;
} bridge_config_t;

/* Bring up the bridge: start CAN, then the discovery responder and the TCP
 * data socket, each on its own task. Returns once they are started, not once
 * R1 has connected — bridge_client_connected() reports that.
 *
 * `cfg` is copied, so the caller need not keep it alive.
 *
 * A socket_count of 0, or one above the R70's maximum, is silently replaced
 * with the four a real R70 offers rather than rejected: R1 leaves its socket
 * column read-only below two, so a low value looks like a broken device rather
 * than a configured one. Only socket 1 ever carries data; the rest exist so R1
 * sees a device with more than one.
 *
 * There is NO AUTHENTICATION on either socket. Anything that can reach them can
 * inject arbitrary frames onto the amplifier bus. A real R70 is the same, and
 * belongs on the same kind of locked-down show network. */
esp_err_t bridge_start(const bridge_config_t *cfg);

/* The IPv4 address, host byte order, to advertise to a peer at `peer` (also
 * host byte order; 0 means "no particular peer").
 *
 * The discovery answer must carry this: R1 ignores the UDP sender and connects
 * to whatever the record says. It takes a peer because a unit can hold more
 * than one address - a wired lease and a USB-NCM link - and only one of them
 * is reachable from any given R1. Provided by the net component on the target
 * and by hostsim off it. */
uint32_t bridge_local_ip_for(uint32_t peer);

/* True while R1 holds the TCP session open. Exposed for status indication -
 * the bridge already tracks it internally to decide whether to forward CAN
 * frames upstream. */
bool bridge_client_connected(void);

#endif /* BRIDGE_H */
