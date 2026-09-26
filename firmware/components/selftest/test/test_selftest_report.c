/* Host tests for the self-test report.
 *
 * The report is the thing that decides whether a board is accepted, and its
 * text output is a parsing contract with tools/board_test.py. Both are worth
 * testing without hardware, because the failure mode is silent: a report that
 * loses a FAIL, or emits JSON a parser rejects, still looks like a working
 * test rig right up until a bad board ships.
 *
 * The overflow case is the one that matters most. SELFTEST_MAX is a fixed
 * array; a 25th result must not be able to turn a failing board into a passing
 * one by falling off the end. */
#include <stdio.h>
#include <string.h>

#include "selftest.h"

static int checks = 0, fails = 0;
#define CHECK(c, ...) do { checks++; if (!(c)) { \
    fails++; printf("  FAIL %s:%d  ", __FILE__, __LINE__); printf(__VA_ARGS__); \
    printf("\n"); } } while (0)

static void test_tally(void)
{
    selftest_report_t r;
    selftest_report_init(&r);

    CHECK(r.count == 0, "fresh report should be empty, got %u", (unsigned)r.count);

    selftest_report_add(&r, "a", SELFTEST_PASS, "fine");
    selftest_report_add(&r, "b", SELFTEST_FAIL, "read 0x%02X", 0xFF);
    selftest_report_add(&r, "c", SELFTEST_SKIP, "no cable");
    selftest_report_add(&r, "d", SELFTEST_INFO, "%d cores", 2);

    CHECK(r.count == 4, "count should be 4, got %u", (unsigned)r.count);
    CHECK(r.pass == 1 && r.fail == 1 && r.skip == 1 && r.info == 1,
          "tally wrong: %u/%u/%u/%u", (unsigned)r.pass, (unsigned)r.fail,
          (unsigned)r.skip, (unsigned)r.info);
    CHECK(strcmp(r.results[1].detail, "read 0xFF") == 0,
          "printf formatting lost: %s", r.results[1].detail);
}

static void test_overflow_never_hides_a_failure(void)
{
    selftest_report_t r;
    selftest_report_init(&r);

    for (int i = 0; i < SELFTEST_MAX; i++) {
        CHECK(selftest_report_add(&r, "filler", SELFTEST_PASS, "%d", i),
              "add %d should have fitted", i);
    }
    CHECK(r.count == SELFTEST_MAX, "should be full at %d", SELFTEST_MAX);

    /* One more PASS is allowed to vanish - it changes no decision. */
    CHECK(!selftest_report_add(&r, "extra", SELFTEST_PASS, "dropped"),
          "a full report must refuse further results");
    CHECK(r.pass == SELFTEST_MAX, "a dropped PASS must not be counted");

    /* A FAIL must not. */
    const size_t before = r.fail;
    CHECK(!selftest_report_add(&r, "extra", SELFTEST_FAIL, "dropped"),
          "a full report must refuse further results");
    CHECK(r.fail == before + 1,
          "a dropped FAIL must still be tallied, or a bad board reads as clean");
}

static void test_detail_truncates_rather_than_overflowing(void)
{
    selftest_report_t r;
    selftest_report_init(&r);

    char big[SELFTEST_DETAIL * 3];
    memset(big, 'x', sizeof(big) - 1);
    big[sizeof(big) - 1] = '\0';

    selftest_report_add(&r, "long", SELFTEST_INFO, "%s", big);
    CHECK(strlen(r.results[0].detail) == SELFTEST_DETAIL - 1,
          "detail should be truncated to %d bytes, got %u",
          SELFTEST_DETAIL - 1, (unsigned)strlen(r.results[0].detail));
}

static void test_json_shape(void)
{
    selftest_report_t r;
    selftest_report_init(&r);
    selftest_report_add(&r, "eth.versionr", SELFTEST_PASS, "0x04");
    selftest_report_add(&r, "can.loopback", SELFTEST_FAIL, "nothing received");

    char buf[512];
    const size_t need = selftest_report_json(&r, buf, sizeof(buf));

    CHECK(need == strlen(buf), "return value %u should be the string length %u",
          (unsigned)need, (unsigned)strlen(buf));
    CHECK(strstr(buf, "\"schema\":\"" SELFTEST_SCHEMA "\"") != NULL,
          "schema missing: %s", buf);
    CHECK(strstr(buf, "\"name\":\"eth.versionr\",\"verdict\":\"PASS\"") != NULL,
          "first result malformed: %s", buf);
    CHECK(strstr(buf, "\"pass\":1,\"fail\":1,\"skip\":0,\"info\":0") != NULL,
          "summary malformed: %s", buf);
}

static void test_json_escapes(void)
{
    selftest_report_t r;
    selftest_report_init(&r);
    /* A vendor string or a register dump can contain either of these, and one
     * unescaped byte makes the whole record unparseable at the host. */
    selftest_report_add(&r, "quoted", SELFTEST_INFO, "he said \"04\" \\ done\n");

    char buf[256];
    selftest_report_json(&r, buf, sizeof(buf));
    CHECK(strstr(buf, "\\\"04\\\"") != NULL, "quote not escaped: %s", buf);
    CHECK(strstr(buf, "\\\\ done") != NULL, "backslash not escaped: %s", buf);
    CHECK(strstr(buf, "\\n\"}") != NULL, "newline not escaped: %s", buf);
}

static void test_json_reports_truncation(void)
{
    selftest_report_t r;
    selftest_report_init(&r);
    for (int i = 0; i < 10; i++) {
        selftest_report_add(&r, "a_reasonably_long_test_name", SELFTEST_INFO,
                            "a reasonably long detail string for entry %d", i);
    }

    char small[64];
    const size_t need = selftest_report_json(&r, small, sizeof(small));
    CHECK(need >= sizeof(small),
          "should report the full length %u needed, not the truncated one",
          (unsigned)need);
    CHECK(small[sizeof(small) - 1] == '\0', "output must stay NUL-terminated");
}

static void test_verdict_strings(void)
{
    CHECK(strcmp(selftest_verdict_str(SELFTEST_PASS), "PASS") == 0, "PASS");
    CHECK(strcmp(selftest_verdict_str(SELFTEST_FAIL), "FAIL") == 0, "FAIL");
    CHECK(strcmp(selftest_verdict_str(SELFTEST_SKIP), "SKIP") == 0, "SKIP");
    CHECK(strcmp(selftest_verdict_str(SELFTEST_INFO), "INFO") == 0, "INFO");
}

int main(void)
{
    test_tally();
    test_overflow_never_hides_a_failure();
    test_detail_truncates_rather_than_overflowing();
    test_json_shape();
    test_json_escapes();
    test_json_reports_truncation();
    test_verdict_strings();

    printf("%s: %d checks, %d failures\n", fails ? "FAIL" : "ok", checks, fails);
    return fails ? 1 : 0;
}
