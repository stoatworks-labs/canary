/* On-device configuration UI. See include/webui.h. */
#include "webui.h"

#include "esp_log.h"

static const char *TAG = "webui";

#if !CONFIG_TINYUSB_NET_MODE_NCM

/* No USB network device in this image, so there is nowhere for the UI to live.
 * It is deliberately NOT offered on the LAN jack - see the header. */
esp_err_t webui_start(void)
{
    ESP_LOGD(TAG, "not built in (no USB network device)");
    return ESP_ERR_NOT_SUPPORTED;
}

#else /* CONFIG_TINYUSB_NET_MODE_NCM */

#include <stdlib.h>
#include <string.h>

#include "bridge.h"
#include "cJSON.h"
#include "config_store.h"
#include "dbcan.h"
#include "diag.h"
#include "esp_app_desc.h"
#include "esp_check.h"
#include "esp_http_server.h"
#include "esp_netif.h"   /* esp_ip4_addr_t, IPSTR/IP2STR */
#include "esp_ota_ops.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lwip/inet.h"
#include "lwip/sockets.h"
#include "net.h"
#include "usbnet.h"

/* The page, embedded from www/index.html by CMakeLists.txt. It is deliberately
 * one self-contained file with no external references: the unit is at the end
 * of a USB cable and has no route to the internet, so a stylesheet or a font
 * from a CDN would simply never load. */
extern const uint8_t index_html_start[] asm("_binary_index_html_start");
extern const uint8_t index_html_end[]   asm("_binary_index_html_end");

#define OTA_CHUNK 4096

static httpd_handle_t s_httpd;

/* ---- who is allowed to talk to us ---------------------------------------- */

/* Called just after accept() and before any data is read. Anything other than
 * ESP_OK closes the socket immediately. */
static esp_err_t webui_open(httpd_handle_t hd, int sockfd)
{
    (void)hd;

    /* No host, no service. Checked again here rather than relying on the
     * watcher having stopped the server, because the link can drop between
     * accept() and this call. */
    const uint32_t our_ip = usbnet_local_ip();
    const uint32_t mask = usbnet_netmask();
    if (!usbnet_link_up() || our_ip == 0 || mask == 0) {
        return ESP_FAIL;
    }

    struct sockaddr_storage peer;
    socklen_t len = sizeof(peer);
    if (getpeername(sockfd, (struct sockaddr *)&peer, &len) != 0) {
        return ESP_FAIL;
    }
    /* With CONFIG_LWIP_IPV6 esp_http_server listens on a dual-stack PF_INET6
     * socket, so an IPv4 client - i.e. every client, the USB host included -
     * arrives as ::ffff:a.b.c.d. Checking only for AF_INET refused all of them
     * and reset every connection. Unwrap the mapped form; real IPv6 peers are
     * still refused, because the USB link is IPv4 by design. */
    uint32_t from;
    if (peer.ss_family == AF_INET) {
        from = ntohl(((struct sockaddr_in *)&peer)->sin_addr.s_addr);
#if CONFIG_LWIP_IPV6
    } else if (peer.ss_family == AF_INET6) {
        const uint32_t *w = ((struct sockaddr_in6 *)&peer)->sin6_addr.un.u32_addr;
        if (w[0] != 0 || w[1] != 0 || w[2] != PP_HTONL(0x0000FFFFUL)) {
            return ESP_FAIL;
        }
        from = ntohl(w[3]);
#endif
    } else {
        return ESP_FAIL;
    }

    if ((from & mask) != (our_ip & mask)) {
        /* Someone on the LAN found the port. They should not have been able
         * to - the server is only up while a USB host is attached - so say so
         * loudly rather than just dropping it. */
        const esp_ip4_addr_t a = { .addr = htonl(from) };
        ESP_LOGW(TAG, "refused a connection from " IPSTR
                      " - the UI is reachable over USB only", IP2STR(&a));
        return ESP_FAIL;
    }
    return ESP_OK;
}

