/*
 * canaryd — the real bridge firmware, running as a host process.
 *
 * This links the SHIPPING C from firmware/components (bridge, rmbcp, r70_ddt,
 * dbcan) against the ESP-IDF stand-ins in hostsim/shim, and puts it on real
 * sockets. Point R1 at this and R1 is driving the code that goes on the board,
 * not tools/r70_emu.py — which is the one thing the Python emulator, however
 * well proven, can never tell you.
 *
 * What it does not cover: W5500/SPI, TWAI silicon, boot, NVS, task stack
 * sizing, anything in net.c. See hostsim/README.md.
 *
 *     ./canaryd --hostname CANary --port 30000
 */
#include "bridge.h"

#include "esp_log.h"

#include <arpa/inet.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

static const char *TAG = "canaryd";

static uint32_t s_forced_ip; /* host byte order, 0 = auto-detect */

/*
 * The address R1 will be told to connect to. R1 discards the UDP sender and
 * uses whatever the discovery record says, so getting this wrong makes the
 * device appear in R1's list and then refuse every connection — the exact
 * failure that is hardest to read from the R1 end.
 *
 * The bridge asks per probe and names the peer, because a unit with both a
 * wired interface and a USB-NCM one holds two addresses and only one of them
 * is reachable from any given R1. On the target, net.c answers that from the
 * interface table. Here the host's own routing table answers it exactly, which
 * is the better oracle: connect() on a UDP socket picks the source address the
 * kernel would really use for that peer, so canaryd exercises the per-peer
 * contract rather than a stub that ignores it.
 */
uint32_t bridge_local_ip_for(uint32_t peer)
{
    if (s_forced_ip) {
        return s_forced_ip;
    }
    /* Ask the routing table which source address would be used, without
     * sending anything: connect() on UDP only sets the default peer. A peer of
     * 0 means "no particular peer", for which TEST-NET-1 stands in — never
     * routed, so it resolves to whatever the default route's source is. */
    const int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (sock < 0) {
        return 0x7F000001u; /* 127.0.0.1 */
    }
    struct sockaddr_in probe;
    memset(&probe, 0, sizeof(probe));
    probe.sin_family = AF_INET;
    probe.sin_port = htons(53);
    probe.sin_addr.s_addr = htonl(peer ? peer : 0xC0000201u); /* 192.0.2.1 */

    uint32_t ip = 0x7F000001u;
    if (connect(sock, (struct sockaddr *)&probe, sizeof(probe)) == 0) {
        struct sockaddr_in local;
        socklen_t len = sizeof(local);
        if (getsockname(sock, (struct sockaddr *)&local, &len) == 0) {
            ip = ntohl(local.sin_addr.s_addr);
        }
    }
    close(sock);
    return ip;
}

static bool parse_mac(const char *text, uint8_t out[6])
{
    unsigned v[6];
    if (sscanf(text, "%x:%x:%x:%x:%x:%x", &v[0], &v[1], &v[2], &v[3], &v[4],
               &v[5]) != 6) {
        return false;
    }
    for (int i = 0; i < 6; i++) {
        if (v[i] > 0xFF) {
            return false;
        }
        out[i] = (uint8_t)v[i];
    }
    return true;
}

static void usage(const char *argv0)
{
    fprintf(stderr,
            "usage: %s [options]\n"
            "  --hostname NAME   name R1 lists (default CANary)\n"
            "  --port N          TCP data socket (default 30000)\n"
            "  --sockets N       sockets advertised, 0 = R70 default of 4\n"
            "  --mac AA:BB:...   advertised MAC (default 02:00:5E:10:00:01)\n"
            "  --ip A.B.C.D      address put in the discovery record\n"
            "                    (default: auto-detected outbound address)\n"
            "environment:\n"
            "  CANARY_LOG_LEVEL  0-5, default 3 (INFO)\n"
            "  CANARY_VCAN_PORT  virtual CAN hub port, default 35000\n",
            argv0);
}

int main(int argc, char **argv)
{
    bridge_config_t cfg = {
        .hostname = "CANary",
        .mac = {0x02, 0x00, 0x5E, 0x10, 0x00, 0x01},
        .base_port = 30000,
        .socket_count = 0, /* bridge_start replaces 0 with the R70's 4 */
        .can_tx_gpio = 4,
        .can_rx_gpio = 5,
    };

    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];
        const bool has_value = (i + 1) < argc;
        if (!strcmp(arg, "--hostname") && has_value) {
            cfg.hostname = argv[++i];
        } else if (!strcmp(arg, "--port") && has_value) {
            cfg.base_port = (uint16_t)atoi(argv[++i]);
        } else if (!strcmp(arg, "--sockets") && has_value) {
            cfg.socket_count = (uint8_t)atoi(argv[++i]);
        } else if (!strcmp(arg, "--mac") && has_value) {
            if (!parse_mac(argv[++i], cfg.mac)) {
                fprintf(stderr, "bad --mac\n");
                return 2;
            }
        } else if (!strcmp(arg, "--ip") && has_value) {
            s_forced_ip = ntohl(inet_addr(argv[++i]));
        } else {
            usage(argv[0]);
            return 2;
        }
    }

    /* A broken pipe on the R1 socket must not take the process down; the
     * bridge already handles the short write. */
    signal(SIGPIPE, SIG_IGN);

    const uint32_t ip = bridge_local_ip_for(0);
    ESP_LOGI(TAG, "advertising %u.%u.%u.%u as \"%s\" on TCP %u",
             (unsigned)(ip >> 24) & 0xFFu, (unsigned)(ip >> 16) & 0xFFu,
             (unsigned)(ip >> 8) & 0xFFu, (unsigned)ip & 0xFFu, cfg.hostname,
             cfg.base_port);

    const esp_err_t err = bridge_start(&cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "bridge_start failed: %d", err);
        return 1;
    }

    /* stdout is the machine-readable channel; the harness waits on this line
     * rather than sleeping a fixed time. */
    printf("canaryd ready tcp=%u udp=33333\n", cfg.base_port);
    fflush(stdout);

    for (;;) {
        pause();
    }
}
