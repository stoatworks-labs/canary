/*
 * Fuzz the R70 discovery responder — the UDP 33333 attack surface.
 *
 * Discovery answers anything that arrives, from anyone, before any session
 * exists. It is the first code a hostile packet reaches and the easiest to
 * reach: a single unsolicited datagram, no handshake, no connection.
 *
 * The identity fed in deliberately includes a hostname at and beyond
 * R70_DDT_HOSTNAME_MAX, because the record has a fixed 64-byte layout with the
 * hostname last — truncation there is exactly where an overflow would live.
 *
 * See fuzz_rmbcp.c for why this is written to libFuzzer's interface.
 */
#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "r70_ddt.h"

int    LLVMFuzzerTestOneInput(const uint8_t *data, size_t size);
size_t fuzz_seed(size_t index, uint8_t *out, size_t max);

#define ANSWER_BUF (R70_DDT_HEADER_LEN + R70_DDT_MAX_SOCKETS * R70_DDT_RECORD_LEN)

/*
 * Seed 0 is the byte-exact capture of R1 V3.46 scanning for interfaces — the
 * same 64 bytes tools/board_test.py sends. Mutating R1's real probe is far
 * more likely to reach live code than mutating noise.
 */
static const uint8_t SEED_R1_PROBE[64] = {
    0x02, 0x00, 0x80, 0x01, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x52, 0x37, 0x30, 0x20,
    /* remainder zero */
};
/* A header with no body: the shortest thing that still parses as a request. */
static const uint8_t SEED_HEADER_ONLY[] = {0x02, 0x00, 0x80, 0x01};

size_t fuzz_seed(size_t index, uint8_t *out, size_t max)
{
    const struct {
        const uint8_t *bytes;
        size_t         len;
    } seeds[] = {
        {SEED_R1_PROBE, sizeof(SEED_R1_PROBE)},
        {SEED_HEADER_ONLY, sizeof(SEED_HEADER_ONLY)},
    };
    if (index >= sizeof(seeds) / sizeof(seeds[0]) || seeds[index].len > max) {
        return 0;
    }
    memcpy(out, seeds[index].bytes, seeds[index].len);
    return seeds[index].len;
}

/* Longer than the record can hold, so truncation is exercised every run. */
static const char LONG_HOSTNAME[] =
    "canary-a-deliberately-overlong-hostname-that-must-be-truncated-safely";

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    /* Let the fuzzer pick the identity too, not just the probe: socket_count
     * and hostname length are what index into the output buffer. */
    const uint8_t socket_count = size ? (uint8_t)(data[0] % 8u) : 0u;
    const size_t  name_len = size > 1 ? (size_t)data[1] % sizeof(LONG_HOSTNAME)
                                      : sizeof(LONG_HOSTNAME) - 1u;

    char hostname[sizeof(LONG_HOSTNAME)];
    memcpy(hostname, LONG_HOSTNAME, sizeof(LONG_HOSTNAME));
    hostname[name_len] = '\0';

    r70_ddt_identity_t id = {
        .ip = 0xC0A80105u,
        .hostname = hostname,
        .socket_count = socket_count,
    };
    memcpy(id.mac, "\x02\x00\x5E\x10\x00\x01", 6);
    for (uint8_t i = 0; i < socket_count && i < R70_DDT_MAX_SOCKETS; i++) {
        id.sockets[i].port = (uint16_t)(30000 + i);
        id.sockets[i].service = R70_DDT_SERVICE_SERVER;
        id.sockets[i].protocol = R70_DDT_PROTOCOL_TCP;
    }

    /* A guard byte after the buffer: ASan catches a heap overrun, but this
     * also catches a one-past-the-end write into a stack array. */
    struct {
        uint8_t answer[ANSWER_BUF];
        uint8_t guard;
    } out;
    memset(&out, 0, sizeof(out));
    out.guard = 0xA5;

    (void)r70_ddt_is_request_for_us(data, size);

    const size_t len = r70_ddt_build_answer(data, size, &id, out.answer,
                                            sizeof(out.answer));
    assert(len <= sizeof(out.answer));
    assert(out.guard == 0xA5);

    if (len > 0) {
        /* A well-formed answer must be a header plus whole records. */
        assert(len >= R70_DDT_HEADER_LEN);
        assert(((len - R70_DDT_HEADER_LEN) % R70_DDT_RECORD_LEN) == 0);
    }
    return 0;
}