/* ---- helpers ------------------------------------------------------------- */

static esp_err_t send_json(httpd_req_t *req, cJSON *doc)
{
    char *text = cJSON_PrintUnformatted(doc);
    cJSON_Delete(doc);
    if (text == NULL) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "out of memory");
        return ESP_FAIL;
    }
    httpd_resp_set_type(req, "application/json");
    const esp_err_t err = httpd_resp_sendstr(req, text);
    free(text);
    return err;
}

static esp_err_t send_error(httpd_req_t *req, httpd_err_code_t code,
                            const char *why)
{
    ESP_LOGW(TAG, "%s: %s", req->uri, why);
    httpd_resp_send_err(req, code, why);
    return ESP_FAIL;
}

/* Read a whole request body. Bounded: this is network input on a socket with
 * no authentication beyond "you are on the USB cable", and the config document
 * is a few hundred bytes. */
static char *read_body(httpd_req_t *req, size_t limit)
{
    if (req->content_len == 0 || req->content_len > limit) {
        return NULL;
    }
    char *buf = malloc(req->content_len + 1);
    if (buf == NULL) {
        return NULL;
    }
    size_t got = 0;
    while (got < req->content_len) {
        const int n = httpd_req_recv(req, buf + got, req->content_len - got);
        if (n <= 0) {
            free(buf);
            return NULL;
        }
        got += (size_t)n;
    }
    buf[got] = '\0';
    return buf;
}

static void add_ip(cJSON *parent, const char *name, uint32_t host_order)
{
    char text[16];
    const esp_ip4_addr_t a = { .addr = htonl(host_order) };
    snprintf(text, sizeof(text), IPSTR, IP2STR(&a));
    cJSON_AddStringToObject(parent, name, host_order ? text : "");
}

/* ---- GET / --------------------------------------------------------------- */

static esp_err_t page_get(httpd_req_t *req)
{
    httpd_resp_set_type(req, "text/html");
    return httpd_resp_send(req, (const char *)index_html_start,
                           index_html_end - index_html_start - 1);
}

/* ---- GET /api/status ----------------------------------------------------- */

static esp_err_t status_get(httpd_req_t *req)
{
    cJSON *doc = cJSON_CreateObject();
    if (doc == NULL) {
        return send_error(req, HTTPD_500_INTERNAL_SERVER_ERROR, "out of memory");
    }

    const esp_app_desc_t *app = esp_app_get_description();
    cJSON_AddStringToObject(doc, "version", app->version);
    cJSON_AddStringToObject(doc, "idf", app->idf_ver);
    cJSON_AddStringToObject(doc, "built", app->date);
    cJSON_AddNumberToObject(doc, "uptime_s",
                            (double)(esp_timer_get_time() / 1000000));
    cJSON_AddNumberToObject(doc, "heap_free", (double)esp_get_free_heap_size());

    cJSON *eth = cJSON_AddObjectToObject(doc, "eth");
    cJSON_AddBoolToObject(eth, "link", net_link_up());
    add_ip(eth, "ip", net_local_ip());
    cJSON_AddBoolToObject(eth, "link_local", net_ip_is_link_local());

    cJSON *usb = cJSON_AddObjectToObject(doc, "usb");
    cJSON_AddBoolToObject(usb, "link", usbnet_link_up());
    add_ip(usb, "ip", usbnet_local_ip());
    add_ip(usb, "host_ip", usbnet_host_ip());

    cJSON *r1 = cJSON_AddObjectToObject(doc, "r1");
    cJSON_AddBoolToObject(r1, "connected", bridge_client_connected());

    cJSON *can = cJSON_AddObjectToObject(doc, "can");
    const dbcan_bus_state_t bus = dbcan_bus_state();
    cJSON_AddStringToObject(can, "state",
        bus == DBCAN_BUS_RUNNING ? "running" :
        bus == DBCAN_BUS_BUS_OFF ? "bus-off" : "stopped");
    cJSON_AddNumberToObject(can, "busload", (double)dbcan_busload());

    cJSON_AddBoolToObject(doc, "coredump", diag_has_coredump());
    cJSON_AddNumberToObject(doc, "coredump_bytes",
                            (double)diag_coredump_size());
    return send_json(req, doc);
}

