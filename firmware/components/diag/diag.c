#include "diag.h"

#include <inttypes.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"
#include "esp_app_desc.h"
#include "esp_chip_info.h"
#include "esp_core_dump.h"
#include "esp_flash.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs.h"
#include "nvs_flash.h"

static const char *TAG = "diag";

/* ---------------------------------------------------------------- log ring */

/*
 * 48 x 160 bytes = ~7.7 KB of DRAM. Sized to cover a full bring-up sequence
 * (I2C, PoE, Ethernet, WiFi, DMX, Art-Net, HTTP) so that a node which dies
 * during boot still shows how far it got, without taking a bite out of the
 * heap that the LWIP and HTTP buffers need.
 */
#define DIAG_RING_LINES 48
#define DIAG_LINE_LEN   160

static char s_ring[DIAG_RING_LINES][DIAG_LINE_LEN];
static size_t s_ring_next;  /* next slot to write */
static size_t s_ring_count; /* lines held, <= DIAG_RING_LINES */
static portMUX_TYPE s_ring_mux = portMUX_INITIALIZER_UNLOCKED;
static vprintf_like_t s_prev_vprintf;

/* Strip the ANSI colour codes esp_log emits and any trailing newline, so the
 * ring holds text a browser can show and a person can read.
 *
 * dest may alias src: the write index never runs ahead of the read index, so
 * in-place is safe. diag_vprintf depends on that to keep one buffer instead of
 * two — see the stack note there. */
static void sanitise(char *dest, size_t dest_len, const char *src)
{
    size_t o = 0;
    for (size_t i = 0; src[i] != '\0' && o + 1 < dest_len; i++) {
        if (src[i] == '\033') {
            /* Skip an escape sequence up to and including its final letter. */
            while (src[i] != '\0' && src[i] != 'm') i++;
            if (src[i] == '\0') break;
            continue;
        }
        if (src[i] == '\r' || src[i] == '\n') continue;
        dest[o++] = src[i];
    }
    dest[o] = '\0';
}

static void ring_push(const char *line)
{
    if (line[0] == '\0') return;

    portENTER_CRITICAL(&s_ring_mux);
    strncpy(s_ring[s_ring_next], line, DIAG_LINE_LEN - 1);
    s_ring[s_ring_next][DIAG_LINE_LEN - 1] = '\0';
    s_ring_next = (s_ring_next + 1) % DIAG_RING_LINES;
    if (s_ring_count < DIAG_RING_LINES) s_ring_count++;
    portEXIT_CRITICAL(&s_ring_mux);
}

/*
 * The tap itself.
 *
 * va_copy is not optional: vsnprintf consumes the list, so passing the
 * original on to the real vprintf afterwards would read past the end of the
 * arguments. That is the classic way a logging tap turns into a crash of its
 * own.
 */
static int diag_vprintf(const char *fmt, va_list ap)
{
    va_list copy;
    va_copy(copy, ap);

    /*
     * ONE buffer, sanitised in place.
     *
     * This is the GLOBAL esp_log hook, so it runs on whichever task happens to
     * be logging. Two 160-byte buffers plus vsnprintf's own frame put a ~350
     * byte tax on EVERY logging task's stack, including main_task's, which was
     * overflowing during bring-up when the image was first booted under QEMU
     * (firmware/qemu). Halving this was not on its own what stopped that
     * overflow — CONFIG_ESP_MAIN_TASK_STACK_SIZE=6144 was — but a global hook
     * has no business costing that much stack on a task it knows nothing about.
     */
    char line[DIAG_LINE_LEN];
    vsnprintf(line, sizeof(line), fmt, copy);
    va_end(copy);

    sanitise(line, sizeof(line), line);
    ring_push(line);

    return s_prev_vprintf ? s_prev_vprintf(fmt, ap) : vprintf(fmt, ap);
}

/* ------------------------------------------------------------ reset reason */

static const char *reset_reason_name(esp_reset_reason_t reason)
{
    switch (reason) {
        case ESP_RST_POWERON:  return "power-on";
        case ESP_RST_EXT:      return "external-pin";
        case ESP_RST_SW:       return "software";
        case ESP_RST_PANIC:    return "panic";
        case ESP_RST_INT_WDT:  return "interrupt-watchdog";
        case ESP_RST_TASK_WDT: return "task-watchdog";
        case ESP_RST_WDT:      return "other-watchdog";
        case ESP_RST_DEEPSLEEP:return "deep-sleep-wake";
        case ESP_RST_BROWNOUT: return "brownout";
        case ESP_RST_SDIO:     return "sdio";
        default:               return "unknown";
    }
}

/* --------------------------------------------------------- crash summaries */

