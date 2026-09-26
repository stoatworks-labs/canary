/* USB network device (CDC-NCM). See include/usbnet.h. */
#include "usbnet.h"

#include "esp_log.h"

static const char *TAG = "usbnet";

#if !CONFIG_TINYUSB_NET_MODE_NCM

/* Built without NCM. Everything below needs TinyUSB, which is not linked in,
 * so the whole implementation is replaced by this — the default image is
 * exactly the one that has always been built, and app_main does not need an
 * #if around the call. */

esp_err_t usbnet_start(const usbnet_config_t *cfg)
{
    (void)cfg;
    ESP_LOGD(TAG, "not built in (no CONFIG_TINYUSB_NET_MODE_NCM)");
    return ESP_ERR_NOT_SUPPORTED;
}

uint32_t usbnet_local_ip(void) { return 0; }
uint32_t usbnet_netmask(void)  { return 0; }
bool     usbnet_link_up(void)  { return false; }
bool     usbnet_stack_up(void) { return false; }
uint32_t usbnet_host_ip(void)  { return 0; }

#else /* CONFIG_TINYUSB_NET_MODE_NCM */

#include <inttypes.h>
#include <stdlib.h>
#include <string.h>

#include "esp_check.h"
#include "esp_event.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
/* dhcps_lease_t, for the lease pool passed through esp_netif_dhcps_option(). */
#include "dhcpserver/dhcpserver.h"
#include "lwip/inet.h"
#include "tinyusb.h"
#include "tinyusb_default_config.h"
#include "tinyusb_net.h"

/* How long lwip's tcpip thread will wait for TinyUSB to take a frame. The USB
 * task is higher priority and a full-speed bulk transfer of a 1514-byte frame
 * is under a millisecond, so reaching this means the host has stopped
 * servicing the endpoint - unplugged mid-frame, or suspended. Dropping the
 * frame is correct; blocking the tcpip thread on it is not, because the wired
 * interface shares that thread and an amplifier bus does not stop needing it
 * because somebody pulled a USB cable. */
#define TX_TIMEOUT_MS 100

static esp_netif_t *s_netif;
static usbnet_config_t s_cfg;
static volatile bool s_link_up;
static volatile bool s_stack_up;
static uint8_t s_host_mac[6];

/* esp_netif requires a driver object whose first member is the base. */
typedef struct {
    esp_netif_driver_base_t base;
} usbnet_driver_t;

static usbnet_driver_t s_driver;

/* ---- USB -> lwip --------------------------------------------------------- */

/* THE BUFFER MUST BE COPIED. tud_network_recv_cb() calls
 * tud_network_recv_renew() the instant this returns, handing the buffer back
 * to the NCM receive machinery, while esp_netif_receive() only queues the
 * frame: ethernetif_input() wraps it in a custom pbuf that REFERENCES it and
 * posts that to the tcpip thread, which reads it later. Passing TinyUSB's
 * buffer through unchanged parses whatever the next NTB happens to contain. */
static esp_err_t usb_to_lwip(void *buffer, uint16_t len, void *ctx)
{
    (void)ctx;
    if (s_netif == NULL || len == 0) {
        return ESP_OK;
    }
    void *copy = malloc(len);
    if (copy == NULL) {
        return ESP_ERR_NO_MEM;   /* the host will retransmit */
    }
    memcpy(copy, buffer, len);
    /* Ownership passes to esp_netif here: every path inside it, success or
     * failure, ends at driver_free_rx_buffer below. Freeing `copy` on an error
     * return would therefore be a double free, not a leak fix. */
    esp_netif_receive(s_netif, copy, len, NULL);
    return ESP_OK;
}

static void usbnet_free_rx(void *h, void *buffer)
{
    (void)h;
    free(buffer);
}

/* ---- lwip -> USB --------------------------------------------------------- */

static esp_err_t usbnet_transmit(void *h, void *buffer, size_t len)
{
    (void)h;
    if (!s_link_up) {
        return ESP_ERR_INVALID_STATE;
    }
    /* Synchronous: `buffer` belongs to lwip and is reused as soon as we
     * return, and the sync path is the one that copies it out before it
     * returns (tud_network_xmit_cb). The async path would queue the pointer
     * and read it after lwip had moved on. No free callback is registered, so
     * nothing here owns or releases the buffer. */
    return tinyusb_net_send_sync(buffer, (uint16_t)len, NULL,
                                 pdMS_TO_TICKS(TX_TIMEOUT_MS));
}

/* ---- link state ---------------------------------------------------------- */

