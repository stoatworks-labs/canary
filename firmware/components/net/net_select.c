/* Address selection for the discovery answer. See include/net_select.h. */
#include "net_select.h"

/* Number of leading 1 bits in a contiguous netmask. A non-contiguous mask
 * cannot arise from anything esp_netif hands us, and treating it as a plain
 * popcount would rank it wrongly rather than dangerously, so it is not worth a
 * rejection path. */
static int prefix_len(uint32_t netmask)
{
    int n = 0;
    while (n < 32 && (netmask & (0x80000000u >> n)) != 0) {
        n++;
    }
    return n;
}

uint32_t net_select_source(const net_iface_t *ifaces, size_t count,
                           uint32_t peer)
{
    if (ifaces == NULL) {
        return 0;
    }

    if (peer != 0) {
        uint32_t best_ip = 0;
        int best_prefix = -1;
        for (size_t i = 0; i < count; i++) {
            const uint32_t ip = ifaces[i].ip;
            const uint32_t mask = ifaces[i].netmask;
            if (ip == 0 || mask == 0) {
                /* A zero mask matches everything, which would make an
                 * unconfigured interface swallow every peer. */
                continue;
            }
            if ((ip & mask) != (peer & mask)) {
                continue;
            }
            const int len = prefix_len(mask);
            if (len > best_prefix) {
                best_prefix = len;
                best_ip = ip;
            }
        }
        if (best_prefix >= 0) {
            return best_ip;
        }
    }

    for (size_t i = 0; i < count; i++) {
        if (ifaces[i].ip != 0) {
            return ifaces[i].ip;
        }
    }
    return 0;
}
