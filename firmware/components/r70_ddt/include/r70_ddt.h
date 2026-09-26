/*
 * R70 device detection — the UDP 33333 discovery protocol.
 *
 * Undocumented by the vendor; documented from captures of R1's discovery
 * traffic and confirmed live. Full description in docs/PROTOCOL.md §4.
 *
 * Packet = 4-byte header + N fixed 64-byte records:
 *   [0] interface index   [1] 0   [2] opcode   [3] record count
 * Record:
 *   [0..3] IPv4 big-endian, [4] service, [5] protocol, [6..7] port big-endian,
 *   [8..13] MAC, [14..17] ASCII device tag "R70 ", [36..] NUL-terminated name.
 *
 * Two facts that shape this API:
 *   - R1 accepts a datagram only if byte 2 is zero. That is its ONLY validation:
 *     no checksum, no magic. It drops its own broadcast (opcode 0x80) that way.
 *   - R1 ignores the UDP sender address and reads the device IP out of the
 *     record, so we must advertise the address reachable on the probed subnet.
 *     It never checks the MAC's OUI, so our own address is fine.
 *
 * Kept ESP-IDF-free so it can be tested on the host against the captured probe.
 */
#ifndef R70_DDT_H
#define R70_DDT_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define R70_DDT_PORT        33333u
#define R70_DDT_HEADER_LEN  4u
#define R70_DDT_RECORD_LEN  64u

#define R70_DDT_OP_REQUEST 0x80u
#define R70_DDT_OP_ANSWER  0x00u

/* Record field offsets */
#define R70_DDT_OFF_IP       0u
#define R70_DDT_OFF_SERVICE  4u
#define R70_DDT_OFF_PROTOCOL 5u
#define R70_DDT_OFF_PORT     6u
#define R70_DDT_OFF_MAC      8u
#define R70_DDT_OFF_TAG      14u
#define R70_DDT_OFF_HOSTNAME 36u

#define R70_DDT_HOSTNAME_MAX (R70_DDT_RECORD_LEN - R70_DDT_OFF_HOSTNAME - 1u)

/* rec[4]: R1 maps 1 -> service 0, 2 -> 1; anything else is rejected. */
#define R70_DDT_SERVICE_SERVER 1u
#define R70_DDT_SERVICE_CLIENT 2u
/* rec[5]: 1 -> TCP; 2 and 0xFF are rejected; service 1 with protocol 0 is too. */
#define R70_DDT_PROTOCOL_TCP 1u
#define R70_DDT_PROTOCOL_UDP 3u

/* A real R70 offers four sockets. R1 keeps the socket column read-only unless
 * it sees at least two, so advertising the
 * full set is not cosmetic. */
#define R70_DDT_MAX_SOCKETS 4u

typedef struct {
    uint16_t port;
    uint8_t service;
    uint8_t protocol;
} r70_ddt_socket_t;

typedef struct {
    uint32_t ip;                       /* host byte order */
    uint8_t mac[6];
    const char *hostname;
    r70_ddt_socket_t sockets[R70_DDT_MAX_SOCKETS];
    uint8_t socket_count;
} r70_ddt_identity_t;

/* True if the datagram is an identification request for the R70 device type,
 * i.e. something we should answer. Rejects our own answers, so no storms. */
bool r70_ddt_is_request_for_us(const uint8_t *data, size_t len);

/* Build the answer. Returns bytes written to out, or 0 if the datagram is not
 * for us or the identity is invalid. out needs
 * R70_DDT_HEADER_LEN + R70_DDT_MAX_SOCKETS * R70_DDT_RECORD_LEN bytes. */
size_t r70_ddt_build_answer(const uint8_t *probe, size_t probe_len,
                            const r70_ddt_identity_t *id, uint8_t *out,
                            size_t out_cap);

/* Would R1 keep a record with this service/protocol pair? Mirrors R1's filter. */
bool r70_ddt_combination_valid(uint8_t service, uint8_t protocol);

#endif /* R70_DDT_H */
