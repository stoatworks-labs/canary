/* R70 device detection (UDP 33333). See include/r70_ddt.h, docs/PROTOCOL.md §4. */
#include "r70_ddt.h"

#include <string.h>

static const uint8_t TAG_R70[4] = {'R', '7', '0', ' '};

bool r70_ddt_combination_valid(uint8_t service, uint8_t protocol)
{
    if (service != 1u && service != 2u) {
        return false;
    }
    if (protocol == 2u || protocol == 0xFFu) {
        return false;
    }
    /* R1 also drops (service ^ 1) | protocol == 0. */
    return (uint8_t)((service ^ 1u) | protocol) != 0u;
}

static uint8_t record_count(const uint8_t *data, size_t len)
{
    const uint8_t claimed = data[3];
    const size_t body = len - R70_DDT_HEADER_LEN;
    if ((size_t)claimed * R70_DDT_RECORD_LEN > body) {
        return 0; /* header lies about how much follows */
    }
    return claimed;
}

bool r70_ddt_is_request_for_us(const uint8_t *data, size_t len)
{
    if (len < R70_DDT_HEADER_LEN) {
        return false;
    }
    if (data[2] != R70_DDT_OP_REQUEST) {
        return false; /* not a request — our own answer, or a foreign packet */
    }
    const uint8_t count = record_count(data, len);
    if (count == 0) {
        return false;
    }
    /* R1 names the device type it is looking for in each template record. */
    for (uint8_t i = 0; i < count; i++) {
        const uint8_t *rec = &data[R70_DDT_HEADER_LEN + (size_t)i * R70_DDT_RECORD_LEN];
        if (memcmp(&rec[R70_DDT_OFF_TAG], TAG_R70, sizeof(TAG_R70)) == 0) {
            return true;
        }
    }
    return false;
}

size_t r70_ddt_build_answer(const uint8_t *probe, size_t probe_len,
                            const r70_ddt_identity_t *id, uint8_t *out,
                            size_t out_cap)
{
    if (!r70_ddt_is_request_for_us(probe, probe_len)) {
        return 0;
    }
    if (id->socket_count == 0 || id->socket_count > R70_DDT_MAX_SOCKETS) {
        return 0;
    }

    const size_t need = R70_DDT_HEADER_LEN +
                        (size_t)id->socket_count * R70_DDT_RECORD_LEN;
    if (out_cap < need) {
        return 0;
    }

    size_t name_len = id->hostname ? strlen(id->hostname) : 0;
    if (name_len > R70_DDT_HOSTNAME_MAX) {
        name_len = R70_DDT_HOSTNAME_MAX;
    }

    memset(out, 0, need);
    out[0] = probe[0];               /* echo R1's interface index */
    out[1] = 0;
    out[2] = R70_DDT_OP_ANSWER;      /* the one byte R1 actually validates */
    out[3] = id->socket_count;

    for (uint8_t i = 0; i < id->socket_count; i++) {
        const r70_ddt_socket_t *s = &id->sockets[i];
        if (!r70_ddt_combination_valid(s->service, s->protocol)) {
            return 0; /* R1 would silently drop it; fail loudly instead */
        }
        /* R1 dedups on (service, protocol, port) within one datagram. */
        for (uint8_t j = 0; j < i; j++) {
            const r70_ddt_socket_t *o = &id->sockets[j];
            if (o->service == s->service && o->protocol == s->protocol &&
                o->port == s->port) {
                return 0;
            }
        }

        uint8_t *rec = &out[R70_DDT_HEADER_LEN + (size_t)i * R70_DDT_RECORD_LEN];
        rec[R70_DDT_OFF_IP + 0] = (uint8_t)(id->ip >> 24);
        rec[R70_DDT_OFF_IP + 1] = (uint8_t)(id->ip >> 16);
        rec[R70_DDT_OFF_IP + 2] = (uint8_t)(id->ip >> 8);
        rec[R70_DDT_OFF_IP + 3] = (uint8_t)(id->ip);
        rec[R70_DDT_OFF_SERVICE] = s->service;
        rec[R70_DDT_OFF_PROTOCOL] = s->protocol;
        rec[R70_DDT_OFF_PORT + 0] = (uint8_t)(s->port >> 8);
        rec[R70_DDT_OFF_PORT + 1] = (uint8_t)(s->port);
        memcpy(&rec[R70_DDT_OFF_MAC], id->mac, sizeof(id->mac));
        memcpy(&rec[R70_DDT_OFF_TAG], TAG_R70, sizeof(TAG_R70));
        if (name_len) {
            memcpy(&rec[R70_DDT_OFF_HOSTNAME], id->hostname, name_len);
        }
    }
    return need;
}
