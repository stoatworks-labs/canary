/* Host tests for per-peer source-address selection.
 *
 * The cases are the address pairs that actually occur once a unit has both a
 * W5500 and a USB-NCM interface: R1 on the wired side, R1 on the USB link, a
 * link-local rig with no DHCP server, and the half-configured states either
 * interface passes through while it is coming up. */
#include <stdio.h>

#include "net_select.h"

static int checks = 0, fails = 0;
#define CHECK(c, ...) do { checks++; if (!(c)) { \
    fails++; printf("  FAIL %s:%d  ", __FILE__, __LINE__); printf(__VA_ARGS__); \
    printf("\n"); } } while (0)

/* Dotted quad -> host byte order, so the tests read like a network diagram. */
#define IP4(a, b, c, d) (((uint32_t)(a) << 24) | ((uint32_t)(b) << 16) | \
                         ((uint32_t)(c) << 8) | (uint32_t)(d))

#define ETH_IP      IP4(192, 168, 1, 90)
#define ETH_MASK    IP4(255, 255, 255, 0)
#define USB_IP      IP4(192, 168, 7, 1)
#define USB_MASK    IP4(255, 255, 255, 0)

int main(void)
{
    printf("net_select tests\n");

    /* The order the bridge must use: routable interface first. */
    const net_iface_t both[] = {
        { .ip = ETH_IP, .netmask = ETH_MASK },
        { .ip = USB_IP, .netmask = USB_MASK },
    };

    {
        /* R1 on the wired network. */
        CHECK(net_select_source(both, 2, IP4(192, 168, 1, 40)) == ETH_IP,
              "a peer on the wired subnet gets the wired address");
    }
    {
        /* R1 on the laptop at the other end of the USB cable - the whole point
         * of this file. Answering ETH_IP here is the bug it prevents. */
        CHECK(net_select_source(both, 2, IP4(192, 168, 7, 2)) == USB_IP,
              "a peer on the USB link gets the USB address");
    }
    {
        /* A peer on neither subnet can only have come through a router, and
         * the USB link routes nowhere. */
        CHECK(net_select_source(both, 2, IP4(10, 0, 0, 5)) == ETH_IP,
              "an off-link peer falls back to the wired address, never USB");
    }
    {
        CHECK(net_select_source(both, 2, 0) == ETH_IP,
              "no peer named falls back to the first configured interface");
    }

    {
        /* USB plugged in before the LAN cable, or before a lease. */
        const net_iface_t usb_only[] = {
            { .ip = 0,       .netmask = 0 },
            { .ip = USB_IP,  .netmask = USB_MASK },
        };
        CHECK(net_select_source(usb_only, 2, IP4(192, 168, 7, 2)) == USB_IP,
              "USB answers while Ethernet has no address");
        CHECK(net_select_source(usb_only, 2, IP4(10, 0, 0, 5)) == USB_IP,
              "with nothing else configured, USB is better than nothing");
    }
    {
        /* No USB host attached: the NCM netif exists but the link is down and
         * esp_netif reports 0.0.0.0. It must not win anything. */
        const net_iface_t eth_only[] = {
            { .ip = ETH_IP, .netmask = ETH_MASK },
            { .ip = 0,      .netmask = 0 },
        };
        CHECK(net_select_source(eth_only, 2, IP4(192, 168, 7, 2)) == ETH_IP,
              "an unconfigured USB interface never matches a peer");
    }
    {
        const net_iface_t none[] = {
            { .ip = 0, .netmask = 0 },
            { .ip = 0, .netmask = 0 },
        };
        CHECK(net_select_source(none, 2, IP4(192, 168, 1, 40)) == 0,
              "nothing configured yields no address");
        CHECK(net_select_source(NULL, 0, IP4(192, 168, 1, 40)) == 0,
              "a NULL table is not a crash");
        CHECK(net_select_source(both, 0, IP4(192, 168, 1, 40)) == 0,
              "an empty table yields no address");
    }

    {
        /* AUTOIP on both sides: a /16 with no DHCP server anywhere. The USB
         * host will have self-assigned too, and both are in 169.254/16 - the
         * longest-prefix rule is what keeps the USB peer on the USB address. */
        const net_iface_t linklocal[] = {
            { .ip = IP4(169, 254, 3, 7),   .netmask = IP4(255, 255, 0, 0) },
            { .ip = USB_IP,                .netmask = USB_MASK },
        };
        CHECK(net_select_source(linklocal, 2, IP4(169, 254, 88, 9)) ==
              IP4(169, 254, 3, 7),
              "a link-local peer gets the link-local Ethernet address");
        CHECK(net_select_source(linklocal, 2, IP4(192, 168, 7, 2)) == USB_IP,
              "the USB peer is still matched on its own /24");
    }
    {
        /* Overlapping subnets: a misconfiguration, but it must resolve to the
         * more specific one rather than to whichever was listed first. */
        const net_iface_t overlap[] = {
            { .ip = IP4(192, 168, 0, 5),  .netmask = IP4(255, 255, 0, 0) },
            { .ip = IP4(192, 168, 7, 1),  .netmask = IP4(255, 255, 255, 0) },
        };
        CHECK(net_select_source(overlap, 2, IP4(192, 168, 7, 2)) ==
              IP4(192, 168, 7, 1),
              "the longest prefix wins when subnets overlap");
        CHECK(net_select_source(overlap, 2, IP4(192, 168, 9, 2)) ==
              IP4(192, 168, 0, 5),
              "the wider subnet still takes peers the narrow one misses");
    }
    {
        /* An address with no netmask. esp_netif reports this while an
         * interface is part way through configuration, and a zero mask matches
         * EVERY peer - so without the guard in net_select_source() a
         * half-configured USB interface would swallow the wired peers too.
         * This case is here because removing that guard passed every other
         * test in this file. */
        const net_iface_t no_mask[] = {
            { .ip = ETH_IP, .netmask = ETH_MASK },
            { .ip = USB_IP, .netmask = 0 },
        };
        CHECK(net_select_source(no_mask, 2, IP4(192, 168, 1, 40)) == ETH_IP,
              "an interface with no netmask does not claim a wired peer");
        CHECK(net_select_source(no_mask, 2, IP4(10, 0, 0, 5)) == ETH_IP,
              "nor an off-link one");
        const net_iface_t only_no_mask[] = {
            { .ip = USB_IP, .netmask = 0 },
        };
        CHECK(net_select_source(only_no_mask, 1, IP4(10, 0, 0, 5)) == USB_IP,
              "but it is still offered as the fallback, being all we have");
    }
    {
        /* A /32 - the shape a point-to-point link takes on some stacks. */
        const net_iface_t host_route[] = {
            { .ip = ETH_IP, .netmask = ETH_MASK },
            { .ip = USB_IP, .netmask = IP4(255, 255, 255, 255) },
        };
        CHECK(net_select_source(host_route, 2, USB_IP) == USB_IP,
              "a /32 matches only itself");
        CHECK(net_select_source(host_route, 2, IP4(192, 168, 7, 2)) == ETH_IP,
              "and does not claim its neighbours");
    }

    printf("\n%d checks, %d failed\n", checks, fails);
    return fails ? 1 : 0;
}