#define DIAG_NVS_NAMESPACE "diag"
#define DIAG_NVS_KEY_LAST  "last_crash"

/*
 * A short, human-readable summary of the last panic, kept in NVS.
 *
 * The coredump itself is the useful artefact, but it gets erased once it has
 * been collected — and it is large. This is the breadcrumb that outlives it,
 * so a node that panicked three weeks ago can still say so.
 */
static void store_crash_summary(const char *summary)
{
    nvs_handle_t nvs;
    if (nvs_open(DIAG_NVS_NAMESPACE, NVS_READWRITE, &nvs) != ESP_OK) return;
    nvs_set_str(nvs, DIAG_NVS_KEY_LAST, summary);
    nvs_commit(nvs);
    nvs_close(nvs);
}

static char *load_crash_summary(void)
{
    nvs_handle_t nvs;
    if (nvs_open(DIAG_NVS_NAMESPACE, NVS_READONLY, &nvs) != ESP_OK) return NULL;

    size_t len = 0;
    if (nvs_get_str(nvs, DIAG_NVS_KEY_LAST, NULL, &len) != ESP_OK || len == 0) {
        nvs_close(nvs);
        return NULL;
    }

    char *out = malloc(len);
    if (out && nvs_get_str(nvs, DIAG_NVS_KEY_LAST, out, &len) != ESP_OK) {
        free(out);
        out = NULL;
    }
    nvs_close(nvs);
    return out;
}

/*
 * Promote a coredump left by the previous boot into a stored summary.
 *
 * esp_core_dump_get_summary gives the faulting PC, the task that faulted and
 * a backtrace — which is enough to name the bug without a serial console
 * anywhere near the truss.
 */
#if CONFIG_ESP_COREDUMP_ENABLE_TO_FLASH && CONFIG_ESP_COREDUMP_DATA_FORMAT_ELF
static void promote_coredump(void)
{
    if (!diag_has_coredump()) return;

    /* Heap, not stack: esp_core_dump_summary_t is over a kilobyte and this
     * runs during bring-up on the main task. */
    esp_core_dump_summary_t *summary = calloc(1, sizeof(esp_core_dump_summary_t));
    if (!summary) return;

    if (esp_core_dump_get_summary(summary) == ESP_OK) {
        char text[192];
        snprintf(text, sizeof(text),
                 "task=%s pc=0x%08" PRIx32 " depth=%" PRIu32 " app=%.8s",
                 summary->exc_task, summary->exc_pc,
                 summary->exc_bt_info.depth, summary->app_elf_sha256);
        store_crash_summary(text);
        ESP_LOGE(TAG, "previous boot panicked: %s", text);
        /* That endpoint did not exist when this line was written - there was
         * no server for it to be on. components/webui serves it now, on the
         * USB link, so the line is finally true; it says "over USB" because
         * on an image without the USB network device there is still nowhere
         * to fetch it from, and esp-coredump over serial is the answer. */
        ESP_LOGE(TAG, "coredump kept in flash (%u bytes) — fetch it over USB "
                      "from /api/diagnostics/coredump, or with esp-coredump "
                      "against the .elf that was flashed",
                 (unsigned)diag_coredump_size());
    }

    free(summary);
}
#else
/* Summaries need the ELF coredump format. Without it the component still
 * builds and still gives you the log ring and the reset reason — it just
 * cannot name the faulting task. */
static void promote_coredump(void) {}
#endif

/* -------------------------------------------------------------------- init */

esp_err_t diag_init(void)
{
    s_prev_vprintf = esp_log_set_vprintf(diag_vprintf);

    const esp_app_desc_t *app = esp_app_get_description();
    const esp_reset_reason_t reason = esp_reset_reason();

    ESP_LOGI(TAG, "logging started app=%s version=%s idf=%s built=%s %s",
             app->project_name, app->version, app->idf_ver, app->date, app->time);
    ESP_LOGI(TAG, "reset reason: %s", reset_reason_name(reason));
    ESP_LOGI(TAG, "heap: %u free, %u minimum ever",
             (unsigned)esp_get_free_heap_size(),
             (unsigned)esp_get_minimum_free_heap_size());

    /* A brownout on a PoE node almost always means the power budget, not the
     * firmware — say so here rather than leaving it to be rediscovered. */
    if (reason == ESP_RST_BROWNOUT)
        ESP_LOGW(TAG, "brownout reset — check the PoE budget and the 3V3 rail, "
                      "not the firmware");

    promote_coredump();
    return ESP_OK;
}

/* ---------------------------------------------------------------- coredump */

bool diag_has_coredump(void)
{
    size_t addr = 0, size = 0;
    return esp_core_dump_image_get(&addr, &size) == ESP_OK && size > 0;
}

