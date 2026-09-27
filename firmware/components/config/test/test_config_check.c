/* Host tests for settings validation.
 *
 * This is the only thing between a typo typed into a browser and a unit that
 * does not come back, so the cases are the ones that actually strand a board:
 * a name the discovery record cannot carry, a port whose last socket runs off
 * the end, a netmask with a hole in it, and the network/broadcast addresses
 * that look like host addresses at 2 a.m. */
#include <stdio.h>
#include <string.h>

#include "config_check.h"

static int checks = 0, fails = 0;
#define CHECK(c, ...) do { checks++; if (!(c)) { \
    fails++; printf("  FAIL %s:%d  ", __FILE__, __LINE__); printf(__VA_ARGS__); \
    printf("\n"); } } while (0)

#define IP4(a, b, c, d) (((uint32_t)(a) << 24) | ((uint32_t)(b) << 16) | \
                         ((uint32_t)(c) << 8) | (uint32_t)(d))

/* A valid static configuration, to be broken one field at a time. */
static cfg_t good_static(void)
{
    cfg_t c;
    cfg_defaults(&c);
    c.eth_mode = CFG_IPV4_STATIC;
    c.eth_ip = IP4(192, 168, 1, 90);
    c.eth_netmask = IP4(255, 255, 255, 0);
    c.eth_gw = 0;
    return c;
}