/* ---- GET/POST /api/config ------------------------------------------------ */

static esp_err_t config_get(httpd_req_t *req)
{
    cfg_t cfg;
    cfg_load(&cfg);

    cJSON *doc = cJSON_CreateObject();
    if (doc == NULL) {
        return send_error(req, HTTPD_500_INTERNAL_SERVER_ERROR, "out of memory");
    }
    cJSON_AddStringToObject(doc, "hostname", cfg.hostname);
    cJSON_AddNumberToObject(doc, "base_port", cfg.base_port);
    cJSON_AddNumberToObject(doc, "socket_count", cfg.socket_count);
    cJSON_AddStringToObject(doc, "eth_mode",
                            cfg.eth_mode == CFG_IPV4_STATIC ? "static" : "dhcp");
    add_ip(doc, "eth_ip", cfg.eth_ip);
    add_ip(doc, "eth_netmask", cfg.eth_netmask);
    add_ip(doc, "eth_gw", cfg.eth_gw);
    cJSON_AddBoolToObject(doc, "stored", cfg_is_stored());
    cJSON_AddNumberToObject(doc, "hostname_max", CFG_HOSTNAME_MAX);
    return send_json(req, doc);
}

/* Parse a dotted quad into host byte order. An empty string means "unset",
 * which is how the form says "no gateway". */
static bool parse_ip(const cJSON *item, uint32_t *out)
{
    if (!cJSON_IsString(item)) {
        return false;
    }
    const char *text = item->valuestring;
    if (text[0] == '\0') {
        *out = 0;
        return true;
    }
    struct in_addr addr;
    if (inet_pton(AF_INET, text, &addr) != 1) {
        return false;
    }
    *out = ntohl(addr.s_addr);
    return true;
}