/* Called from the TinyUSB task when the host configures the device
 * (TINYUSB_EVENT_ATTACHED, i.e. tud_mount_cb).
 *
 * NOT from tud_network_init_cb, which is what this used to hang off: TinyUSB
 * 0.21's NCM driver declares that callback and never calls it, so the link was
 * never marked up, the netif and DHCP server never started, and every frame
 * was refused - a Mac saw an active adapter, sent 166 frames and got 0 back,
 * then fell back to 169.254. The driver has no hook for the host selecting
 * data alt 1 either, so mount is the latest event there is. Nothing is lost
 * by being early: a frame queued before alt 1 waits in the NTB rather than
 * failing, and the DHCP server only answers what the host sends, which it
 * does not send until alt 1. on_init_callback stays wired to this too, in
 * case a later TinyUSB starts calling it; the guard makes that a no-op. */
static void link_up(void *ctx)
{
    (void)ctx;
    if (s_link_up) {
        return;
    }
    s_link_up = true;
    ESP_LOGI(TAG, "host attached; link up");
    esp_netif_action_start(s_netif, NULL, 0, NULL);
    esp_netif_action_connected(s_netif, NULL, 0, NULL);

    /* action_start() only starts the DHCP server from INIT, and make_netif()
     * had to stop it (INIT -> STOPPED) to be allowed to set the lease options,
     * so without this the server silently never runs: action_start() returns
     * ESP_OK and the host sits in DHCP INIT until it gives up and self-assigns
     * 169.254. On a re-attach action_start() has already started it from the
     * INIT that action_stop() left, hence ALREADY_STARTED is fine. */
    const esp_err_t err = esp_netif_dhcps_start(s_netif);
    if (err != ESP_OK && err != ESP_ERR_ESP_NETIF_DHCP_ALREADY_STARTED) {
        ESP_LOGE(TAG, "DHCP server: %s - the host will self-assign 169.254",
                 esp_err_to_name(err));
    }
}

static void on_usb_event(tinyusb_event_t *event, void *arg)
{
    (void)arg;
    switch (event->id) {
    case TINYUSB_EVENT_ATTACHED:
        ESP_LOGI(TAG, "USB attached");
        link_up(NULL);
        break;
    case TINYUSB_EVENT_DETACHED:
        if (s_link_up) {
            s_link_up = false;
            ESP_LOGW(TAG, "host detached; link down");
            esp_netif_action_disconnected(s_netif, NULL, 0, NULL);
            esp_netif_action_stop(s_netif, NULL, 0, NULL);
        }
        break;
    default:
        break;
    }
}

/* ---- netif --------------------------------------------------------------- */

static esp_err_t post_attach(esp_netif_t *netif, esp_netif_iodriver_handle h)
{
    usbnet_driver_t *driver = h;
    driver->base.netif = netif;

    const esp_netif_driver_ifconfig_t ifcfg = {
        .handle = driver,
        .transmit = usbnet_transmit,
        .driver_free_rx_buffer = usbnet_free_rx,
    };
    return esp_netif_set_driver_config(netif, &ifcfg);
}

