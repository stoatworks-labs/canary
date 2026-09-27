/* Settings storage in NVS. See include/config_store.h. */
#include "config_store.h"

#include <string.h>

#include "esp_log.h"
#include "nvs.h"
#include "nvs_flash.h"

static const char *TAG = "cfg";

/* Its own namespace, separate from diag's: erasing settings to recover a unit
 * must not throw away the crash summary that explains why it needed
 * recovering. NVS keys are capped at 15 characters.
 *
 * Still "dbcanary" after the rename to CANary, on purpose: the namespace is
 * where every unit in the field keeps its settings, and a new name would read
 * as "never configured" and quietly put them all back on defaults. */
#define NS "dbcanary"

#define KEY_HOSTNAME "host"
#define KEY_PORT     "port"
#define KEY_SOCKETS  "socks"
#define KEY_ETH_MODE "ethmode"
#define KEY_ETH_IP   "ethip"
#define KEY_ETH_MASK "ethmask"
#define KEY_ETH_GW   "ethgw"

static bool s_stored;

bool cfg_is_stored(void) { return s_stored; }

esp_err_t cfg_load(cfg_t *out)
{
    if (out == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    cfg_defaults(out);
    s_stored = false;

    nvs_handle_t nvs;
    esp_err_t err = nvs_open(NS, NVS_READONLY, &nvs);
    if (err != ESP_OK) {
        /* ESP_ERR_NVS_NOT_FOUND is the ordinary case on a unit that has never
         * been configured, and is not worth an error line every boot. */
        ESP_LOGI(TAG, "no stored settings (%s); using defaults",
                 esp_err_to_name(err));
        return ESP_OK;
    }

    cfg_t stored = *out;
    bool any = false;

    size_t len = sizeof(stored.hostname);
    if (nvs_get_str(nvs, KEY_HOSTNAME, stored.hostname, &len) == ESP_OK) {
        any = true;
    } else {
        /* nvs_get_str can leave the buffer part-written on a short read. */
        memcpy(stored.hostname, out->hostname, sizeof(stored.hostname));
    }

    uint16_t u16;
    if (nvs_get_u16(nvs, KEY_PORT, &u16) == ESP_OK) { stored.base_port = u16; any = true; }
    uint8_t u8;
    if (nvs_get_u8(nvs, KEY_SOCKETS, &u8) == ESP_OK) { stored.socket_count = u8; any = true; }
    if (nvs_get_u8(nvs, KEY_ETH_MODE, &u8) == ESP_OK) {
        stored.eth_mode = (cfg_ipv4_mode_t)u8;
        any = true;
    }
    uint32_t u32;
    if (nvs_get_u32(nvs, KEY_ETH_IP,   &u32) == ESP_OK) { stored.eth_ip = u32; any = true; }
    if (nvs_get_u32(nvs, KEY_ETH_MASK, &u32) == ESP_OK) { stored.eth_netmask = u32; any = true; }
    if (nvs_get_u32(nvs, KEY_ETH_GW,   &u32) == ESP_OK) { stored.eth_gw = u32; any = true; }

    nvs_close(nvs);

    if (!any) {
        ESP_LOGI(TAG, "stored settings are empty; using defaults");
        return ESP_OK;
    }

    /* THE WHOLE SET IS VALIDATED, not each field as it is read. A half-written
     * save, or a downgrade to firmware with a smaller socket maximum, can
     * leave fields that are individually fine and jointly impossible - a base
     * port whose last socket runs off the end, say. Falling back to defaults
     * wholesale is the only outcome that is guaranteed to boot, and a unit on
     * factory settings is recoverable in a way one that will not start is not. */
    const char *why = cfg_validate(&stored);
    if (why != NULL) {
        ESP_LOGE(TAG, "stored settings rejected (%s); falling back to defaults "
                      "- reconfigure and save again", why);
        return ESP_OK;                  /* `out` still holds the defaults */
    }

    *out = stored;
    s_stored = true;
    ESP_LOGI(TAG, "settings: name '%s', port %u, %u sockets, LAN %s",
             out->hostname, (unsigned)out->base_port,
             (unsigned)out->socket_count,
             out->eth_mode == CFG_IPV4_STATIC ? "static" : "DHCP");
    return ESP_OK;
}

esp_err_t cfg_save(const cfg_t *cfg)
{
    const char *why = cfg_validate(cfg);
    if (why != NULL) {
        ESP_LOGW(TAG, "refusing to save: %s", why);
        return ESP_ERR_INVALID_ARG;
    }

    nvs_handle_t nvs;
    esp_err_t err = nvs_open(NS, NVS_READWRITE, &nvs);
    if (err != ESP_OK) {
        return err;
    }

    /* Write everything, including the fields a DHCP configuration does not
     * use: they are what the form shows next time, and losing them means
     * retyping an address to get back to it. */
    err = nvs_set_str(nvs, KEY_HOSTNAME, cfg->hostname);
    if (err == ESP_OK) err = nvs_set_u16(nvs, KEY_PORT, cfg->base_port);
    if (err == ESP_OK) err = nvs_set_u8(nvs, KEY_SOCKETS, cfg->socket_count);
    if (err == ESP_OK) err = nvs_set_u8(nvs, KEY_ETH_MODE, (uint8_t)cfg->eth_mode);
    if (err == ESP_OK) err = nvs_set_u32(nvs, KEY_ETH_IP, cfg->eth_ip);
    if (err == ESP_OK) err = nvs_set_u32(nvs, KEY_ETH_MASK, cfg->eth_netmask);
    if (err == ESP_OK) err = nvs_set_u32(nvs, KEY_ETH_GW, cfg->eth_gw);
    if (err == ESP_OK) err = nvs_commit(nvs);

    nvs_close(nvs);
    if (err == ESP_OK) {
        ESP_LOGW(TAG, "settings saved; they take effect at the next boot");
    } else {
        ESP_LOGE(TAG, "save failed: %s", esp_err_to_name(err));
    }
    return err;
}

esp_err_t cfg_reset(void)
{
    nvs_handle_t nvs;
    esp_err_t err = nvs_open(NS, NVS_READWRITE, &nvs);
    if (err != ESP_OK) {
        return err;
    }
    err = nvs_erase_all(nvs);
    if (err == ESP_OK) {
        err = nvs_commit(nvs);
    }
    nvs_close(nvs);
    ESP_LOGW(TAG, "settings erased; the next boot is on factory defaults");
    return err;
}