static esp_err_t config_post(httpd_req_t *req)
{
    char *body = read_body(req, 1024);
    if (body == NULL) {
        return send_error(req, HTTPD_400_BAD_REQUEST, "no usable request body");
    }
    cJSON *doc = cJSON_Parse(body);
    free(body);
    if (doc == NULL) {
        return send_error(req, HTTPD_400_BAD_REQUEST, "that is not JSON");
    }

    /* Start from what is stored, so a document that omits a field leaves it
     * alone rather than silently resetting it to the factory value. */
    cfg_t cfg;
    cfg_load(&cfg);

    const cJSON *item = cJSON_GetObjectItem(doc, "hostname");
    if (cJSON_IsString(item)) {
        /* strncpy would leave the field unterminated at exactly the maximum
         * length, which cfg_validate() would then reject as "too long" - true,
         * but not what the operator typed. Refuse the over-long name here so
         * the message names the real problem. */
        if (strlen(item->valuestring) > CFG_HOSTNAME_MAX) {
            cJSON_Delete(doc);
            return send_error(req, HTTPD_400_BAD_REQUEST,
                              "host name is too long for the discovery record");
        }
        strcpy(cfg.hostname, item->valuestring);
    }
    item = cJSON_GetObjectItem(doc, "base_port");
    if (cJSON_IsNumber(item)) {
        if (item->valuedouble < 0 || item->valuedouble > 65535) {
            cJSON_Delete(doc);
            return send_error(req, HTTPD_400_BAD_REQUEST, "port out of range");
        }
        cfg.base_port = (uint16_t)item->valuedouble;
    }
    item = cJSON_GetObjectItem(doc, "socket_count");
    if (cJSON_IsNumber(item)) {
        if (item->valuedouble < 0 || item->valuedouble > 255) {
            cJSON_Delete(doc);
            return send_error(req, HTTPD_400_BAD_REQUEST, "socket count out of range");
        }
        cfg.socket_count = (uint8_t)item->valuedouble;
    }
    item = cJSON_GetObjectItem(doc, "eth_mode");
    if (cJSON_IsString(item)) {
        cfg.eth_mode = strcmp(item->valuestring, "static") == 0
                     ? CFG_IPV4_STATIC : CFG_IPV4_DHCP;
    }
    bool bad_address = false;
    item = cJSON_GetObjectItem(doc, "eth_ip");
    if (item != NULL && !parse_ip(item, &cfg.eth_ip)) bad_address = true;
    item = cJSON_GetObjectItem(doc, "eth_netmask");
    if (item != NULL && !parse_ip(item, &cfg.eth_netmask)) bad_address = true;
    item = cJSON_GetObjectItem(doc, "eth_gw");
    if (item != NULL && !parse_ip(item, &cfg.eth_gw)) bad_address = true;
    cJSON_Delete(doc);

    if (bad_address) {
        return send_error(req, HTTPD_400_BAD_REQUEST, "that is not an IPv4 address");
    }

    /* cfg_save() validates again and is the authority; this call is only so
     * the operator gets the reason rather than a bare 400. */
    const char *why = cfg_validate(&cfg);
    if (why != NULL) {
        return send_error(req, HTTPD_400_BAD_REQUEST, why);
    }
    if (cfg_save(&cfg) != ESP_OK) {
        return send_error(req, HTTPD_500_INTERNAL_SERVER_ERROR, "could not save");
    }

    cJSON *reply = cJSON_CreateObject();
    cJSON_AddBoolToObject(reply, "saved", true);
    cJSON_AddStringToObject(reply, "note", "takes effect at the next boot");
    return send_json(req, reply);
}

static esp_err_t config_reset_post(httpd_req_t *req)
{
    if (cfg_reset() != ESP_OK) {
        return send_error(req, HTTPD_500_INTERNAL_SERVER_ERROR, "could not erase");
    }
    cJSON *reply = cJSON_CreateObject();
    cJSON_AddBoolToObject(reply, "reset", true);
    cJSON_AddStringToObject(reply, "note", "factory settings at the next boot");
    return send_json(req, reply);
}

/* ---- POST /api/ota ------------------------------------------------------- */

static void reboot_task(void *arg)
{
    (void)arg;
    /* Long enough for the reply to have gone out and the socket to have
     * closed. Rebooting inside the handler leaves the browser with a dead
     * connection and no idea whether it worked. */
    vTaskDelay(pdMS_TO_TICKS(1500));
    esp_restart();
}

static esp_err_t reboot_post(httpd_req_t *req)
{
    cJSON *reply = cJSON_CreateObject();
    cJSON_AddBoolToObject(reply, "rebooting", true);
    const esp_err_t err = send_json(req, reply);
    xTaskCreate(reboot_task, "reboot", 2048, NULL, 5, NULL);
    return err;
}

