/*
 * The bridge itself: R1 over Ethernet <-> dbCAN, plus the discovery responder.
 *
 * Mirrors tools/r70_emu.py, which is the version actually proven against R1
 * V3.46. Where this file makes a choice, docs/PROTOCOL.md §6 says why.
 */
#include "bridge.h"

#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lwip/inet.h"
#include "lwip/sockets.h"
#include "lwip/tcp.h"

#include "dbcan.h"
#include "r70_ddt.h"
#include "rmbcp.h"

static const char *TAG = "bridge";

#define DDT_BUF (R70_DDT_HEADER_LEN + R70_DDT_MAX_SOCKETS * R70_DDT_RECORD_LEN)

static bridge_config_t s_cfg;
/* s_cfg.hostname points here, never at the caller's string. app_main's settings
 * live on its stack, and ESP-IDF frees that stack when app_main returns - so
 * keeping the caller's pointer advertised whatever reused the memory next (on
 * the first USB bench session, a fragment of the web UI's JavaScript). */
static char s_hostname[R70_DDT_HOSTNAME_MAX + 1];
static int s_client = -1; /* the connected R1 socket, or -1 */

/* --- Discovery (UDP 33333) ------------------------------------------------ */

static void ddt_task(void *arg)
{
    (void)arg;
    const int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (sock < 0) {
        ESP_LOGE(TAG, "discovery socket: errno %d", errno);
        vTaskDelete(NULL);
        return;
    }
    int on = 1;
    setsockopt(sock, SOL_SOCKET, SO_BROADCAST, &on, sizeof(on));
    setsockopt(sock, SOL_SOCKET, SO_REUSEADDR, &on, sizeof(on));

    struct sockaddr_in addr = {
        .sin_family = AF_INET,
        .sin_port = htons(R70_DDT_PORT),
        .sin_addr.s_addr = htonl(INADDR_ANY),
    };
    if (bind(sock, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        ESP_LOGE(TAG, "bind UDP %u: errno %d", R70_DDT_PORT, errno);
        close(sock);
        vTaskDelete(NULL);
        return;
    }
    ESP_LOGI(TAG, "discovery listening on UDP %u", R70_DDT_PORT);

    for (;;) {
        uint8_t probe[256];
        struct sockaddr_in from;
        socklen_t from_len = sizeof(from);
        const int n = recvfrom(sock, probe, sizeof(probe), 0,
                               (struct sockaddr *)&from, &from_len);
        if (n <= 0) {
            continue;
        }

        /* Per probe, and per PEER: the answer must name the address on the
         * interface this probe arrived on, or R1 lists a device and then
         * cannot open a socket to it. Reading it here rather than caching it
         * also keeps a late DHCP lease, or a USB cable plugged in after boot,
         * reflected in the very next answer. */
        r70_ddt_identity_t id = {
            .ip = bridge_local_ip_for(ntohl(from.sin_addr.s_addr)),
            .hostname = s_cfg.hostname,
            .socket_count = s_cfg.socket_count,
        };
        memcpy(id.mac, s_cfg.mac, sizeof(id.mac));
        for (uint8_t i = 0; i < s_cfg.socket_count; i++) {
            id.sockets[i].port = (uint16_t)(s_cfg.base_port + i);
            id.sockets[i].service = R70_DDT_SERVICE_SERVER;
            id.sockets[i].protocol = R70_DDT_PROTOCOL_TCP;
        }

        uint8_t answer[DDT_BUF];
        const size_t len = r70_ddt_build_answer(probe, (size_t)n, &id, answer,
                                                sizeof(answer));
        if (len == 0) {
            continue; /* not for us, or our identity is unusable */
        }
        /* R1 discards the UDP sender address and reads the IP out of the
         * record, but the reply still has to reach the port it probed from. */
        sendto(sock, answer, len, 0, (struct sockaddr *)&from, from_len);
        ESP_LOGI(TAG, "answered discovery from %s", inet_ntoa(from.sin_addr));
    }
}

/* --- CAN -> R1 ------------------------------------------------------------ */

static void on_can_rx(const dbcan_frame_t *frame, void *ctx)
{
    (void)ctx;
    const int sock = s_client;
    if (sock < 0) {
        return; /* nothing connected; a real R70 also just drops these */
    }
    rmbcp_can_t msg = {
        .id = frame->id,
        .dlc = frame->dlc,
        .extended = frame->extended,
    };
    memcpy(msg.data, frame->data, frame->dlc);

    uint8_t out[RMBCP_MAX_FRAME];
    const size_t n = rmbcp_encode_can(&msg, out);
    if (n) {
        send(sock, out, n, 0);
    }
}

/* --- R1 -> gateway / CAN -------------------------------------------------- */

static void reply(int sock, uint8_t command, const uint8_t *data, uint8_t len)
{
    uint8_t out[RMBCP_MAX_FRAME];
    const size_t n = rmbcp_encode(command, data, len, out);
    if (n) {
        send(sock, out, n, 0);
    }
}

static size_t device_id_string(uint8_t *out)
{
    /* R1 renders "<host>-<TRANSPORT>-<port>" alongside the MAC. */
    const int n = snprintf((char *)out, 48, "%s-TCP-%u", s_cfg.hostname,
                           (unsigned)s_cfg.base_port);
    size_t len = (n < 0) ? 0 : (size_t)n;
    out[len++] = 0;
    memcpy(&out[len], s_cfg.mac, 6);
    return len + 6;
}

static void handle_frame(int sock, rmbcp_frame_t *frame)
{
    rmbcp_unwrap_extended(frame);

    rmbcp_can_t can;
    if (rmbcp_frame_as_can(frame, &can)) {
        dbcan_frame_t out = {
            .id = can.id,
            .dlc = can.dlc,
            .extended = can.extended,
        };
        memcpy(out.data, can.data, can.dlc);
        dbcan_transmit(&out, 20);
        return;
    }

    uint8_t buf[64];
    switch (frame->command) {
    case RMBCP_CMD_DEVICE_ID: {
        const size_t n = device_id_string(buf);
        reply(sock, RMBCP_CMD_DEVICE_ID, buf, (uint8_t)n);
        break;
    }
    case RMBCP_CMD_VERSION: {
        /* HW, FW, bootloader — 16-bit each. Ours, not a real R70's. */
        const uint8_t v[6] = {0x01, 0x00, 0x00, 0x01, 0x00, 0x01};
        reply(sock, RMBCP_CMD_VERSION, v, sizeof(v));
        break;
    }
    case RMBCP_CMD_ERROR: {
        const uint8_t none[2] = {0, 0};
        reply(sock, RMBCP_CMD_ERROR, none, sizeof(none));
        break;
    }
    case RMBCP_CMD_BUSLOAD: {
        const uint16_t load = dbcan_busload();
        const uint8_t v[2] = {(uint8_t)(load >> 8), (uint8_t)load};
        reply(sock, RMBCP_CMD_BUSLOAD, v, sizeof(v));
        break;
    }
    case RMBCP_CMD_BAUD_REQ:
    case RMBCP_CMD_BAUD_SET: {
        /* dbCAN is fixed at 100 kbit/s, so we report that whatever R1 asks
         * for. R1 sets exactly this value on every connect. */
        const uint8_t rate = RMBCP_BAUD_100K;
        reply(sock, frame->command, &rate, 1);
        break;
    }
    case RMBCP_CMD_CAN_RESET:
        dbcan_poll_recovery();
        reply(sock, RMBCP_CMD_CAN_RESET, NULL, 0);
        break;
    case RMBCP_CMD_RESET_DEV: {
        /* Spec §2.10.1: devices answer a reset with the Device ID, not 0xC0.
         * We must not actually reboot — the host connection would be lost. */
        const size_t n = device_id_string(buf);
        reply(sock, RMBCP_CMD_DEVICE_ID, buf, (uint8_t)n);
        break;
    }
    case RMBCP_CMD_BLOCKTIME:
        reply(sock, frame->command, frame->data, frame->len);
        break;
    case RMBCP_CMD_IFVERSION:
    case RMBCP_CMD_BAUDCALC:
        /* Deliberately unanswered — see docs/PROTOCOL.md §6. R1 sends both
         * during initialisation and proceeds without a reply. */
        break;
    default:
        ESP_LOGD(TAG, "unanswered command 0x%02X", frame->command);
        break;
    }
}

static void serve_client(int sock)
{
    rmbcp_decoder_t dec;
    rmbcp_decoder_init(&dec);
    s_client = sock;

    for (;;) {
        uint8_t chunk[512];
        const int n = recv(sock, chunk, sizeof(chunk), 0);
        if (n <= 0) {
            break;
        }
        rmbcp_decoder_feed(&dec, chunk, (size_t)n);

        rmbcp_frame_t frame;
        while (rmbcp_decoder_next(&dec, &frame)) {
            handle_frame(sock, &frame);
        }
    }

    s_client = -1;
    ESP_LOGI(TAG, "R1 disconnected (%" PRIu32 " malformed frames)", dec.bad_frames);
}

static void tcp_task(void *arg)
{
    const uint16_t port = (uint16_t)(uintptr_t)arg;
    const int listener = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (listener < 0) {
        ESP_LOGE(TAG, "socket: errno %d", errno);
        vTaskDelete(NULL);
        return;
    }
    int on = 1;
    setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, &on, sizeof(on));

    struct sockaddr_in addr = {
        .sin_family = AF_INET,
        .sin_port = htons(port),
        .sin_addr.s_addr = htonl(INADDR_ANY),
    };
    if (bind(listener, (struct sockaddr *)&addr, sizeof(addr)) < 0 ||
        listen(listener, 1) < 0) {
        ESP_LOGE(TAG, "bind/listen TCP %u: errno %d", port, errno);
        close(listener);
        vTaskDelete(NULL);
        return;
    }
    ESP_LOGI(TAG, "data socket listening on TCP %u", port);

    for (;;) {
        struct sockaddr_in peer;
        socklen_t peer_len = sizeof(peer);
        const int sock = accept(listener, (struct sockaddr *)&peer, &peer_len);
        if (sock < 0) {
            continue;
        }
        if (s_client >= 0) {
            /* One master at a time on this socket, as a real R70 behaves. */
            close(sock);
            continue;
        }
        ESP_LOGI(TAG, "R1 connected from %s", inet_ntoa(peer.sin_addr));
        int nodelay = 1;
        setsockopt(sock, IPPROTO_TCP, TCP_NODELAY, &nodelay, sizeof(nodelay));
        serve_client(sock);
        close(sock);
    }
}

esp_err_t bridge_start(const bridge_config_t *cfg)
{
    s_cfg = *cfg;
    snprintf(s_hostname, sizeof(s_hostname), "%s",
             cfg->hostname != NULL ? cfg->hostname : "CANary");
    s_cfg.hostname = s_hostname;
    if (s_cfg.socket_count == 0 || s_cfg.socket_count > R70_DDT_MAX_SOCKETS) {
        /* R1 leaves the socket column read-only below two, so default to the
         * four a real R70 offers. */
        s_cfg.socket_count = R70_DDT_MAX_SOCKETS;
    }

    const esp_err_t err = dbcan_start(cfg->can_tx_gpio, cfg->can_rx_gpio,
                                      on_can_rx, NULL);
    if (err != ESP_OK) {
        return err;
    }

    xTaskCreate(ddt_task, "r70_ddt", 4096, NULL, 5, NULL);
    /* Only socket 1 carries data in practice; the others exist so R1 sees a
     * device with more than one socket. */
    xTaskCreate(tcp_task, "r70_tcp", 6144,
                (void *)(uintptr_t)s_cfg.base_port, 6, NULL);
    return ESP_OK;
}

bool bridge_client_connected(void)
{
    return s_client >= 0;
}