static esp_err_t make_netif(const uint8_t *our_mac)
{
    esp_netif_ip_info_t ip_info = {0};
    ip_info.ip.addr = htonl(s_cfg.ip);
    ip_info.netmask.addr = htonl(s_cfg.netmask);
    /* NO GATEWAY. Deliberately 0.0.0.0 and not our own address: see the
     * router-option comment in usbnet_start(). */
    ip_info.gw.addr = 0;

    esp_netif_inherent_config_t base = {
        /* AUTOUP because esp_netif_action_start() only starts the DHCP server
         * if the lwip netif is already up, and DHCP_SERVER because the host at
         * the other end of a USB cable has nothing else to ask. GARP so a
         * laptop that re-plugs does not sit on a stale ARP entry for us. */
        .flags = (esp_netif_flags_t)(ESP_NETIF_DHCP_SERVER |
                                     ESP_NETIF_FLAG_AUTOUP |
                                     ESP_NETIF_FLAG_GARP),
        .ip_info = &ip_info,
        .get_ip_event = 0,          /* static address; nothing to announce */
        .lost_ip_event = 0,
        .if_key = "USB_NCM_DEF",
        .if_desc = s_cfg.if_desc,
        /* Below the W5500's 50 and below the Wi-Fi AP's 10, so this interface
         * can never become the default route. A point-to-point link to one
         * laptop is not a route to anywhere. */
        .route_prio = 5,
        .bridge_info = NULL,
    };
    memcpy(base.mac, our_mac, 6);

    const esp_netif_config_t cfg = {
        .base = &base,
        .driver = NULL,             /* attached below, once it has a netif */
        .stack = ESP_NETIF_NETSTACK_DEFAULT_ETH,
    };
    s_netif = esp_netif_new(&cfg);
    ESP_RETURN_ON_FALSE(s_netif != NULL, ESP_FAIL, TAG, "netif");

    s_driver.base.post_attach = post_attach;
    ESP_RETURN_ON_ERROR(esp_netif_attach(s_netif, &s_driver), TAG, "attach");
    ESP_RETURN_ON_ERROR(esp_netif_set_mac(s_netif, (uint8_t *)our_mac),
                        TAG, "set mac");

    /* The lease pool and the two options that decide whether plugging this
     * unit into a laptop is harmless.
     *
     * OFFER_ROUTER is ON by default in lwip's DHCP server (dhcps_offer = 0xFF)
     * and it would advertise us as the host's router. macOS and Windows both
     * rank a freshly appeared wired adapter ABOVE Wi-Fi in their automatic
     * service order, so the laptop would move its default route onto a USB
     * link that routes precisely nowhere - the operator loses the internet,
     * the venue network, and very likely the amplifiers, by plugging in a
     * converter. Clearing it leaves the host with an on-link route to
     * 192.168.7.0/24 and nothing else, which is all R1 needs.
     *
     * DNS is off by default (dhcps_dns = 0x00); cleared here anyway so the
     * intent survives a change of lwip defaults. */
    esp_netif_dhcps_stop(s_netif);      /* INIT state; ignore "already" */

    dhcps_lease_t pool = {
        .enable = true,
        .start_ip.addr = htonl(s_cfg.pool_start),
        .end_ip.addr = htonl(s_cfg.pool_end),
    };
    ESP_RETURN_ON_ERROR(esp_netif_dhcps_option(s_netif, ESP_NETIF_OP_SET,
                            ESP_NETIF_REQUESTED_IP_ADDRESS, &pool, sizeof(pool)),
                        TAG, "dhcps pool");

    uint8_t offer = 0;
    ESP_RETURN_ON_ERROR(esp_netif_dhcps_option(s_netif, ESP_NETIF_OP_SET,
                            ESP_NETIF_ROUTER_SOLICITATION_ADDRESS,
                            &offer, sizeof(offer)),
                        TAG, "dhcps router option");
    ESP_RETURN_ON_ERROR(esp_netif_dhcps_option(s_netif, ESP_NETIF_OP_SET,
                            ESP_NETIF_DOMAIN_NAME_SERVER, &offer, sizeof(offer)),
                        TAG, "dhcps dns option");
    return ESP_OK;
}

/* ---- the deferred install ------------------------------------------------ */

/* Installing TinyUSB is the point of no return for the USB-C port: it moves the
 * shared FSLS PHY from USB_SERIAL_JTAG to USB-OTG, so the console and esptool's
 * reset line vanish from this connector until the next reset.
 *
 * It therefore waits. Everything before this point - the netif, the DHCP
 * server, the MAC derivation - happens at boot and claims no peripheral, so the
 * only thing the delay holds back is the moment the port stops being a serial
 * port. That window is how a unit with no fitted J301 is read and reflashed at
 * all, so it is not an optimisation to be tidied away later.
 *
 * Failures are logged rather than returned, because the caller is long gone.
 * The console is, by construction, still alive when this runs - that is the
 * whole point - so a failure here is visible in `idf.py monitor` even though
 * nothing can return it. */
static void install_task(void *arg)
{
    (void)arg;
    if (s_cfg.start_delay_ms > 0) {
        ESP_LOGW(TAG, "USB-OTG starts in %" PRIu32 " ms. Until then this port "
                      "is still a serial console: read the log now, and this "
                      "is also the window in which esptool can reflash "
                      "without the BOOT button.",
                 s_cfg.start_delay_ms);
        vTaskDelay(pdMS_TO_TICKS(s_cfg.start_delay_ms));
    }

    ESP_LOGW(TAG, "starting USB-OTG: the USB-serial console on this port is "
                  "about to disappear. Reflash with BOOT held.");

    const tinyusb_config_t tusb_cfg = TINYUSB_DEFAULT_CONFIG(on_usb_event);
    esp_err_t err = tinyusb_driver_install(&tusb_cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "tinyusb_driver_install: %s - no USB network device. "
                      "The PHY may already have moved, so this may be the last "
                      "line you see on this port.", esp_err_to_name(err));
        vTaskDelete(NULL);
        return;
    }

    tinyusb_net_config_t net_cfg = {
        .on_recv_callback = usb_to_lwip,
        .on_init_callback = link_up,
        .free_tx_buffer = NULL,     /* sync sends only; nothing to release */
        .user_context = NULL,
    };
    memcpy(net_cfg.mac_addr, s_host_mac, sizeof(net_cfg.mac_addr));
    err = tinyusb_net_init(&net_cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "tinyusb_net_init: %s - enumerated, but not as a network "
                      "device", esp_err_to_name(err));
        vTaskDelete(NULL);
        return;
    }

    s_stack_up = true;
    ESP_LOGI(TAG, "USB-OTG up; waiting for a host to attach");
    vTaskDelete(NULL);
}