static esp_err_t ota_post(httpd_req_t *req)
{
    const esp_partition_t *target = esp_ota_get_next_update_partition(NULL);
    if (target == NULL) {
        return send_error(req, HTTPD_500_INTERNAL_SERVER_ERROR,
                          "no OTA partition to write to");
    }
    if (req->content_len == 0 || req->content_len > target->size) {
        return send_error(req, HTTPD_400_BAD_REQUEST,
                          "image is empty or larger than the partition");
    }

    ESP_LOGW(TAG, "OTA: %u bytes into '%s'", (unsigned)req->content_len,
             target->label);

    esp_ota_handle_t ota;
    esp_err_t err = esp_ota_begin(target, req->content_len, &ota);
    if (err != ESP_OK) {
        return send_error(req, HTTPD_500_INTERNAL_SERVER_ERROR,
                          "could not start the update");
    }

    char *chunk = malloc(OTA_CHUNK);
    if (chunk == NULL) {
        esp_ota_abort(ota);
        return send_error(req, HTTPD_500_INTERNAL_SERVER_ERROR, "out of memory");
    }

    size_t got = 0;
    while (got < req->content_len) {
        const size_t want = (req->content_len - got) < OTA_CHUNK
                          ? (req->content_len - got) : OTA_CHUNK;
        const int n = httpd_req_recv(req, chunk, want);
        if (n <= 0) {
            /* A cable pulled halfway through. esp_ota_abort leaves the OTHER
             * partition - the one currently running - untouched, so the unit
             * still boots what it booted before. */
            free(chunk);
            esp_ota_abort(ota);
            return send_error(req, HTTPD_400_BAD_REQUEST,
                              "upload stopped before the end; nothing changed");
        }
        err = esp_ota_write(ota, chunk, (size_t)n);
        if (err != ESP_OK) {
            free(chunk);
            esp_ota_abort(ota);
            return send_error(req, HTTPD_500_INTERNAL_SERVER_ERROR,
                              "write failed; nothing changed");
        }
        got += (size_t)n;
    }
    free(chunk);

    /* esp_ota_end verifies the image. A truncated or corrupt one is refused
     * HERE, before anything points the bootloader at it. */
    err = esp_ota_end(ota);
    if (err != ESP_OK) {
        return send_error(req, HTTPD_400_BAD_REQUEST,
                          err == ESP_ERR_OTA_VALIDATE_FAILED
                          ? "that is not a valid image for this board"
                          : "the image did not verify; nothing changed");
    }
    if (esp_ota_set_boot_partition(target) != ESP_OK) {
        return send_error(req, HTTPD_500_INTERNAL_SERVER_ERROR,
                          "could not select the new image");
    }

    ESP_LOGW(TAG, "OTA written and selected; rebooting into '%s'",
             target->label);
    cJSON *reply = cJSON_CreateObject();
    cJSON_AddBoolToObject(reply, "written", true);
    cJSON_AddStringToObject(reply, "note", "rebooting into the new firmware");
    const esp_err_t sent = send_json(req, reply);
    xTaskCreate(reboot_task, "reboot", 2048, NULL, 5, NULL);
    return sent;
}

/* ---- diagnostics --------------------------------------------------------- */

static esp_err_t diagnostics_get(httpd_req_t *req)
{
    char *bundle = diag_bundle_json();
    if (bundle == NULL) {
        return send_error(req, HTTPD_500_INTERNAL_SERVER_ERROR,
                          "could not build the bundle");
    }
    httpd_resp_set_type(req, "application/json");
    httpd_resp_set_hdr(req, "Content-Disposition",
                       "attachment; filename=\"dbcanary-diagnostics.json\"");
    const esp_err_t err = httpd_resp_sendstr(req, bundle);
    free(bundle);
    return err;
}

/* The endpoint diag.c has been telling people about since it was written:
 *
 *   "coredump kept in flash (%u bytes) - fetch it from /api/diagnostics/coredump"
 *
 * Until now there was no server for it to be on. */
static esp_err_t coredump_get(httpd_req_t *req)
{
    const size_t total = diag_coredump_size();
    if (!diag_has_coredump() || total == 0) {
        return send_error(req, HTTPD_404_NOT_FOUND, "no coredump stored");
    }

    char *chunk = malloc(OTA_CHUNK);
    if (chunk == NULL) {
        return send_error(req, HTTPD_500_INTERNAL_SERVER_ERROR, "out of memory");
    }
    httpd_resp_set_type(req, "application/octet-stream");
    httpd_resp_set_hdr(req, "Content-Disposition",
                       "attachment; filename=\"dbcanary-coredump.elf\"");

    /* Chunked, because the image is tens of kilobytes and must not be brought
     * into RAM in one piece - diag.h says so and means it. */
    for (size_t offset = 0; offset < total; ) {
        const size_t want = (total - offset) < OTA_CHUNK
                          ? (total - offset) : OTA_CHUNK;
        if (diag_coredump_read(offset, chunk, want) != ESP_OK ||
            httpd_resp_send_chunk(req, chunk, want) != ESP_OK) {
            free(chunk);
            httpd_resp_send_chunk(req, NULL, 0);
            return ESP_FAIL;
        }
        offset += want;
    }
    free(chunk);
    return httpd_resp_send_chunk(req, NULL, 0);
}

