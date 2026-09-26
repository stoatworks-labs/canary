/*
 * diag — logging and crash diagnostics for a headless node.
 *
 * A desk or a laptop can rotate log files and write a JSON crash report on the
 * way down. A DMX node on a truss can do neither: it has no screen, no
 * operator, a few hundred KB of RAM, and flash that wears out if you write to
 * it. When it dies it does not unwind — it reboots, and everything in RAM is
 * gone.
 *
 * So the shape is different from the rest of the fleet, on purpose:
 *
 *   1. A bounded **in-RAM log ring**, tee'd off esp_log. It survives right up
 *      to the reset, and is served over HTTP rather than written to flash.
 *   2. A **coredump written to its own flash partition** by ESP-IDF's panic
 *      handler. This is the machine-readable crash artefact: registers, the
 *      faulting task and a full backtrace, decodable offline with
 *      espcoredump.py against the matching .elf.
 *   3. A **crash summary kept in NVS**, so that after the coredump has been
 *      downloaded and erased there is still a record that the node panicked,
 *      when, and where.
 *
 * The reset reason matters more than anything else here: a brownout, a task
 * watchdog and a panic look identical from the far end of a DMX line, and they
 * have completely different causes.
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Identifies the document shape to anything reading it later. Shared with the
 * rest of the fleet — see docs/diagnostics.md in any of the repos. */
#define DIAG_SCHEMA "stoatworks.diagnostics/1"

/*
 * Install the log tap and record boot state.
 *
 * Call first in app_main, before anything that can fail: a fault during
 * bring-up is the most likely fault there is, and this is what records it.
 * Also promotes the previous boot's coredump (if any) to a stored summary.
 */
esp_err_t diag_init(void);

/*
 * Build the diagnostics bundle as a JSON string.
 *
 * Caller owns the returned buffer and must free() it. Returns NULL if it could
 * not be built, which on a node with a full heap is a real possibility — the
 * caller must handle it rather than assuming.
 */
char *diag_bundle_json(void);

/* True if a coredump from a previous panic is present in flash. */
bool diag_has_coredump(void);

/* Size of the stored coredump image in bytes, or 0. */
size_t diag_coredump_size(void);

/*
 * Copy part of the stored coredump image out.
 *
 * Read in chunks: the image can be tens of kilobytes and must not be brought
 * into RAM in one piece on a node with ~200 KB free.
 */
esp_err_t diag_coredump_read(size_t offset, void *dest, size_t len);

/* Erase the stored coredump, after it has been downloaded. */
esp_err_t diag_coredump_erase(void);

#ifdef __cplusplus
}
#endif