/* ---- public -------------------------------------------------------------- */

esp_err_t usbnet_start(const usbnet_config_t *cfg)
{
    ESP_RETURN_ON_FALSE(cfg != NULL, ESP_ERR_INVALID_ARG, TAG, "cfg");
    ESP_RETURN_ON_FALSE(s_netif == NULL, ESP_ERR_INVALID_STATE, TAG, "started");
    s_cfg = *cfg;
    if (s_cfg.if_desc == NULL) {
        s_cfg.if_desc = "usb";
    }

    /* esp_netif_init() and the default event loop are idempotent and net.c may
     * already have done both; usbnet must work whether it runs before or after
     * the wired side, including on a build with no wired side at all. */
    ESP_RETURN_ON_ERROR(esp_netif_init(), TAG, "netif init");
    const esp_err_t loop_err = esp_event_loop_create_default();
    ESP_RETURN_ON_FALSE(loop_err == ESP_OK || loop_err == ESP_ERR_INVALID_STATE,
                        loop_err, TAG, "event loop");

    /* TWO MACs, and they must differ: one is ours, one is the address the host
     * gives its own end of the link, and a link with the same address at both
     * ends does not forward. Both are derived locally-administered addresses,
     * so neither can collide with the Espressif OUI the W5500 carries -
     * important because a laptop with both interfaces up would otherwise see
     * one MAC on two networks. */
    uint8_t base_mac[6];
    ESP_RETURN_ON_ERROR(esp_read_mac(base_mac, ESP_MAC_ETH), TAG, "read mac");

    uint8_t our_mac[6];
    ESP_RETURN_ON_ERROR(esp_derive_local_mac(our_mac, base_mac), TAG, "derive mac");
    memcpy(s_host_mac, our_mac, sizeof(s_host_mac));
    s_host_mac[5] ^= 0x01;          /* the host's end of the same cable */

    ESP_RETURN_ON_ERROR(make_netif(our_mac), TAG, "netif");

    /* Everything above is free: no peripheral has been claimed and the USB-C
     * port is still a serial port. The install that changes that is deferred -
     * see install_task(). */
    if (xTaskCreate(install_task, "usbnet", 4096, NULL, 4, NULL) != pdPASS) {
        return ESP_ERR_NO_MEM;
    }

    const esp_ip4_addr_t ip = { .addr = htonl(s_cfg.ip) };
    ESP_LOGI(TAG, "NCM will be at " IPSTR "/%d, leases " IPSTR "-" IPSTR
                  ", no gateway offered",
             IP2STR(&ip), 32 - __builtin_ctz(s_cfg.netmask),
             IP2STR(&(esp_ip4_addr_t){ .addr = htonl(s_cfg.pool_start) }),
             IP2STR(&(esp_ip4_addr_t){ .addr = htonl(s_cfg.pool_end) }));
    return ESP_OK;
}

uint32_t usbnet_local_ip(void)
{
    /* 0 until a host is there. The address is static and known from boot, but
     * handing it to a discovery answer before the link exists would advertise
     * somewhere nothing can connect. */
    return s_link_up ? s_cfg.ip : 0;
}

uint32_t usbnet_netmask(void)
{
    return s_link_up ? s_cfg.netmask : 0;
}

bool usbnet_link_up(void)
{
    return s_link_up;
}

bool usbnet_stack_up(void)
{
    return s_stack_up;
}

uint32_t usbnet_host_ip(void)
{
    if (!s_link_up || s_netif == NULL) {
        return 0;
    }
    esp_netif_pair_mac_ip_t pair = {0};
    memcpy(pair.mac, s_host_mac, sizeof(pair.mac));
    if (esp_netif_dhcps_get_clients_by_mac(s_netif, 1, &pair) != ESP_OK) {
        return 0;
    }
    return ntohl(pair.ip.addr);
}

#endif /* CONFIG_TINYUSB_NET_MODE_NCM */
