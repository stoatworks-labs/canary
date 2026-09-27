/*
 * Defaults and validation. See include/config_store.h.
 *
 * ESP-IDF-free on purpose: this is the only thing between a typo typed into a
 * browser and a unit that does not come back, so it is host-tested against the
 * values that actually break things.
 */
#include "config_check.h"

#include <stddef.h>
#include <string.h>

void cfg_defaults(cfg_t *out)
{
    if (out == NULL) {
        return;
    }
    memset(out, 0, sizeof(*out));
    /* Our own name, not the R70's factory "db-70", so R1's list says what the
     * unit is. R1 shows it verbatim, and a rig with two units on defaults shows
     * two identically named entries - which is exactly why being able to change
     * it is the first reason this component exists. */
    strcpy(out->hostname, "CANary");
    out->base_port = 30000;
    out->socket_count = 4;
    out->eth_mode = CFG_IPV4_DHCP;
}

/* 127.0.0.0/8, 224.0.0.0/4 and 255.255.255.255 are not addresses an interface
 * can usefully hold; 0.0.0.0 means "unset" everywhere else in this codebase. */
static bool usable_host_address(uint32_t ip)
{
    if (ip == 0 || ip == 0xFFFFFFFFu) {
        return false;
    }
    if ((ip & 0xFF000000u) == 0x7F000000u) {   /* loopback */
        return false;
    }
    if ((ip & 0xF0000000u) == 0xE0000000u) {   /* multicast and above */
        return false;
    }
    return true;
}

/* A netmask is a run of 1s then a run of 0s. Adding 1 to the inverse of a
 * contiguous mask gives a power of two; anything else has a hole in it. */
static bool contiguous_mask(uint32_t mask)
{
    const uint32_t inverse = ~mask;
    return (inverse & (inverse + 1u)) == 0;
}

const char *cfg_validate(const cfg_t *cfg)
{
    if (cfg == NULL) {
        return "no settings";
    }

    /* The host name must be NUL-terminated inside the field: the discovery
     * record copies it out by length, and strlen() on a run-on string reads
     * off the end of the struct before it ever reaches a length check.
     *
     * This IS the length check. The field is CFG_HOSTNAME_MAX + 1 bytes, so a
     * string terminated inside it cannot be longer than the record can carry —
     * which makes a separate `len > CFG_HOSTNAME_MAX` test unreachable. There
     * was one here; it could not fail, and deleting it is what made the
     * termination check independently provable. The static assertion below is
     * what keeps that reasoning true if anyone resizes the field. */
    _Static_assert(sizeof(((cfg_t *)0)->hostname) == CFG_HOSTNAME_MAX + 1,
                   "host name field must be exactly the record's capacity + 1, "
                   "or termination no longer implies the length is legal");

    /* A BOUNDED scan, not strlen(). strlen() on an unterminated field reads
     * off the end of the struct before any check can object - and a test for
     * that guard would then be testing undefined behaviour rather than the
     * guard. It was written with strlen() first, and the mutant that deleted
     * the guard still "passed" because the read happened to wander into
     * socket_count and trip the printable-character test instead. */
    size_t len = 0;
    while (len < sizeof(cfg->hostname) && cfg->hostname[len] != '\0') {
        len++;
    }
    if (len == sizeof(cfg->hostname)) {
        return "host name is too long for the discovery record";
    }
    if (len == 0) {
        return "host name is empty";
    }
    for (size_t i = 0; i < len; i++) {
        const char c = cfg->hostname[i];
        /* Printable ASCII only. R1 renders the name straight into a list and
         * a control character there is somebody else's crash, not ours. */
        if (c < 0x20 || c > 0x7E) {
            return "host name has a character R1 cannot display";
        }
    }

    /* Sockets before ports, because the port arithmetic below uses the count
     * and would otherwise report a nonsense range for a nonsense count: a
     * base of 0 with 0 sockets underflows to "the last socket would be above
     * port 65535", which is true and useless. */
    if (cfg->socket_count == 0) {
        return "at least one socket is needed";
    }
    if (cfg->socket_count > R70_DDT_MAX_SOCKETS) {
        return "more sockets than a real R70 offers";
    }

    /* This covers port 0 as well. There was a separate "port 0 is not a port"
     * test above it; it could not fail, because anything it caught this line
     * caught first, and "ports below 1024 are reserved" is a perfectly good
     * thing to tell someone who typed 0. */
    if (cfg->base_port < 1024) {
        return "ports below 1024 are reserved";
    }
    /* The LAST socket must fit: the bridge advertises base_port + n - 1. */
    if ((uint32_t)cfg->base_port + cfg->socket_count - 1u > 65535u) {
        return "the last socket would be above port 65535";
    }

    if (cfg->eth_mode != CFG_IPV4_DHCP && cfg->eth_mode != CFG_IPV4_STATIC) {
        return "unknown address mode";
    }

    if (cfg->eth_mode == CFG_IPV4_STATIC) {
        if (!usable_host_address(cfg->eth_ip)) {
            return "static address is not one an interface can hold";
        }
        if (!contiguous_mask(cfg->eth_netmask) || cfg->eth_netmask == 0) {
            return "netmask is not a contiguous mask";
        }
        if (cfg->eth_netmask == 0xFFFFFFFFu) {
            return "a /32 leaves nothing to talk to";
        }
        /* The host part must not be all zeroes (the network) or all ones (the
         * broadcast address): a unit on either is unreachable, and it is the
         * mistake somebody makes at 2 a.m. */
        const uint32_t host_part = cfg->eth_ip & ~cfg->eth_netmask;
        if (host_part == 0) {
            return "that is the network address, not a host address";
        }
        if (host_part == (~cfg->eth_netmask & 0xFFFFFFFFu)) {
            return "that is the broadcast address, not a host address";
        }
        /* A gateway is optional - a show network usually has none - but one
         * that is set must be reachable without a router, or it is furniture. */
        if (cfg->eth_gw != 0) {
            if (!usable_host_address(cfg->eth_gw)) {
                return "gateway is not a usable address";
            }
            if ((cfg->eth_gw & cfg->eth_netmask) !=
                (cfg->eth_ip & cfg->eth_netmask)) {
                return "gateway is not on this subnet";
            }
            if (cfg->eth_gw == cfg->eth_ip) {
                return "gateway is this unit's own address";
            }
        }
    }

    return NULL;
}