size_t diag_coredump_size(void)
{
    size_t addr = 0, size = 0;
    if (esp_core_dump_image_get(&addr, &size) != ESP_OK) return 0;
    return size;
}

esp_err_t diag_coredump_read(size_t offset, void *dest, size_t len)
{
    size_t addr = 0, size = 0;
    esp_err_t err = esp_core_dump_image_get(&addr, &size);
    if (err != ESP_OK) return err;
    if (offset >= size) return ESP_ERR_INVALID_ARG;
    if (offset + len > size) len = size - offset;

    const esp_partition_t *part = esp_partition_find_first(
        ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_DATA_COREDUMP, NULL);
    if (!part) return ESP_ERR_NOT_FOUND;

    return esp_partition_read(part, offset, dest, len);
}

esp_err_t diag_coredump_erase(void)
{
    return esp_core_dump_image_erase();
}

/* ------------------------------------------------------------------ bundle */

char *diag_bundle_json(void)
{
    cJSON *root = cJSON_CreateObject();
    if (!root) return NULL;

    const esp_app_desc_t *app = esp_app_get_description();

    cJSON_AddStringToObject(root, "schema", DIAG_SCHEMA);
    cJSON_AddStringToObject(root, "kind", "diagnostics-bundle");

    cJSON *a = cJSON_AddObjectToObject(root, "app");
    cJSON_AddStringToObject(a, "name", app->project_name);
    cJSON_AddStringToObject(a, "version", app->version);
    cJSON_AddStringToObject(a, "idf_version", app->idf_ver);
    cJSON_AddStringToObject(a, "built", app->date);
    /* The ELF SHA is the build identity that matters: espcoredump.py needs the
     * matching .elf, and this is how you know which one that is. */
    char sha[17];
    for (int i = 0; i < 8; i++) snprintf(sha + i * 2, 3, "%02x", app->app_elf_sha256[i]);
    cJSON_AddStringToObject(a, "elf_sha256", sha);

    esp_chip_info_t chip;
    esp_chip_info(&chip);
    uint32_t flash_size = 0;
    esp_flash_get_size(NULL, &flash_size);
    uint8_t mac[6] = {0};
    esp_read_mac(mac, ESP_MAC_ETH);
    char mac_text[18];
    snprintf(mac_text, sizeof(mac_text), "%02x:%02x:%02x:%02x:%02x:%02x",
             mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);

    cJSON *p = cJSON_AddObjectToObject(root, "platform");
    cJSON_AddNumberToObject(p, "chip_model", chip.model);
    cJSON_AddNumberToObject(p, "chip_revision", chip.revision);
    cJSON_AddNumberToObject(p, "cores", chip.cores);
    cJSON_AddNumberToObject(p, "flash_bytes", flash_size);
    cJSON_AddStringToObject(p, "eth_mac", mac_text);

    cJSON *pr = cJSON_AddObjectToObject(root, "process");
    cJSON_AddNumberToObject(pr, "uptime_seconds", (double)(esp_timer_get_time() / 1000000));
    cJSON_AddNumberToObject(pr, "free_heap", esp_get_free_heap_size());
    cJSON_AddNumberToObject(pr, "min_free_heap", esp_get_minimum_free_heap_size());
    cJSON_AddNumberToObject(pr, "largest_free_block",
                            heap_caps_get_largest_free_block(MALLOC_CAP_DEFAULT));
    cJSON_AddNumberToObject(pr, "tasks", uxTaskGetNumberOfTasks());
    cJSON_AddStringToObject(pr, "reset_reason", reset_reason_name(esp_reset_reason()));

    cJSON *c = cJSON_AddObjectToObject(root, "crash");
    cJSON_AddBoolToObject(c, "coredump_present", diag_has_coredump());
    cJSON_AddNumberToObject(c, "coredump_bytes", diag_coredump_size());
    char *summary = load_crash_summary();
    if (summary) {
        cJSON_AddStringToObject(c, "last_summary", summary);
        free(summary);
    } else {
        cJSON_AddNullToObject(c, "last_summary");
    }

    cJSON *log = cJSON_AddArrayToObject(root, "recent_log");
    portENTER_CRITICAL(&s_ring_mux);
    const size_t count = s_ring_count;
    const size_t start = (s_ring_next + DIAG_RING_LINES - count) % DIAG_RING_LINES;
    portEXIT_CRITICAL(&s_ring_mux);
    for (size_t i = 0; i < count; i++)
        cJSON_AddItemToArray(log,
            cJSON_CreateString(s_ring[(start + i) % DIAG_RING_LINES]));

    /* Unformatted: a node has no spare heap to hold a pretty-printed copy, and
     * whatever fetches this can format it. */
    char *out = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    return out;
}
