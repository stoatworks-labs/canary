/* Network bring-up. See include/net.h. */
#include "net.h"
#include "net_select.h"

#include <string.h>

#include "board.h"
#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_check.h"
#include "esp_eth.h"
#include "esp_eth_mac_spi.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "lwip/inet.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"

static const char *TAG = "net";

#define GOT_IP_BIT BIT0

static EventGroupHandle_t s_events;
static volatile uint32_t s_ip;
static volatile bool s_link_up;
static esp_eth_handle_t s_eth;

/* ---- shared -------------------------------------------------------------- */

static esp_err_t common_init(void)
{
    if (s_events != NULL) {
        return ESP_OK;                  /* already brought up */
    }
    s_events = xEventGroupCreate();
    ESP_RETURN_ON_FALSE(s_events != NULL, ESP_ERR_NO_MEM, TAG, "event group");
    ESP_RETURN_ON_ERROR(esp_netif_init(), TAG, "netif init");
    /* ESP_ERR_INVALID_STATE here means the default loop already exists, which
     * is not an error: since usbnet started shipping, this component is no
     * longer guaranteed to be the first thing in the image that wants one, and
     * usbnet runs BEFORE it (app_main explains why). Treating that as fatal is
     * not a quiet degradation either - app_main ESP_ERROR_CHECKs the result,
     * so the unit abort()s, reboots, and does it again. A QEMU boot of the
     * USB-NCM image boot-looped exactly this way the first time the two were
     * put in one image. esp_netif_init() is already idempotent and returns
     * ESP_OK. */
    const esp_err_t loop_err = esp_event_loop_create_default();
    ESP_RETURN_ON_FALSE(loop_err == ESP_OK || loop_err == ESP_ERR_INVALID_STATE,
                        loop_err, TAG, "event loop");
    return ESP_OK;
}

/* 169.254.0.0/16 - the address AUTOIP claims when no DHCP server answers.
 * Worth naming in the log: a unit on one of these is reachable only from hosts
 * that are themselves link-local, which is the difference between "R1 cannot
 * see it" and "R1 is on the wrong subnet". */
static bool ip4_is_link_local(uint32_t host_order)
{
    return (host_order & 0xffff0000u) == 0xa9fe0000u;
}

static void on_got_ip(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg; (void)base; (void)id;
    const ip_event_got_ip_t *event = (const ip_event_got_ip_t *)data;
    s_ip = ntohl(event->ip_info.ip.addr);
    /* This fires for a DHCP lease AND for an AUTOIP self-assignment: lwip hands
     * both to esp_netif through the same netif-address-changed callback. It can
     * therefore fire twice - link-local first, then the lease if a server turns
     * up late - and the second one is not an error. */
    if (ip4_is_link_local(s_ip)) {
        ESP_LOGW(TAG, "got " IPSTR " - LINK-LOCAL (RFC 3927): no DHCP server "
                      "answered, so R1 must also be link-local to reach us",
                 IP2STR(&event->ip_info.ip));
    } else {
        ESP_LOGI(TAG, "got " IPSTR " by DHCP", IP2STR(&event->ip_info.ip));
    }
    xEventGroupSetBits(s_events, GOT_IP_BIT);
}

uint32_t net_local_ip(void) { return s_ip; }

bool net_ip_is_link_local(void) { return ip4_is_link_local(s_ip); }

bool net_link_up(void) { return s_link_up; }

/* ---- wired Ethernet: W5500 over SPI (the rev A board) -------------------- */

static void on_eth(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg; (void)base; (void)data;
    switch (id) {
    case ETHERNET_EVENT_CONNECTED:
        s_link_up = true;
        ESP_LOGI(TAG, "link up");
        break;
    case ETHERNET_EVENT_DISCONNECTED:
        s_link_up = false;
        s_ip = 0;
        ESP_LOGW(TAG, "link down");
        break;
    default:
        break;
    }
}

