/*
 * Fuzz the RMBCP stream decoder — the code that parses bytes off the network.
 *
 * This is the whole attack surface. TCP 30000 has no authentication (see
 * bridge.h), so anything that can reach a dbCANary on a show network gets to
 * choose these bytes. A decoder that reads out of bounds on a hostile length
 * field is a remote crash on a device in a rack.
 *
 * Written to libFuzzer's interface so `-fsanitize=fuzzer` picks it up
 * directly, but it links against standalone_main.c when libFuzzer is absent —
 * which it is in Apple's toolchain. The bug detector in both cases is
 * ASan/UBSan; libFuzzer only adds coverage-guided input generation.
 *
 * The invariants asserted here are the decoder's contract, not guesses:
 *   - a frame's len never exceeds RMBCP_MAX_DATA
 *   - feed() never reports dropping more than it was given
 *   - the whole pipeline the bridge runs (unwrap, as_can) survives any input
 */
#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "rmbcp.h"

int    LLVMFuzzerTestOneInput(const uint8_t *data, size_t size);
size_t fuzz_seed(size_t index, uint8_t *out, size_t max);

/*
 * Seeds. Random bytes almost never contain a valid frame, so without these the
 * fuzzer only ever exercises the resynchronisation path and never gets inside
 * a decoded frame. These are real: the first two are the vendor's own worked
 * examples, checksums and all, the same vectors the unit tests use.
 */
static const uint8_t SEED_DEVICE_ID[] = {0x43, 0x01, 0x40, 0x42, 0x0D};
static const uint8_t SEED_BAUD_SET[]  = {0x43, 0x02, 0x57, 0xFE, 0xBC, 0x0D};
/* An 11-bit CAN frame: id 0x442, three payload bytes. */
static const uint8_t SEED_CAN11[] = {0x43, 0x06, 0x00, 0x04, 0x42,
                                     0xA1, 0xB2, 0xC3, 0x21, 0x0D};
/* Extended command form, which wraps a real command behind a channel byte. */
static const uint8_t SEED_EXT[] = {0x43, 0x04, 0xD0, 0x01, 0x40, 0x00, 0x96, 0x0D};
/* Maximum declared length with no body — the classic overrun bait. */
static const uint8_t SEED_LONG_LEN[] = {0x43, 0xFF, 0x40, 0x00, 0x0D};

size_t fuzz_seed(size_t index, uint8_t *out, size_t max)
{
    const struct {
        const uint8_t *bytes;
        size_t         len;
    } seeds[] = {
        {SEED_DEVICE_ID, sizeof(SEED_DEVICE_ID)},
        {SEED_BAUD_SET, sizeof(SEED_BAUD_SET)},
        {SEED_CAN11, sizeof(SEED_CAN11)},
        {SEED_EXT, sizeof(SEED_EXT)},
        {SEED_LONG_LEN, sizeof(SEED_LONG_LEN)},
    };
    if (index >= sizeof(seeds) / sizeof(seeds[0]) || seeds[index].len > max) {
        return 0;
    }
    memcpy(out, seeds[index].bytes, seeds[index].len);
    return seeds[index].len;
}

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    rmbcp_decoder_t dec;
    rmbcp_decoder_init(&dec);

    /* Feed in ragged chunks: the real socket delivers arbitrary splits, and a
     * decoder can be correct on whole frames yet wrong across a boundary. The
     * chunk sizes come from the input itself so the fuzzer can steer them. */
    size_t offset = 0;
    while (offset < size) {
        size_t chunk = (size_t)(data[offset] % 37u) + 1u;
        if (offset + chunk > size) {
            chunk = size - offset;
        }
        const size_t dropped = rmbcp_decoder_feed(&dec, &data[offset], chunk);
        assert(dropped <= chunk);
        offset += chunk;

        /*
         * Assert the decoder's own state invariant explicitly. This is not
         * belt-and-braces: `used` and `buf` are members of the same struct, so
         * a write one byte past buf lands in used rather than past the object,
         * and ASan does not detect intra-object overflows. Sanitizers alone
         * would let that bug through — verified by planting it.
         */
        assert(dec.used <= sizeof(dec.buf));

        rmbcp_frame_t frame;
        while (rmbcp_decoder_next(&dec, &frame)) {
            assert(frame.len <= RMBCP_MAX_DATA);

            /* Exactly what bridge.c/handle_frame does to every frame. */
            (void)rmbcp_unwrap_extended(&frame);
            assert(frame.len <= RMBCP_MAX_DATA);

            rmbcp_can_t can;
            if (rmbcp_frame_as_can(&frame, &can)) {
                assert(can.dlc <= 8);
                /* Round-trip: whatever we accepted must re-encode. */
                uint8_t out[RMBCP_MAX_FRAME];
                const size_t n = rmbcp_encode_can(&can, out);
                assert(n <= RMBCP_MAX_FRAME);
            }
        }
    }
    return 0;
}
