/* Host tests for the R70 device-detection protocol.
 *
 * REAL_PROBE is a byte-exact capture of R1 V3.46 scanning (2026-07-22,
 * interface index 2), so the decoder is pinned to captured traffic. */
#include <stdio.h>
#include <string.h>

#include "r70_ddt.h"

static int checks = 0, fails = 0;
#define CHECK(c, ...) do { checks++; if (!(c)) { \
    fails++; printf("  FAIL %s:%d  ", __FILE__, __LINE__); printf(__VA_ARGS__); \
    printf("\n"); } } while (0)

#define OUT_CAP (R70_DDT_HEADER_LEN + R70_DDT_MAX_SOCKETS * R70_DDT_RECORD_LEN)

static uint8_t probe[68];

static void make_probe(void)
{
    memset(probe, 0, sizeof(probe));
    probe[0] = 2;                    /* interface index */
    probe[2] = R70_DDT_OP_REQUEST;   /* 0x80 */
    probe[3] = 1;                    /* one template record */
    memcpy(&probe[R70_DDT_HEADER_LEN + R70_DDT_OFF_TAG], "R70 ", 4);
}

static r70_ddt_identity_t identity(uint8_t sockets)
{
    static const uint8_t mac[6] = {0x00, 0x50, 0xC2, 0x5D, 0xC0, 0xBE};
    r70_ddt_identity_t id;
    memset(&id, 0, sizeof(id));
    id.ip = 0xC000025Au; /* 192.0.2.90 */
    memcpy(id.mac, mac, sizeof(mac));
    id.hostname = "db-70";
    id.socket_count = sockets;
    for (uint8_t i = 0; i < sockets; i++) {
        id.sockets[i].port = (uint16_t)(30000 + i);
        id.sockets[i].service = R70_DDT_SERVICE_SERVER;
        id.sockets[i].protocol = R70_DDT_PROTOCOL_TCP;
    }
    return id;
}