esp_err_t net_start_eth(const net_ipv4_static_t *ipv4)
{
    ESP_RETURN_ON_ERROR(common_init(), TAG, "common init");

    const spi_bus_config_t bus = {
        .mosi_io_num = BOARD_ETH_MOSI_GPIO,
        .miso_io_num = BOARD_ETH_MISO_GPIO,
        .sclk_io_num = BOARD_ETH_SCK_GPIO,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
    };
    ESP_RETURN_ON_ERROR(spi_bus_initialize(BOARD_ETH_SPI_HOST, &bus,
                                           SPI_DMA_CH_AUTO), TAG, "spi bus");

    /* command_bits/address_bits are NOT decorative: the W5500's variable-length
     * data mode frames every access as a 16-bit address plus an 8-bit control
     * byte, and esp_eth's W5500 driver expects the SPI peripheral to emit those
     * as the command and address phases. Omitting them yields a device that
     * probes but never talks. */
    spi_device_interface_config_t devcfg = {
        .command_bits = 16,
        .address_bits = 8,
        .mode = 0,
        .clock_speed_hz = BOARD_ETH_SPI_CLOCK_MHZ * 1000 * 1000,
        .spics_io_num = BOARD_ETH_CS_GPIO,
        .queue_size = 20,
    };

    eth_w5500_config_t w5500 = ETH_W5500_DEFAULT_CONFIG(BOARD_ETH_SPI_HOST,
                                                        &devcfg);
    w5500.int_gpio_num = BOARD_ETH_INT_GPIO;

    /* The ISR service must exist BEFORE esp_eth_driver_install: the W5500 MAC
     * registers its interrupt handler with gpio_isr_handler_add(), which fails
     * if nothing installed the service first. That failure is only a log line —
     * the driver comes up anyway, with no handler on INT, so the link goes up
     * and not one frame is ever received. Booting the image under QEMU showed
     * exactly that:
     *
     *   E gpio: gpio_isr_handler_add(561): GPIO isr service is not installed
     *
     * ESP_ERR_INVALID_STATE just means someone already installed it. */
    const esp_err_t isr_err = gpio_install_isr_service(0);
    ESP_RETURN_ON_FALSE(isr_err == ESP_OK || isr_err == ESP_ERR_INVALID_STATE,
                        isr_err, TAG, "gpio isr service");

    eth_mac_config_t mac_config = ETH_MAC_DEFAULT_CONFIG();
    esp_eth_mac_t *mac = esp_eth_mac_new_w5500(&w5500, &mac_config);
    ESP_RETURN_ON_FALSE(mac != NULL, ESP_FAIL, TAG, "w5500 mac");

    eth_phy_config_t phy_config = ETH_PHY_DEFAULT_CONFIG();
    phy_config.reset_gpio_num = BOARD_ETH_RST_GPIO;
    phy_config.phy_addr = 1;            /* W5500 integrates its PHY; no MDIO scan */
    esp_eth_phy_t *phy = esp_eth_phy_new_w5500(&phy_config);
    ESP_RETURN_ON_FALSE(phy != NULL, ESP_FAIL, TAG, "w5500 phy");

    esp_eth_config_t eth_config = ETH_DEFAULT_CONFIG(mac, phy);
    ESP_RETURN_ON_ERROR(esp_eth_driver_install(&eth_config, &s_eth),
                        TAG, "eth install");

    /* The W5500 has no MAC address of its own, and nothing else supplies one -
     * unlike a PHY sitting behind the ESP's own EMAC. Derive it from the
     * module's efuse base MAC so each board is unique with no provisioning
     * step. R1 does not check the OUI (see docs/PROTOCOL.md), so the
     * Espressif-registered prefix is harmless for R70 compatibility. */
    uint8_t mac_addr[6];
    ESP_RETURN_ON_ERROR(esp_read_mac(mac_addr, ESP_MAC_ETH), TAG, "read mac");
    ESP_RETURN_ON_ERROR(esp_eth_ioctl(s_eth, ETH_CMD_S_MAC_ADDR, mac_addr),
                        TAG, "set mac");

    esp_netif_config_t netif_cfg = ESP_NETIF_DEFAULT_ETH();
    esp_netif_t *netif = esp_netif_new(&netif_cfg);
    ESP_RETURN_ON_FALSE(netif != NULL, ESP_FAIL, TAG, "netif");
    ESP_RETURN_ON_ERROR(esp_netif_attach(netif, esp_eth_new_netif_glue(s_eth)),
                        TAG, "netif attach");

    ESP_RETURN_ON_ERROR(esp_event_handler_instance_register(
        ETH_EVENT, ESP_EVENT_ANY_ID, on_eth, NULL, NULL), TAG, "eth handler");
    ESP_RETURN_ON_ERROR(esp_event_handler_instance_register(
        IP_EVENT, IP_EVENT_ETH_GOT_IP, on_got_ip, NULL, NULL), TAG, "ip handler");

    /* A static address is set BEFORE the interface starts, so the DHCP client
     * never sends a DISCOVER - which also means AUTOIP never runs, since lwip
     * starts it from the DHCP client's unanswered attempts. Stopping the
     * client afterwards would leave a race in which a lease could arrive and
     * replace the address somebody deliberately configured. */
    if (ipv4 != NULL) {
        esp_netif_dhcpc_stop(netif);    /* INIT state; "already stopped" is fine */
        esp_netif_ip_info_t info = {
            .ip.addr      = htonl(ipv4->ip),
            .netmask.addr = htonl(ipv4->netmask),
            .gw.addr      = htonl(ipv4->gw),
        };
        ESP_RETURN_ON_ERROR(esp_netif_set_ip_info(netif, &info), TAG, "static ip");
        /* Publish it ourselves rather than waiting for IP_EVENT_ETH_GOT_IP:
         * that event belongs to the DHCP client, which is not running. */
        s_ip = ipv4->ip;
        xEventGroupSetBits(s_events, GOT_IP_BIT);
        ESP_LOGI(TAG, "static address " IPSTR "/%d, gateway %s",
                 IP2STR(&info.ip), 32 - __builtin_ctz(ipv4->netmask ? ipv4->netmask : 1),
                 ipv4->gw ? inet_ntoa(info.gw) : "none");
    }

    ESP_LOGI(TAG, "W5500 on SPI%d sck=%d mosi=%d miso=%d cs=%d int=%d rst=%d @ %d MHz",
             BOARD_ETH_SPI_HOST + 1, BOARD_ETH_SCK_GPIO, BOARD_ETH_MOSI_GPIO,
             BOARD_ETH_MISO_GPIO, BOARD_ETH_CS_GPIO, BOARD_ETH_INT_GPIO,
             BOARD_ETH_RST_GPIO, BOARD_ETH_SPI_CLOCK_MHZ);
    ESP_RETURN_ON_ERROR(esp_eth_start(s_eth), TAG, "eth start");

    /* Do NOT block forever. Something has to start the bridge even on a rig
     * where the address is slow to arrive, and three dark LEDs for a minute is
     * indistinguishable from a dead board.
     *
     * A missing DHCP server no longer ends up here: CONFIG_LWIP_AUTOIP makes
     * lwip self-assign a 169.254 address after five unanswered DISCOVERs, which
     * arrives well inside this window. Reaching the timeout therefore means
     * there is no usable link at all - no cable, dead switch port, or a W5500
     * that claims link and passes nothing - and NOT merely "no DHCP". */
    EventBits_t bits = xEventGroupWaitBits(s_events, GOT_IP_BIT, pdFALSE,
                                          pdTRUE, pdMS_TO_TICKS(30000));
    if (!(bits & GOT_IP_BIT)) {
        ESP_LOGW(TAG, "no IPv4 address after 30 s (link %s) - neither DHCP nor "
                      "link-local got one; carrying on, and any address that "
                      "arrives later is picked up",
                 s_link_up ? "up" : "DOWN");
        return ESP_ERR_TIMEOUT;
    }
    return ESP_OK;
}

