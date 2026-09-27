/*
 * A dependency-free driver for the LLVMFuzzerTestOneInput targets.
 *
 * Apple's clang ships no libFuzzer, and the rest of this project's tests need
 * nothing but `cc` and a shell — so rather than make fuzzing conditional on a
 * 1.5 GB toolchain nobody has installed, the targets are written to
 * libFuzzer's interface and driven by this when it is absent. Build with
 * `-fsanitize=fuzzer` instead and the same target files are picked up
 * unchanged, with coverage feedback.
 *
 * The bug detector is ASan and UBSan either way. What libFuzzer adds is
 * coverage-guided input selection; what this does instead is mutate a seed
 * corpus of REAL protocol vectors, which for a parser this small covers a lot
 * of the same ground. It is not equivalent, and run_fuzz.sh says so.
 *
 * Runs are deterministic: the same --seed reproduces the same inputs exactly.
 * The input under test is written to the crash file BEFORE it runs, so an
 * ASan abort still leaves you the bytes that caused it.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int    LLVMFuzzerTestOneInput(const uint8_t *data, size_t size);
size_t fuzz_seed(size_t index, uint8_t *out, size_t max);

#define MAX_INPUT 1024

/* xorshift64*, so a run is reproducible from its seed on any machine. */
static uint64_t g_state = 88172645463325252ull;

static uint64_t next_random(void)
{
    g_state ^= g_state >> 12;
    g_state ^= g_state << 25;
    g_state ^= g_state >> 27;
    return g_state * 2685821657736338717ull;
}

static size_t random_below(size_t bound)
{
    return bound ? (size_t)(next_random() % bound) : 0;
}

/* Values that sit on parser boundaries: framing bytes, length extremes. */
static const uint8_t INTERESTING[] = {0x00, 0x01, 0x02, 0x0D, 0x43, 0x7F,
                                      0x80, 0xC0, 0xD0, 0xFE, 0xFF};

static size_t mutate(uint8_t *buf, size_t len)
{
    switch (random_below(8)) {
    case 0: /* flip one bit */
        if (len) {
            buf[random_below(len)] ^= (uint8_t)(1u << random_below(8));
        }
        break;
    case 1: /* set a byte to an interesting value */
        if (len) {
            buf[random_below(len)] =
                INTERESTING[random_below(sizeof(INTERESTING))];
        }
        break;
    case 2: /* set a byte at random */
        if (len) {
            buf[random_below(len)] = (uint8_t)next_random();
        }
        break;
    case 3: /* truncate */
        if (len > 1) {
            len = random_below(len);
        }
        break;
    case 4: /* extend with noise */
        while (len < MAX_INPUT && random_below(4)) {
            buf[len++] = (uint8_t)next_random();
        }
        break;
    case 5: /* a long run of one byte — the only way to reach the
             * buffer-full path, which needs more consecutive non-framing
             * bytes than short random noise ever produces */
        if (len < MAX_INPUT) {
            const uint8_t fill = INTERESTING[random_below(sizeof(INTERESTING))];
            size_t run = random_below(MAX_INPUT - len);
            while (run-- > 0 && len < MAX_INPUT) {
                buf[len++] = fill;
            }
        }
        break;
    case 6: /* duplicate a run — makes back-to-back and nested frames */
        if (len && len * 2 <= MAX_INPUT) {
            const size_t start = random_below(len);
            const size_t run = random_below(len - start) + 1;
            memmove(&buf[start + run], &buf[start], len - start);
            len += run;
        }
        break;
    default: /* splice in a fresh seed, so frames appear mid-stream */
        if (len < MAX_INPUT) {
            uint8_t seed[MAX_INPUT];
            const size_t n = fuzz_seed(random_below(8), seed, sizeof(seed));
            if (n && len + n <= MAX_INPUT) {
                memcpy(&buf[len], seed, n);
                len += n;
            }
        }
        break;
    }
    return len;
}

int main(int argc, char **argv)
{
    unsigned long iterations = 200000;
    const char   *crash_path = "/tmp/canary_fuzz_last.bin";

    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--iterations") && i + 1 < argc) {
            iterations = strtoul(argv[++i], NULL, 10);
        } else if (!strcmp(argv[i], "--seed") && i + 1 < argc) {
            g_state = strtoull(argv[++i], NULL, 10) | 1ull;
        } else if (!strcmp(argv[i], "--crash-file") && i + 1 < argc) {
            crash_path = argv[++i];
        } else {
            fprintf(stderr,
                    "usage: %s [--iterations N] [--seed N] [--crash-file PATH]\n",
                    argv[0]);
            return 2;
        }
    }

    /* Every seed, verbatim, before any mutation: if a vendor vector itself
     * breaks the parser we want that reported as such, not as a mutation. */
    uint8_t buf[MAX_INPUT];
    for (size_t i = 0;; i++) {
        const size_t n = fuzz_seed(i, buf, sizeof(buf));
        if (n == 0) {
            break;
        }
        LLVMFuzzerTestOneInput(buf, n);
    }

    size_t len = fuzz_seed(0, buf, sizeof(buf));
    for (unsigned long i = 0; i < iterations; i++) {
        /* Restart from a clean seed periodically so the corpus does not drift
         * into pure noise and stay there. */
        if (random_below(64) == 0) {
            len = fuzz_seed(random_below(8), buf, sizeof(buf));
            if (len == 0) {
                len = fuzz_seed(0, buf, sizeof(buf));
            }
        }
        len = mutate(buf, len);
        if (len > MAX_INPUT) {
            len = MAX_INPUT;
        }

        FILE *f = fopen(crash_path, "wb");
        if (f) {
            fwrite(buf, 1, len, f);
            fclose(f);
        }

        LLVMFuzzerTestOneInput(buf, len);
    }

    printf("%lu iterations, no crash (inputs reproducible with --seed)\n",
           iterations);
    remove(crash_path);
    return 0;
}
