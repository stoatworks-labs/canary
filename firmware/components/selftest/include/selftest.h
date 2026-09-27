/*
 * Board self-test — the production and bring-up test firmware.
 *
 * Two entry points, deliberately different in what they are allowed to touch:
 *
 *   selftest_post()      Runs in the SHIPPING firmware at every boot. Reads
 *                        only things that are free and side-effect-free: chip
 *                        identity, MAC, reset reason, PD power-good. It never
 *                        claims SPI or TWAI, so it cannot change how the
 *                        product behaves. Its job is to put a line in the log
 *                        that says which board this is.
 *
 *   selftest_run_all()   Runs ONLY in the test build (-DCANARY_SELFTEST=1),
 *                        before anything else has claimed a peripheral. It
 *                        drives the SPI bus and the CAN controller directly,
 *                        so it must run first and the bridge must not run at
 *                        all in that build.
 *
 * Output is line-oriented and machine-parseable, because a person reading it on
 * a bench and tools/board_test.py reading it over USB are the same audience:
 *
 *     RESULT <name> <PASS|FAIL|SKIP|INFO> <detail>
 *     SELFTEST-END pass=<n> fail=<n> skip=<n>
 *
 * Nothing here has been run on hardware. Every limit is predicted from the
 * schematic and the datasheets; see hardware/fab/test/BENCH-BRINGUP.md.
 */
#ifndef SELFTEST_H
#define SELFTEST_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* selftest_report.c is deliberately ESP-IDF-free so the accept/reject logic
 * and the output format can be tested on a host with no toolchain. Everything
 * that needs the SDK is declared behind this guard. */
#ifdef ESP_PLATFORM
#include "esp_err.h"
#endif

#define SELFTEST_SCHEMA   "canary.selftest/1"
#define SELFTEST_MAX      24
#define SELFTEST_DETAIL   72

typedef enum {
    SELFTEST_PASS = 0,
    SELFTEST_FAIL,
    SELFTEST_SKIP,   /* could not run here - not a failure of the board */
    SELFTEST_INFO,   /* a measurement with no pass limit yet */
} selftest_verdict_t;

typedef struct {
    const char *name;                      /* stable id, e.g. "eth.versionr" */
    selftest_verdict_t verdict;
    char detail[SELFTEST_DETAIL];
} selftest_result_t;

typedef struct {
    selftest_result_t results[SELFTEST_MAX];
    size_t count;
    size_t pass, fail, skip, info;
} selftest_report_t;

/* --- pure helpers, host-testable (selftest_report.c) --------------------- */

void selftest_report_init(selftest_report_t *r);

/* Append one result. Truncates rather than overflowing, and returns false if
 * the report is full - a silently dropped FAIL is the one bug a test tool must
 * never have. */
bool selftest_report_add(selftest_report_t *r, const char *name,
                         selftest_verdict_t verdict, const char *fmt, ...)
    __attribute__((format(printf, 4, 5)));

const char *selftest_verdict_str(selftest_verdict_t v);

/* Print the report as RESULT lines plus the SELFTEST-END summary. */
void selftest_report_print(const selftest_report_t *r);

/* Serialise the report as one JSON line, for a test record keyed to a serial
 * number. Returns the number of bytes that WOULD have been written, so a
 * caller can detect truncation. */
size_t selftest_report_json(const selftest_report_t *r, char *out, size_t len);

/* --- the tests themselves ----------------------------------------------- */
#ifdef ESP_PLATFORM

/* Cheap, non-invasive identity checks. Safe in the shipping firmware. */
void selftest_post(selftest_report_t *r);

/* Everything, including tests that claim SPI2 and TWAI. Test build only.
 * Releases both peripherals before returning. */
void selftest_run_all(selftest_report_t *r);

/* Individual tests, exposed so the console can re-run one at a time. */
void selftest_eth(selftest_report_t *r);       /* claims and releases SPI2  */
void selftest_can_loopback(selftest_report_t *r); /* claims and releases TWAI */
void selftest_leds(selftest_report_t *r);

/* Blocking line-oriented command console. Never returns. Test build only. */
esp_err_t selftest_console_start(void);

#endif /* ESP_PLATFORM */

#endif /* SELFTEST_H */