/* ---- Wi-Fi STA: devkit bring-up only, not on the rev A board ------------- */

static void on_wifi(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "disconnected; retrying");
        s_ip = 0;
        s_link_up = false;
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        s_link_up = true;
        on_got_ip(arg, base, id, data);
    }
}

esp_err_t net_start_sta(const char *ssid, const char *password)
{
    ESP_RETURN_ON_ERROR(common_init(), TAG, "common init");
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        WIFI_EVENT, ESP_EVENT_ANY_ID, on_wifi, NULL, NULL));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        IP_EVENT, IP_EVENT_STA_GOT_IP, on_wifi, NULL, NULL));

    wifi_config_t cfg = {0};
    strncpy((char *)cfg.sta.ssid, ssid, sizeof(cfg.sta.ssid) - 1);
    strncpy((char *)cfg.sta.password, password, sizeof(cfg.sta.password) - 1);
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &cfg));
    ESP_ERROR_CHECK(esp_wifi_start());

    xEventGroupWaitBits(s_events, GOT_IP_BIT, pdFALSE, pdTRUE, portMAX_DELAY);
    return ESP_OK;
}

/* ---- which address to advertise, per peer -------------------------------- */

/* The interfaces this product can have, MOST ROUTABLE FIRST. net_select_source()
 * falls back to the first entry that holds an address when it cannot place the
 * peer, so this order is the policy, not a detail: a peer we cannot place
 * reached us over the wired side or not at all, and offering it the USB link -
 * point to point, routing nowhere - would advertise an address it can never
 * open a socket to.
 *
 * Interfaces are named rather than enumerated because the order matters and a
 * walk of esp_netif's list would have to reconstruct it from route_prio while
 * holding the list lock. A key that does not exist in this build simply
 * contributes nothing. */
static const char *const IFACE_KEYS[] = {
    "ETH_DEF",          /* W5500 - the shipping path */
    "WIFI_STA_DEF",     /* devkit builds only */
    "USB_NCM_DEF",      /* usbnet, when built in */
};

#define IFACE_COUNT (sizeof(IFACE_KEYS) / sizeof(IFACE_KEYS[0]))

uint32_t bridge_local_ip_for(uint32_t peer)
{
    net_iface_t table[IFACE_COUNT];
    size_t n = 0;

    for (size_t i = 0; i < IFACE_COUNT; i++) {
        esp_netif_t *netif = esp_netif_get_handle_from_ifkey(IFACE_KEYS[i]);
        if (netif == NULL || !esp_netif_is_netif_up(netif)) {
            continue;
        }
        esp_netif_ip_info_t info;
        if (esp_netif_get_ip_info(netif, &info) != ESP_OK || info.ip.addr == 0) {
            continue;
        }
        table[n].ip = ntohl(info.ip.addr);
        table[n].netmask = ntohl(info.netmask.addr);
        n++;
    }

    const uint32_t chosen = net_select_source(table, n, peer);
    if (chosen != 0) {
        return chosen;
    }
    /* Nothing enumerated - which happens in the window between an address
     * arriving and the netif being marked up, and on the Wi-Fi devkit path
     * where the address is tracked here rather than read back. s_ip is what
     * this component has always returned. */
    return s_ip;
}
