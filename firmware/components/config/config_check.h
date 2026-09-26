/*
 * Settings: the shape of them, and what makes one unusable.
 *
 * ESP-IDF-free, like led_patterns.h, so the validation can be host-tested.
 * The storage half is include/config_store.h.
 *
 * WHY THIS EXISTS: everything the unit is was a compile-time constant until
 * now — the host name R1 shows, the TCP port, the socket count, and whether
 * the LAN side takes a lease. Changing any of them meant a toolchain, a clone
 * and a cable, which is not a thing to ask of someone with a rack to finish.
 *
 * Kept deliberately small. This is a transparent bridge (AGENTS.md §1) and the
 * settings are the ones that decide whether R1 can find it and what it is
 * called — NOT anything about dbCAN, amplifiers or the protocol, which are
 * fixed by the R70 protocol this is compatible with and are not ours to make
 * configurable.
 *
 * Reading is cheap and happens once at boot. Writing is rare and takes effect
 * at the NEXT boot: net.c hands its address to lwip during bring-up and the
 * bridge copies its config when it starts, so changing either underneath them
 * would leave half the system on the old value. Saying "reboot to apply" is
 * honest and is what a converter should do; quietly applying half of it is not.
 */
#ifndef CONFIG_CHECK_H
#define CONFIG_CHECK_H

#include <stdbool.h>
#include <stdint.h>

#include "r70_ddt.h"

/* Bounded by the discovery record: the host name lives at record offset 36 in
 * a 64-byte record and must be NUL-terminated, so R1 can never see more than
 * this many characters however they are set. Enforcing it here rather than
 * truncating later means what you typed is what R1 shows. */
#define CFG_HOSTNAME_MAX R70_DDT_HOSTNAME_MAX

typedef enum {
    CFG_IPV4_DHCP = 0,   /* lease, falling back to link-local (the default) */
    CFG_IPV4_STATIC,     /* the address below, no DHCP client at all */
} cfg_ipv4_mode_t;

/* All addresses host byte order, matching net.h, usbnet.h and bridge.h. */
typedef struct {
    char     hostname[CFG_HOSTNAME_MAX + 1];
    uint16_t base_port;     /* socket 1; the R70 default is 30000 */
    uint8_t  socket_count;  /* 1..R70_DDT_MAX_SOCKETS */

    cfg_ipv4_mode_t eth_mode;
    uint32_t eth_ip;
    uint32_t eth_netmask;
    uint32_t eth_gw;        /* 0 for none, which is normal on a show network */
} cfg_t;

/* The compile-time values this replaced, so a unit with empty NVS behaves
 * exactly as every unit did before there was an NVS. */
void cfg_defaults(cfg_t *out);

/* Why `cfg` is unusable, as a short human-readable string, or NULL if it is
 * fine. Pure and ESP-IDF-free so it can be host-tested: this is the only thing
 * standing between a typo in a browser and a unit that does not come back.
 *
 * The returned string is static and must not be freed. */
const char *cfg_validate(const cfg_t *cfg);

#endif /* CONFIG_CHECK_H */