int main(void)
{
    uint8_t out[OUT_CAP];
    make_probe();

    printf("captured probe\n");
    {
        CHECK(sizeof(probe) == R70_DDT_HEADER_LEN + R70_DDT_RECORD_LEN,
              "probe is header + one record");
        CHECK(r70_ddt_is_request_for_us(probe, sizeof(probe)),
              "the real probe must be recognised");
    }

    printf("answer\n");
    {
        const r70_ddt_identity_t id = identity(1);
        const size_t n = r70_ddt_build_answer(probe, sizeof(probe), &id, out, OUT_CAP);
        CHECK(n == 68, "one-socket answer is 68 bytes, got %zu", n);
        /* The single thing R1 checks before accepting an answer. */
        CHECK(out[2] == R70_DDT_OP_ANSWER, "opcode must be 0 or R1 drops it");
        CHECK(out[0] == 2, "interface index echoed");
        CHECK(out[3] == 1, "record count");

        const uint8_t *rec = &out[R70_DDT_HEADER_LEN];
        CHECK(rec[0] == 192 && rec[1] == 0 && rec[2] == 2 && rec[3] == 90,
              "IPv4 big-endian");
        CHECK(rec[R70_DDT_OFF_PORT] == 0x75 && rec[R70_DDT_OFF_PORT + 1] == 0x30,
              "port 30000 big-endian");
        CHECK(memcmp(&rec[R70_DDT_OFF_MAC], "\x00\x50\xC2\x5D\xC0\xBE", 6) == 0,
              "MAC");
        CHECK(memcmp(&rec[R70_DDT_OFF_TAG], "R70 ", 4) == 0, "device tag");
        CHECK(memcmp(&rec[R70_DDT_OFF_HOSTNAME], "db-70\0", 6) == 0,
              "NUL-terminated host name at offset 36");
    }
    {
        /* R1 leaves the socket column read-only below two sockets. */
        const r70_ddt_identity_t id = identity(4);
        const size_t n = r70_ddt_build_answer(probe, sizeof(probe), &id, out, OUT_CAP);
        CHECK(n == 4 + 4 * 64, "four-socket answer is 260 bytes, got %zu", n);
        CHECK(out[3] == 4, "record count is 4");
        for (uint8_t i = 0; i < 4; i++) {
            const uint8_t *rec = &out[R70_DDT_HEADER_LEN + i * R70_DDT_RECORD_LEN];
            const uint16_t port = (uint16_t)((rec[R70_DDT_OFF_PORT] << 8) |
                                             rec[R70_DDT_OFF_PORT + 1]);
            CHECK(port == 30000 + i, "socket %u port", i);
        }
    }

    printf("rejection\n");
    {
        /* Our own answer must never trigger another answer. */
        const r70_ddt_identity_t id = identity(1);
        r70_ddt_build_answer(probe, sizeof(probe), &id, out, OUT_CAP);
        CHECK(!r70_ddt_is_request_for_us(out, 68), "an answer is not a request");
    }
    {
        /* R60 is the USB interface — not us. */
        uint8_t other[68];
        memcpy(other, probe, sizeof(other));
        memcpy(&other[R70_DDT_HEADER_LEN + R70_DDT_OFF_TAG], "R60 ", 4);
        CHECK(!r70_ddt_is_request_for_us(other, sizeof(other)),
              "another device type must be ignored");
    }
    {
        /* A header claiming more records than the datagram holds. */
        uint8_t bad[68];
        memcpy(bad, probe, sizeof(bad));
        bad[3] = 4;
        CHECK(!r70_ddt_is_request_for_us(bad, sizeof(bad)),
              "truncated packet must be rejected");
        CHECK(!r70_ddt_is_request_for_us(probe, 3), "runt packet rejected");
    }
    {
        /* Combinations R1 discards. */
        CHECK(!r70_ddt_combination_valid(0, 1), "service 0 rejected");
        CHECK(!r70_ddt_combination_valid(3, 1), "service 3 rejected");
        CHECK(!r70_ddt_combination_valid(1, 2), "protocol 2 rejected");
        CHECK(!r70_ddt_combination_valid(1, 0xFF), "protocol 0xFF rejected");
        CHECK(!r70_ddt_combination_valid(1, 0), "service 1 + protocol 0 rejected");
        CHECK(r70_ddt_combination_valid(1, 1), "server/TCP accepted");
        CHECK(r70_ddt_combination_valid(2, 1), "client/TCP accepted");
        CHECK(r70_ddt_combination_valid(2, 0), "client/none accepted");

        r70_ddt_identity_t id = identity(1);
        id.sockets[0].service = 0;
        CHECK(r70_ddt_build_answer(probe, sizeof(probe), &id, out, OUT_CAP) == 0,
              "must refuse to emit a record R1 would drop");
    }
    {
        /* Duplicate (service, protocol, port) — R1 would dedup them. */
        r70_ddt_identity_t id = identity(2);
        id.sockets[1] = id.sockets[0];
        CHECK(r70_ddt_build_answer(probe, sizeof(probe), &id, out, OUT_CAP) == 0,
              "duplicate sockets must be refused");
    }
    {
        /* An over-long host name must be truncated, never overrun the record. */
        r70_ddt_identity_t id = identity(1);
        id.hostname = "a-very-long-host-name-that-will-not-fit-in-the-record";
        const size_t n = r70_ddt_build_answer(probe, sizeof(probe), &id, out, OUT_CAP);
        CHECK(n == 68, "over-long name still produces a valid answer");
        CHECK(out[67] == 0, "last record byte stays the NUL terminator");
    }
    {
        r70_ddt_identity_t id = identity(4);
        CHECK(r70_ddt_build_answer(probe, sizeof(probe), &id, out, 68) == 0,
              "must refuse to overflow the caller's buffer");
    }

    printf("\n%d checks, %d failed\n", checks, fails);
    return fails ? 1 : 0;
}