int main(void)
{
    printf("config_check tests\n");

    {
        cfg_t c;
        cfg_defaults(&c);
        CHECK(cfg_validate(&c) == NULL, "the defaults must validate");
        CHECK(strcmp(c.hostname, "CANary") == 0, "default name is CANary");
        CHECK(c.base_port == 30000, "default port is the R70's");
        CHECK(c.socket_count == 4, "default socket count is the R70's");
        CHECK(c.eth_mode == CFG_IPV4_DHCP, "default is DHCP, as it always was");
    }
    CHECK(cfg_validate(NULL) != NULL, "a NULL config is not valid");

    /* ---- host name ---------------------------------------------------- */
    {
        cfg_t c; cfg_defaults(&c);
        c.hostname[0] = '\0';
        CHECK(cfg_validate(&c) != NULL, "an empty name is refused");
    }
    {
        /* A name that fills the field with no terminator is both "too long"
         * and "unterminated" - the field is sized so that those are the same
         * fault, and this is the only test of that guard, so it is also the
         * one that fails if the guard is removed. */
        cfg_t c; cfg_defaults(&c);
        memset(c.hostname, 'a', sizeof(c.hostname));
        CHECK(cfg_validate(&c) != NULL, "a name with no terminator is refused");
    }
    {
        cfg_t c; cfg_defaults(&c);
        memset(c.hostname, 'a', CFG_HOSTNAME_MAX);
        c.hostname[CFG_HOSTNAME_MAX] = '\0';
        CHECK(cfg_validate(&c) == NULL, "a name of exactly the maximum fits");
    }
    {
        cfg_t c; cfg_defaults(&c);
        strcpy(c.hostname, "db\t70");
        CHECK(cfg_validate(&c) != NULL, "a control character is refused");
        strcpy(c.hostname, "db-70 FOH");
        CHECK(cfg_validate(&c) == NULL, "a space is fine - R1 renders it");
    }

    /* ---- ports and sockets --------------------------------------------- */
    {
        cfg_t c; cfg_defaults(&c);
        c.base_port = 0;
        CHECK(cfg_validate(&c) != NULL, "port 0 is refused");
        c.base_port = 80;
        CHECK(cfg_validate(&c) != NULL, "a reserved port is refused");
        c.base_port = 1024;
        CHECK(cfg_validate(&c) == NULL, "1024 is the first allowed port");
    }
    {
        /* The bridge advertises base_port + socket_count - 1, so the last
         * socket is what has to fit, not the first. */
        cfg_t c; cfg_defaults(&c);
        c.base_port = 65535; c.socket_count = 1;
        CHECK(cfg_validate(&c) == NULL, "one socket on the last port fits");
        c.socket_count = 2;
        CHECK(cfg_validate(&c) != NULL, "two would run off the end");
        c.base_port = 65532; c.socket_count = 4;
        CHECK(cfg_validate(&c) == NULL, "four sockets ending exactly at 65535");
    }
    {
        cfg_t c; cfg_defaults(&c);
        c.socket_count = 0;
        CHECK(cfg_validate(&c) != NULL, "zero sockets is refused");
        c.socket_count = R70_DDT_MAX_SOCKETS + 1;
        CHECK(cfg_validate(&c) != NULL, "more than a real R70 offers is refused");
        c.socket_count = R70_DDT_MAX_SOCKETS;
        CHECK(cfg_validate(&c) == NULL, "exactly what a real R70 offers is fine");
    }

    /* ---- static addressing --------------------------------------------- */
    {
        cfg_t c = good_static();
        CHECK(cfg_validate(&c) == NULL, "a plain static address validates");
    }
    {
        cfg_t c = good_static();
        c.eth_ip = IP4(127, 0, 0, 1);
        CHECK(cfg_validate(&c) != NULL, "loopback is refused");
        c.eth_ip = IP4(224, 0, 0, 1);
        CHECK(cfg_validate(&c) != NULL, "multicast is refused");
    }
    {
        /* 0.0.0.0 and 255.255.255.255 also have a zero or all-ones host part
         * under any mask, so the network/broadcast tests further down refuse
         * them too - which is why deleting the guard that names them went
         * unnoticed. Assert the REASON: "that is the network address" is a
         * misleading thing to tell someone who typed 0.0.0.0, and the message
         * is what reaches the browser. */
        cfg_t c = good_static();
        c.eth_ip = 0;
        const char *why_zero = cfg_validate(&c);
        CHECK(why_zero != NULL, "0.0.0.0 is refused");
        CHECK(why_zero != NULL && strstr(why_zero, "interface can hold") != NULL,
              "0.0.0.0 refused as a non-address, not as a network address: "
              "got \"%s\"", why_zero ? why_zero : "(accepted)");

        c.eth_ip = IP4(255, 255, 255, 255);
        const char *why_bcast = cfg_validate(&c);
        CHECK(why_bcast != NULL, "255.255.255.255 is refused");
        CHECK(why_bcast != NULL &&
              strstr(why_bcast, "interface can hold") != NULL,
              "255.255.255.255 refused as a non-address: got \"%s\"",
              why_bcast ? why_bcast : "(accepted)");
    }
    {
        cfg_t c = good_static();
        c.eth_netmask = IP4(255, 255, 0, 255);
        CHECK(cfg_validate(&c) != NULL, "a mask with a hole in it is refused");
        c.eth_netmask = 0;
        CHECK(cfg_validate(&c) != NULL, "a zero mask is refused");
        /* A /32 has a zero host part too, so the network-address check would
         * refuse it anyway - and did, which is why deleting the /32 guard
         * went unnoticed. Assert the REASON, because it is the reason that
         * reaches the browser and a technician reading "that is the network
         * address" about a /32 is being told the wrong thing. */
        c.eth_netmask = IP4(255, 255, 255, 255);
        const char *why = cfg_validate(&c);
        CHECK(why != NULL, "a /32 is refused");
        CHECK(why != NULL && strstr(why, "/32") != NULL,
              "and refused AS a /32, not as a network address: got \"%s\"",
              why ? why : "(accepted)");
        c.eth_netmask = IP4(255, 255, 255, 252);
        c.eth_ip = IP4(192, 168, 1, 90);
        CHECK(cfg_validate(&c) == NULL, "a /30 with a host in it is fine");
    }
    {
        /* The 2 a.m. mistakes. */
        cfg_t c = good_static();
        c.eth_ip = IP4(192, 168, 1, 0);
        CHECK(cfg_validate(&c) != NULL, "the network address is refused");
        c.eth_ip = IP4(192, 168, 1, 255);
        CHECK(cfg_validate(&c) != NULL, "the broadcast address is refused");
    }
    {
        cfg_t c = good_static();
        c.eth_gw = IP4(192, 168, 1, 1);
        CHECK(cfg_validate(&c) == NULL, "a gateway on the subnet is fine");
        c.eth_gw = IP4(10, 0, 0, 1);
        CHECK(cfg_validate(&c) != NULL, "a gateway off the subnet is refused");
        c.eth_gw = c.eth_ip;
        CHECK(cfg_validate(&c) != NULL, "we are not our own gateway");
        c.eth_gw = 0;
        CHECK(cfg_validate(&c) == NULL, "no gateway at all is normal here");
    }
    {
        /* A static address is only checked in static mode: leftover values
         * from a previous static configuration must not block a return to
         * DHCP, which is the way out of a bad static address. */
        cfg_t c = good_static();
        c.eth_ip = IP4(127, 0, 0, 1);
        c.eth_netmask = 0;
        c.eth_mode = CFG_IPV4_DHCP;
        CHECK(cfg_validate(&c) == NULL,
              "DHCP ignores a stale static address, so you can always get back");
    }
    {
        cfg_t c = good_static();
        c.eth_mode = (cfg_ipv4_mode_t)7;
        CHECK(cfg_validate(&c) != NULL, "an unknown mode is refused");
    }

    printf("\n%d checks, %d failed\n", checks, fails);
    return fails ? 1 : 0;
}
