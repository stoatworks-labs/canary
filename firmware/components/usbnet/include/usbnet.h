/*
 * USB network device (CDC-NCM) — CANary over the USB-C cable.
 *
 * Plug the unit into a laptop and it appears as a second Ethernet adapter, on
 * a private point-to-point link with the unit at one end and the laptop at the
 * other. R1 then discovers and drives it exactly as it does over the LAN jack:
 * the whole proven stack above the netif — UDP 33333 discovery, TCP 30000,
 * the CAN bridge — is unchanged and does not know which interface it is on.
 * That reuse is the entire argument for NCM over emulating an R60 (D/H16).
 *
 * WHAT IT COSTS, AND WHY IT IS NOT ON BY DEFAULT
 *
 * The ESP32-S3 has one USB PHY and two peripherals that want it. The
 * USB_SERIAL_JTAG block owns it out of reset; installing TinyUSB moves the mux
 * to USB-OTG in software (usb_wrap_ll_phy_enable_external(), no eFuse burnt,
 * reversible only by reset). The moment that happens the USB-Serial-JTAG
 * device disappears from the host — and on this board that device is the
 * console AND the programming port, on the same single USB-C connector.
 *
 * So a unit running the NCM image:
 *   - shows up as a network adapter, not as a serial port;
 *   - has no esp_log console over USB-C once the switch has happened;
 *   - cannot be reflashed by esptool's automatic reset after that, because the
 *     port esptool would drive no longer exists. Hold BOOT (SW302) and tap EN,
 *     and the ROM — which is unaffected, the eFuse is not burnt — brings
 *     USB-Serial-JTAG back for the download.
 *
 * THE START DELAY EXISTS FOR EXACTLY THAT. TinyUSB is installed a few seconds
 * after boot rather than immediately, so every power-up leaves a window in
 * which the USB-C port is still an ordinary serial port: long enough to read
 * the whole boot log with `idf.py monitor`, and long enough for esptool to
 * reset into download mode and reflash. On these boards that window is not a
 * convenience — J301 is a DNP and is NOT FITTED, so without it a unit that
 * fails to enumerate has no console at all and no way in but the BOOT button.
 *
 * The cost is that a laptop waits that long for the adapter to appear. Once,
 * per power-up. That is the right trade for a port that is also the only way
 * to recover the board.
 *
 * None of that is acceptable as a silent default on a board whose only power
 * path is also its only programming path, so this is a build-time choice:
 *
 *     idf.py -B build-usbnet \
 *            -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.usb-ncm" build
 *
 * Without that overlay CONFIG_TINYUSB_NET_MODE_NCM is off, usbnet_start()
 * returns ESP_ERR_NOT_SUPPORTED without touching anything, and the image is
 * the one that has always been built.
 *
 * Proven on a macOS host 2026-09-26. See docs/USB-NIC.md §7 for what is and
 * is not proven.
 */
#ifndef USBNET_H
#define USBNET_H

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

/* All addresses host byte order, matching net.h and bridge_local_ip(). */
typedef struct {
    uint32_t ip;          /* ours on the USB link */
    uint32_t netmask;
    uint32_t pool_start;  /* first address offered to the host */
    uint32_t pool_end;    /* last; one host, but a laptop that re-plugs before
                           * the lease expires asks for a second */
    uint32_t start_delay_ms; /* console/reflash window before TinyUSB takes the
                              * PHY. 0 installs immediately. */
    const char *if_desc;  /* shown in esp_netif listings and our own logs */
} usbnet_config_t;

/* 192.168.7.0/24 — RFC 1918, and deliberately not 192.168.0/1/2, which is
 * what the venue's own network is most likely to be using. A collision would
 * not merely be untidy: the host would have two interfaces claiming the same
 * subnet and would pick one, so R1 would reach the amplifiers or the unit but
 * not both. 192.168.7 is the subnet Linux's g_ether and a long tail of USB
 * gadgets have used for the same reason. */
#define USBNET_DEFAULT_CONFIG() (usbnet_config_t) {  \
    .ip              = 0xC0A80701u, /* 192.168.7.1 */\
    .netmask         = 0xFFFFFF00u, /* /24 */        \
    .pool_start      = 0xC0A80702u, /* 192.168.7.2 */\
    .pool_end        = 0xC0A80709u, /* 192.168.7.9 */\
    .start_delay_ms  = 8000,                         \
    .if_desc         = "usb",                        \
}

/* Create the netif and schedule TinyUSB to be installed after the start delay.
 *
 * Returns as soon as that is arranged — NOT once TinyUSB is up, and certainly
 * not once a host has enumerated us. Neither may block the bridge, and the
 * second may never happen at all. ESP_OK therefore means "this image has a USB
 * network path and it is coming", which is what the caller needs in order to
 * decide how serious a wired failure is. usbnet_link_up() reports the rest.
 *
 * A TinyUSB install that FAILS is reported by the deferred task, on a console
 * that is by construction still alive at that moment — that being the point of
 * the delay.
 *
 * ESP_ERR_NOT_SUPPORTED if the image was not built with NCM (see the header
 * comment); the caller should treat that as "no USB interface on this build"
 * and carry on, not as a failure. */
esp_err_t usbnet_start(const usbnet_config_t *cfg);

/* Our IPv4 address on the USB link, or 0 when no host is attached. Static, so
 * unlike the wired side this is known before anything plugs in — but it is
 * reported as 0 until the link is up, because an address on a link with
 * nothing on it is not somewhere R1 can be told to connect. */
uint32_t usbnet_local_ip(void);

/* The netmask that goes with it, 0 when the link is down. */
uint32_t usbnet_netmask(void);

/* True once a host has enumerated us and selected the NCM data interface. */
bool usbnet_link_up(void);

/* True once TinyUSB is installed, i.e. the start delay has elapsed and the PHY
 * has moved. False both before that and if the install failed. Distinguishing
 * the two from outside is what the log is for. */
bool usbnet_stack_up(void);

/* The address the DHCP server last handed out, 0 if none. Log and bench use:
 * it is the only way from this end to see whether the host took a lease or is
 * sitting on an APIPA address of its own. */
uint32_t usbnet_host_ip(void);

#endif /* USBNET_H */