/* ---- the server ---------------------------------------------------------- */

static const httpd_uri_t ROUTES[] = {
    { .uri = "/",                        .method = HTTP_GET,  .handler = page_get },
    { .uri = "/api/status",              .method = HTTP_GET,  .handler = status_get },
    { .uri = "/api/config",              .method = HTTP_GET,  .handler = config_get },
    { .uri = "/api/config",              .method = HTTP_POST, .handler = config_post },
    { .uri = "/api/config/reset",        .method = HTTP_POST, .handler = config_reset_post },
    { .uri = "/api/reboot",              .method = HTTP_POST, .handler = reboot_post },
    { .uri = "/api/ota",                 .method = HTTP_POST, .handler = ota_post },
    { .uri = "/api/diagnostics",         .method = HTTP_GET,  .handler = diagnostics_get },
    { .uri = "/api/diagnostics/coredump",.method = HTTP_GET,  .handler = coredump_get },
};

#define ROUTE_COUNT (sizeof(ROUTES) / sizeof(ROUTES[0]))

static esp_err_t server_up(void)
{
    httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
    cfg.open_fn = webui_open;
    cfg.max_uri_handlers = ROUTE_COUNT;
    /* The OTA and coredump handlers hold a 4 KB buffer and call into the flash
     * driver; the default 4 KB of stack is not enough for that plus cJSON. */
    cfg.stack_size = 8192;
    /* One browser, one cable. Fewer sockets is less to go wrong and less RAM
     * held away from the bridge, which is the thing that actually matters. */
    cfg.max_open_sockets = 4;
    cfg.lru_purge_enable = true;
    /* An upload of a megabyte over full-speed USB is not instant. */
    cfg.recv_wait_timeout = 20;
    cfg.send_wait_timeout = 20;

    ESP_RETURN_ON_ERROR(httpd_start(&s_httpd, &cfg), TAG, "httpd");
    for (size_t i = 0; i < ROUTE_COUNT; i++) {
        ESP_RETURN_ON_ERROR(httpd_register_uri_handler(s_httpd, &ROUTES[i]),
                            TAG, "route %s", ROUTES[i].uri);
    }
    ESP_LOGI(TAG, "configuration UI at http://" IPSTR "/",
             IP2STR(&(esp_ip4_addr_t){ .addr = htonl(usbnet_local_ip()) }));
    return ESP_OK;
}

static void server_down(void)
{
    if (s_httpd != NULL) {
        httpd_stop(s_httpd);
        s_httpd = NULL;
        ESP_LOGI(TAG, "USB host gone; configuration UI stopped");
    }
}

/* Follows the USB link so that there is no listening socket at all when no
 * host is attached. Polling rather than a callback keeps usbnet unaware of
 * this component, which is the direction the dependency should point. */
static void watch_task(void *arg)
{
    (void)arg;
    for (;;) {
        const bool want = usbnet_link_up();
        if (want && s_httpd == NULL) {
            if (server_up() != ESP_OK) {
                server_down();          /* release a half-started server */
            }
        } else if (!want && s_httpd != NULL) {
            server_down();
        }
        vTaskDelay(pdMS_TO_TICKS(500));
    }
}

esp_err_t webui_start(void)
{
    if (xTaskCreate(watch_task, "webui", 3072, NULL, 3, NULL) != pdPASS) {
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}

#endif /* CONFIG_TINYUSB_NET_MODE_NCM */
