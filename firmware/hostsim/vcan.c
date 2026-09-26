/*
 * A virtual dbCAN bus, so components/dbcan/dbcan.c can run unmodified on the
 * host with something on the other end of the wire.
 *
 * Every participant speaks UDP to a hub (tools/vcan_hub.py) that reflects each
 * datagram to all the OTHER participants — which is what a CAN bus looks like
 * from a node: everyone hears everyone, nobody hears themselves. SocketCAN's
 * vcan would be the obvious choice but is Linux-only, and this has to run on
 * the Mac the rest of the project is developed on.
 *
 * Wire format, 14 bytes fixed:
 *
 *     0..3   identifier, uint32 little-endian
 *     4      flags: bit0 extended, bit1 RTR
 *     5      DLC (0..8)
 *     6..13  data, unused bytes zero
 *
 * A datagram of any other length is a registration ping: it tells the hub a
 * peer exists without injecting traffic. tools/vcan.py is the Python side of
 * this format.
 *
 * NOT MODELLED: bit timing, arbitration, error counters, real bus-off. Those
 * are properties of silicon and a transceiver. twai_initiate_recovery() here
 * just returns to RUNNING, so a test can exercise the recovery *path* without
 * that being evidence the controller recovers.
 */
#include "driver/twai.h"

#include "esp_log.h"

#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

static const char *TAG = "vcan";

#define VCAN_FRAME_LEN 14
#define VCAN_DEFAULT_PORT 35000

static int                s_sock = -1;
static struct sockaddr_in s_hub;
static twai_state_t       s_state = TWAI_STATE_STOPPED;
static uint32_t           s_tx_count;
static uint32_t           s_rx_count;

static uint16_t hub_port(void)
{
    const char *env = getenv("DBCANARY_VCAN_PORT");
    const int   port = env ? atoi(env) : VCAN_DEFAULT_PORT;
    return (port > 0 && port < 65536) ? (uint16_t)port : VCAN_DEFAULT_PORT;
}

esp_err_t twai_driver_install(const twai_general_config_t *g,
                              const twai_timing_config_t *t,
                              const twai_filter_config_t *f)
{
    (void)t;
    (void)f;

    s_sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (s_sock < 0) {
        ESP_LOGE(TAG, "socket: errno %d", errno);
        return ESP_FAIL;
    }

    memset(&s_hub, 0, sizeof(s_hub));
    s_hub.sin_family = AF_INET;
    s_hub.sin_port = htons(hub_port());
    s_hub.sin_addr.s_addr = htonl(INADDR_LOOPBACK);

    /* Bind an ephemeral local port so the hub has somewhere to reply to. */
    struct sockaddr_in local;
    memset(&local, 0, sizeof(local));
    local.sin_family = AF_INET;
    local.sin_port = 0;
    local.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (bind(s_sock, (struct sockaddr *)&local, sizeof(local)) < 0) {
        ESP_LOGE(TAG, "bind: errno %d", errno);
        close(s_sock);
        s_sock = -1;
        return ESP_FAIL;
    }

    ESP_LOGI(TAG, "virtual bus on UDP %u (TX=%d RX=%d ignored)", hub_port(),
             g->tx_io, g->rx_io);
    return ESP_OK;
}

esp_err_t twai_start(void)
{
    if (s_sock < 0) {
        return ESP_ERR_INVALID_STATE;
    }
    /* Register with the hub so we receive other nodes' traffic. */
    const uint8_t hello = 0;
    sendto(s_sock, &hello, sizeof(hello), 0, (struct sockaddr *)&s_hub,
           sizeof(s_hub));
    s_state = TWAI_STATE_RUNNING;
    return ESP_OK;
}

esp_err_t twai_stop(void)
{
    s_state = TWAI_STATE_STOPPED;
    return ESP_OK;
}

esp_err_t twai_driver_uninstall(void)
{
    if (s_sock >= 0) {
        close(s_sock);
        s_sock = -1;
    }
    s_state = TWAI_STATE_STOPPED;
    return ESP_OK;
}

esp_err_t twai_transmit(const twai_message_t *msg, TickType_t timeout)
{
    (void)timeout;
    if (s_sock < 0 || s_state != TWAI_STATE_RUNNING) {
        return ESP_ERR_INVALID_STATE;
    }

    uint8_t buf[VCAN_FRAME_LEN];
    memset(buf, 0, sizeof(buf));
    buf[0] = (uint8_t)(msg->identifier);
    buf[1] = (uint8_t)(msg->identifier >> 8);
    buf[2] = (uint8_t)(msg->identifier >> 16);
    buf[3] = (uint8_t)(msg->identifier >> 24);
    buf[4] = (uint8_t)((msg->extd ? 1u : 0u) | (msg->rtr ? 2u : 0u));
    buf[5] = msg->data_length_code > 8 ? 8 : msg->data_length_code;
    memcpy(&buf[6], msg->data, buf[5]);

    if (sendto(s_sock, buf, sizeof(buf), 0, (struct sockaddr *)&s_hub,
               sizeof(s_hub)) < 0) {
        return ESP_FAIL;
    }
    s_tx_count++;
    return ESP_OK;
}

esp_err_t twai_receive(twai_message_t *msg, TickType_t timeout)
{
    if (s_sock < 0 || s_state != TWAI_STATE_RUNNING) {
        return ESP_ERR_INVALID_STATE;
    }

    struct timeval tv = {
        .tv_sec = (time_t)(timeout / 1000u),
        .tv_usec = (suseconds_t)((timeout % 1000u) * 1000u),
    };
    setsockopt(s_sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

    uint8_t   buf[64];
    const ssize_t n = recv(s_sock, buf, sizeof(buf), 0);
    if (n != VCAN_FRAME_LEN) {
        return ESP_ERR_TIMEOUT; /* timeout, or a registration ping echoed back */
    }

    memset(msg, 0, sizeof(*msg));
    msg->identifier = (uint32_t)buf[0] | ((uint32_t)buf[1] << 8) |
                      ((uint32_t)buf[2] << 16) | ((uint32_t)buf[3] << 24);
    msg->extd = (buf[4] & 1u) != 0;
    msg->rtr = (buf[4] & 2u) != 0;
    msg->data_length_code = buf[5] > 8 ? 8 : buf[5];
    memcpy(msg->data, &buf[6], msg->data_length_code);
    s_rx_count++;
    return ESP_OK;
}

esp_err_t twai_get_status_info(twai_status_info_t *status)
{
    if (s_sock < 0) {
        return ESP_ERR_INVALID_STATE;
    }
    memset(status, 0, sizeof(*status));
    status->state = s_state;
    return ESP_OK;
}

esp_err_t twai_initiate_recovery(void)
{
    /* No real bus-off to recover from — see the header comment. */
    s_state = TWAI_STATE_RUNNING;
    return ESP_OK;
}
