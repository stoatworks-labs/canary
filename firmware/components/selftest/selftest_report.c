/*
 * Self-test report accumulation and formatting.
 *
 * Deliberately free of ESP-IDF: this is the part that decides whether a board
 * passed, and it is worth being able to test that decision on a host with no
 * hardware and no toolchain. test/test_selftest_report.c does exactly that.
 *
 * The output format is the contract with tools/board_test.py. If you change a
 * line here, change the parser and its tests in the same commit.
 */
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "selftest.h"

void selftest_report_init(selftest_report_t *r)
{
    memset(r, 0, sizeof(*r));
}

const char *selftest_verdict_str(selftest_verdict_t v)
{
    switch (v) {
    case SELFTEST_PASS: return "PASS";
    case SELFTEST_FAIL: return "FAIL";
    case SELFTEST_SKIP: return "SKIP";
    case SELFTEST_INFO: return "INFO";
    }
    return "????";
}

bool selftest_report_add(selftest_report_t *r, const char *name,
                         selftest_verdict_t verdict, const char *fmt, ...)
{
    if (r->count >= SELFTEST_MAX) {
        /* Count it anyway so the summary cannot claim a clean sweep it did
         * not have. A dropped FAIL that also vanishes from the tally is how a
         * bad board ships. */
        if (verdict == SELFTEST_FAIL) {
            r->fail++;
        }
        return false;
    }

    selftest_result_t *slot = &r->results[r->count++];
    slot->name = name;
    slot->verdict = verdict;

    va_list ap;
    va_start(ap, fmt);
    vsnprintf(slot->detail, sizeof(slot->detail), fmt, ap);
    va_end(ap);

    switch (verdict) {
    case SELFTEST_PASS: r->pass++; break;
    case SELFTEST_FAIL: r->fail++; break;
    case SELFTEST_SKIP: r->skip++; break;
    case SELFTEST_INFO: r->info++; break;
    }
    return true;
}

void selftest_report_print(const selftest_report_t *r)
{
    for (size_t i = 0; i < r->count; i++) {
        printf("RESULT %s %s %s\n", r->results[i].name,
               selftest_verdict_str(r->results[i].verdict),
               r->results[i].detail);
    }
    printf("SELFTEST-END pass=%u fail=%u skip=%u info=%u\n",
           (unsigned)r->pass, (unsigned)r->fail,
           (unsigned)r->skip, (unsigned)r->info);
    fflush(stdout);
}

/* Minimal JSON string escaping. Detail strings are ours, but a register dump
 * or a vendor string could still contain a quote or a backslash, and one
 * unescaped byte makes the whole record unparseable. */
static size_t append_escaped(char *out, size_t len, size_t at, const char *s)
{
    for (; *s; s++) {
        const char *rep = NULL;
        char buf[8];
        switch (*s) {
        case '"':  rep = "\\\""; break;
        case '\\': rep = "\\\\"; break;
        case '\n': rep = "\\n";  break;
        case '\r': rep = "\\r";  break;
        case '\t': rep = "\\t";  break;
        default:
            if ((unsigned char)*s < 0x20) {
                snprintf(buf, sizeof(buf), "\\u%04x", (unsigned char)*s);
                rep = buf;
            }
            break;
        }
        if (rep) {
            for (const char *p = rep; *p; p++) {
                if (at < len) { out[at] = *p; }
                at++;
            }
        } else {
            if (at < len) { out[at] = *s; }
            at++;
        }
    }
    return at;
}

static size_t append(char *out, size_t len, size_t at, const char *s)
{
    for (; *s; s++) {
        if (at < len) { out[at] = *s; }
        at++;
    }
    return at;
}

size_t selftest_report_json(const selftest_report_t *r, char *out, size_t len)
{
    char num[64];
    size_t at = 0;

    at = append(out, len, at, "{\"schema\":\"" SELFTEST_SCHEMA "\",\"results\":[");
    for (size_t i = 0; i < r->count; i++) {
        if (i) { at = append(out, len, at, ","); }
        at = append(out, len, at, "{\"name\":\"");
        at = append_escaped(out, len, at, r->results[i].name);
        at = append(out, len, at, "\",\"verdict\":\"");
        at = append(out, len, at, selftest_verdict_str(r->results[i].verdict));
        at = append(out, len, at, "\",\"detail\":\"");
        at = append_escaped(out, len, at, r->results[i].detail);
        at = append(out, len, at, "\"}");
    }
    snprintf(num, sizeof(num), "],\"pass\":%u,\"fail\":%u,\"skip\":%u,\"info\":%u}",
             (unsigned)r->pass, (unsigned)r->fail,
             (unsigned)r->skip, (unsigned)r->info);
    at = append(out, len, at, num);

    if (len) {
        out[at < len ? at : len - 1] = '\0';
    }
    return at;
}
