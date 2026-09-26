/*
 * Which of our addresses to tell a peer about.
 *
 * WHY THIS EXISTS: with only the W5500 there was one address and
 * bridge_local_ip() could return it. A USB-NCM interface gives the unit a
 * SECOND address, on a point-to-point link that reaches exactly one host, and
 * the discovery answer carries an address R1 then connects to while ignoring
 * the UDP sender entirely (docs/PROTOCOL.md §4). Answer a probe that arrived
 * over USB with the Ethernet address and R1 lists a device it can never open a
 * socket to - the failure mode that reads, from the R1 end, as "it appears and
 * then refuses", which is the hardest one to diagnose.
 *
 * So the address is chosen per probe, from the probe's source address. Kept
 * ESP-IDF-free and pure so it can be tested on the host against the address
 * pairs that actually occur.
 */
#ifndef NET_SELECT_H
#define NET_SELECT_H

#include <stddef.h>
#include <stdint.h>

/* One interface's IPv4 identity, host byte order. ip == 0 means "no address
 * yet" and the entry is skipped. */
typedef struct {
    uint32_t ip;
    uint32_t netmask;
} net_iface_t;

/* Pick the address to advertise to a peer at `peer` (host byte order).
 *
 * Rules, in order:
 *   1. An interface whose subnet contains `peer` wins. If several do - which
 *      means overlapping subnets, a misconfiguration rather than a routing
 *      question - the longest prefix wins, and a tie goes to the earlier entry.
 *   2. Otherwise the first entry that has an address at all.
 *   3. 0 if nothing has one.
 *
 * Rule 2 is why ORDER MATTERS and why the caller must list the routable
 * interface first: a peer we cannot place is reachable, if at all, over the
 * wired side. The USB link is point to point and routes nowhere, so it must
 * never be the fallback - offering it to an off-link peer is how a unit that
 * is reachable ends up advertising an address that is not.
 *
 * A `peer` of 0 means "no particular peer" and takes rule 2 directly. */
uint32_t net_select_source(const net_iface_t *ifaces, size_t count,
                           uint32_t peer);

#endif /* NET_SELECT_H */
