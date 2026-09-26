/* Host tests for the RM Byte Command Protocol codec.
 *
 * The spec_example_* cases are the worked examples printed in the vendor spec
 * (§2.1.1 and §2.2.1), checksums included, so the C codec is pinned to the
 * document — and to the Python implementation in tools/, which carries the
 * same two vectors. */
#include <stdio.h>
#include <string.h>

#include "rmbcp.h"

static int checks = 0, fails = 0;
#define CHECK(c, ...) do { checks++; if (!(c)) { \
    fails++; printf("  FAIL %s:%d  ", __FILE__, __LINE__); printf(__VA_ARGS__); \
    printf("\n"); } } while (0)

static int feed_all(rmbcp_decoder_t *dec, const uint8_t *buf, size_t n,
                    rmbcp_frame_t *frames, int max)
{
    rmbcp_decoder_feed(dec, buf, n);
    int got = 0;
    while (got < max && rmbcp_decoder_next(dec, &frames[got])) {
        got++;
    }
    return got;
}

int main(void)
{
    uint8_t out[RMBCP_MAX_FRAME];
    rmbcp_frame_t frames[8];
    rmbcp_decoder_t dec;

    printf("vendor spec worked examples\n");
    {
        /* §2.1.1: 11-bit id 0x789, data 0x11..0x18, checksum 0xCE. */
        const uint8_t want[] = {0x43, 0x0B, 0x00, 0x07, 0x89, 0x11, 0x12, 0x13,
                                0x14, 0x15, 0x16, 0x17, 0x18, 0xCE, 0x0D};
        rmbcp_can_t msg = {.id = 0x789, .dlc = 8};
        for (int i = 0; i < 8; i++) msg.data[i] = (uint8_t)(0x11 + i);
        const size_t n = rmbcp_encode_can(&msg, out);
        CHECK(n == sizeof(want), "encoded %zu bytes, expected %zu", n, sizeof(want));
        CHECK(memcmp(out, want, sizeof(want)) == 0, "spec 2.1.1 byte mismatch");
    }
    {
        /* §2.2.1: the same message on CAN channel 2 (index 1), checksum 0x19. */
        const uint8_t want[] = {0x43, 0x0D, 0xD0, 0x01, 0x00, 0x07, 0x89, 0x11,
                                0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19, 0x0D};
        rmbcp_can_t msg = {.id = 0x789, .dlc = 8, .channel = 1};
        for (int i = 0; i < 8; i++) msg.data[i] = (uint8_t)(0x11 + i);
        const size_t n = rmbcp_encode_can(&msg, out);
        CHECK(n == sizeof(want), "encoded %zu bytes, expected %zu", n, sizeof(want));
        CHECK(memcmp(out, want, sizeof(want)) == 0, "spec 2.2.1 byte mismatch");
    }

    printf("framing\n");
    {
        const size_t n = rmbcp_encode(RMBCP_CMD_DEVICE_ID, NULL, 0, out);
        CHECK(n == 5, "empty frame is 5 bytes, got %zu", n);
        CHECK(out[1] == 1, "Length counts the command byte");
    }

    printf("round trip\n");
    {
        rmbcp_can_t msg = {.id = 0x2AA, .dlc = 3};
        memcpy(msg.data, "\x01\x02\x03", 3);
        const size_t n = rmbcp_encode_can(&msg, out);
        rmbcp_decoder_init(&dec);
        CHECK(feed_all(&dec, out, n, frames, 8) == 1, "expected one frame");
        rmbcp_can_t got;
        CHECK(rmbcp_frame_as_can(&frames[0], &got), "should decode as CAN");
        CHECK(got.id == 0x2AA && got.dlc == 3, "id/dlc round trip");
        CHECK(memcmp(got.data, "\x01\x02\x03", 3) == 0, "payload round trip");
    }
    {
        /* 29-bit plus timestamp. */
        rmbcp_can_t msg = {.id = 0x1FFFFFFF, .dlc = 2, .extended = true,
                           .has_timestamp = true, .timestamp = 0xDEADBEEF};
        memcpy(msg.data, "\xAA\xBB", 2);
        const size_t n = rmbcp_encode_can(&msg, out);
        rmbcp_decoder_init(&dec);
        CHECK(feed_all(&dec, out, n, frames, 8) == 1, "expected one frame");
        rmbcp_can_t got;
        CHECK(rmbcp_frame_as_can(&frames[0], &got), "should decode as CAN");
        CHECK(got.id == 0x1FFFFFFF && got.extended, "29-bit id round trip");
        CHECK(got.timestamp == 0xDEADBEEF, "timestamp round trip");
        CHECK(got.dlc == 2, "dlc with timestamp present");
    }
    {
        /* Extended command form unwraps to the inner CAN frame. */
        rmbcp_can_t msg = {.id = 0x123, .dlc = 2, .channel = 3};
        memcpy(msg.data, "\xAA\xBB", 2);
        const size_t n = rmbcp_encode_can(&msg, out);
        rmbcp_decoder_init(&dec);
        CHECK(feed_all(&dec, out, n, frames, 8) == 1, "expected one frame");
        CHECK(rmbcp_unwrap_extended(&frames[0]) == 3, "channel should be 3");
        rmbcp_can_t got;
        CHECK(rmbcp_frame_as_can(&frames[0], &got), "inner frame is CAN");
        CHECK(got.id == 0x123 && got.dlc == 2, "inner id/dlc");
    }

    printf("stream decoding\n");
    {
        /* Block Time batches several frames into one segment. */
        uint8_t blob[512];
        size_t n = 0;
        for (uint8_t i = 1; i <= 5; i++) {
            rmbcp_can_t msg = {.id = i, .dlc = 1};
            msg.data[0] = i;
            n += rmbcp_encode_can(&msg, &blob[n]);
        }
        rmbcp_decoder_init(&dec);
        const int got = feed_all(&dec, blob, n, frames, 8);
        CHECK(got == 5, "expected 5 batched frames, got %d", got);
        for (int i = 0; i < got; i++) {
            rmbcp_can_t c;
            rmbcp_frame_as_can(&frames[i], &c);
            CHECK(c.id == (uint32_t)(i + 1), "frame %d id", i);
        }
    }
    {
        /* A frame arriving one byte at a time must still yield exactly one. */
        rmbcp_can_t msg = {.id = 0x123, .dlc = 8};
        const size_t n = rmbcp_encode_can(&msg, out);
        rmbcp_decoder_init(&dec);
        int got = 0;
        rmbcp_frame_t f;
        for (size_t i = 0; i < n; i++) {
            rmbcp_decoder_feed(&dec, &out[i], 1);
            while (rmbcp_decoder_next(&dec, &f)) got++;
        }
        CHECK(got == 1, "byte-at-a-time gave %d frames, expected 1", got);
    }
    {
        /* 0x43 and 0x0D are legal CAN payload and must not cause a resync. */
        rmbcp_can_t msg = {.id = 0x100, .dlc = 5};
        memcpy(msg.data, "\x43\x0D\x43\x43\x0D", 5);
        const size_t n = rmbcp_encode_can(&msg, out);
        rmbcp_decoder_init(&dec);
        CHECK(feed_all(&dec, out, n, frames, 8) == 1, "SOF/EOF in payload");
        rmbcp_can_t got;
        rmbcp_frame_as_can(&frames[0], &got);
        CHECK(memcmp(got.data, "\x43\x0D\x43\x43\x0D", 5) == 0, "payload intact");
    }
    {
        /* Leading garbage, including a false SOF with a nonsense length, must
         * not stall the stream — this was a real bug in the Python original. */
        uint8_t blob[512];
        const uint8_t junk[] = {0x00, 0xFF, 0x43, 0x99};
        memcpy(blob, junk, sizeof(junk));
        rmbcp_can_t msg = {.id = 0x321, .dlc = 1};
        msg.data[0] = 0x09;
        const size_t n = sizeof(junk) + rmbcp_encode_can(&msg, &blob[sizeof(junk)]);
        rmbcp_decoder_init(&dec);
        CHECK(feed_all(&dec, blob, n, frames, 8) == 1, "should resync past junk");
        rmbcp_can_t got;
        rmbcp_frame_as_can(&frames[0], &got);
        CHECK(got.id == 0x321, "recovered the real frame");
    }
    {
        /* A corrupt frame costs that frame only, not the stream. */
        uint8_t blob[512];
        rmbcp_can_t a = {.id = 0x111, .dlc = 2};
        size_t n = rmbcp_encode_can(&a, blob);
        blob[n - 2] ^= 0xFF; /* break the checksum */
        rmbcp_can_t b = {.id = 0x222, .dlc = 1};
        n += rmbcp_encode_can(&b, &blob[n]);
        rmbcp_decoder_init(&dec);
        const int got = feed_all(&dec, blob, n, frames, 8);
        CHECK(got == 1, "expected only the good frame, got %d", got);
        rmbcp_can_t c;
        rmbcp_frame_as_can(&frames[0], &c);
        CHECK(c.id == 0x222, "the surviving frame is the second one");
        CHECK(dec.bad_frames > 0, "corrupt frame should be counted");
    }
    {
        /* An incomplete frame is held, not dropped. */
        rmbcp_can_t msg = {.id = 0x123, .dlc = 8};
        const size_t n = rmbcp_encode_can(&msg, out);
        rmbcp_decoder_init(&dec);
        rmbcp_frame_t f;
        rmbcp_decoder_feed(&dec, out, 6);
        CHECK(!rmbcp_decoder_next(&dec, &f), "partial frame must not decode");
        rmbcp_decoder_feed(&dec, &out[6], n - 6);
        CHECK(rmbcp_decoder_next(&dec, &f), "completed frame must decode");
    }
    {
        /* Regression: Length=0 underflowed len to 255.
         *
         * Found by firmware/hostsim/fuzz. Length counts command + data, so 0 is
         * illegal, but the decoder computed len = length - 1 in uint8_t and got
         * 255. That read up to 259 bytes past the SOF (off the end of a
         * 518-byte buf when the SOF landed late, confirmed by ASan/UBSan) and
         * then memcpy'd 255 bytes into a 254-byte data[], landing the last byte
         * exactly on out->len. A peer therefore chose the length of the frame
         * the bridge went on to handle. TCP 30000 has no authentication.
         *
         * Two shapes, because they fail differently:
         *   1. the 4-byte minimum, which the old code accepted as "complete"
         *   2. a crafted frame whose checksum matches, which reached the memcpy
         */
        rmbcp_frame_t f;
        const uint8_t minimal[4] = {RMBCP_SOF, 0x00, 0x40, RMBCP_EOF};
        rmbcp_decoder_init(&dec);
        rmbcp_decoder_feed(&dec, minimal, sizeof(minimal));
        CHECK(!rmbcp_decoder_next(&dec, &f), "Length=0 must never decode");
        CHECK(dec.bad_frames == 1, "Length=0 counts as a bad frame");

        uint8_t crafted[300];
        memset(crafted, 0, sizeof(crafted));
        crafted[0] = RMBCP_SOF;
        crafted[1] = 0x00; /* the hostile length */
        crafted[2] = 0x40;
        crafted[3 + 254] = 0x7E; /* would land on out->len */
        crafted[3 + 255] = rmbcp_checksum(0x00, 0x40, &crafted[3], 255);
        crafted[4 + 255] = RMBCP_EOF;
        rmbcp_decoder_init(&dec);
        rmbcp_decoder_feed(&dec, crafted, 260);
        CHECK(!rmbcp_decoder_next(&dec, &f),
              "Length=0 with a matching checksum must not decode either");

        /* Resynchronisation still works: a good frame after the bad one. */
        rmbcp_can_t good = {.id = 0x222, .dlc = 2, .data = {0xAA, 0xBB}};
        const size_t n = rmbcp_encode_can(&good, out);
        rmbcp_decoder_init(&dec);
        rmbcp_decoder_feed(&dec, minimal, sizeof(minimal));
        rmbcp_decoder_feed(&dec, out, n);
        CHECK(rmbcp_decoder_next(&dec, &f),
              "the frame after a Length=0 must still decode");
        rmbcp_can_t c;
        CHECK(rmbcp_frame_as_can(&f, &c) && c.id == 0x222,
              "and it is the right frame");
    }

    printf("dbCAN identifiers\n");
    {
        CHECK(dbcan_id(DBCAN_OBJ_PRIMARY_MASTER, 0, 1) == 0x001, "0.01 master");
        CHECK(dbcan_id(DBCAN_OBJ_DEVICE_DATA, 0, 1) == 0x401, "0.01 device");
        CHECK(dbcan_id(DBCAN_OBJ_STREAM, 7, 63) == 0x7FF, "7.63 stream");
        /* Observed live: R1 sweeps subnets as secondary master. */
        CHECK(dbcan_id(DBCAN_OBJ_SECONDARY_MASTER, 1, 0) == 0x240, "R1 scan 1.00");
        CHECK(dbcan_id(DBCAN_OBJ_DEVICE_DATA, 1, 2) == 0x442, "device 1.02 reply");
        CHECK(dbcan_object_class(0x442) == DBCAN_OBJ_DEVICE_DATA, "class of 0x442");
        CHECK(dbcan_subnet(0x442) == 1, "subnet of 0x442");
        CHECK(dbcan_device(0x442) == 2, "device of 0x442");
    }
    {
        /* R70 software manual §1.3.2 filtering example. */
        const uint16_t mask = 0x600, arb = 0x400;
        CHECK(((0x001 ^ arb) & mask) != 0, "master telegram blocked");
        CHECK(((0x401 ^ arb) & mask) == 0, "device telegram passed");
    }

    printf("\n%d checks, %d failed\n", checks, fails);
    return fails ? 1 : 0;
}
