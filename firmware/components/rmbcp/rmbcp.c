/* RM Byte Command Protocol codec. See include/rmbcp.h and docs/PROTOCOL.md §2. */
#include "rmbcp.h"

#include <string.h>

uint8_t rmbcp_checksum(uint8_t length, uint8_t command,
                       const uint8_t *data, uint8_t len)
{
    uint8_t c = (uint8_t)(RMBCP_SOF ^ length ^ command);
    for (uint8_t i = 0; i < len; i++) {
        c ^= data[i];
    }
    return c;
}

size_t rmbcp_encode(uint8_t command, const uint8_t *data, uint8_t len,
                    uint8_t *out)
{
    if (len > RMBCP_MAX_DATA) {
        return 0;
    }
    const uint8_t length = (uint8_t)(1u + len); /* command byte + data bytes */
    size_t n = 0;
    out[n++] = RMBCP_SOF;
    out[n++] = length;
    out[n++] = command;
    if (len) {
        memcpy(&out[n], data, len);
        n += len;
    }
    out[n++] = rmbcp_checksum(length, command, data, len);
    out[n++] = RMBCP_EOF;
    return n;
}

size_t rmbcp_encode_can(const rmbcp_can_t *msg, uint8_t *out)
{
    if (msg->dlc > 8) {
        return 0;
    }
    const uint8_t id_len = msg->extended ? 4u : 2u;
    if (!msg->extended && msg->id > 0x7FFu) {
        return 0;
    }
    if (msg->extended && msg->id > 0x1FFFFFFFu) {
        return 0;
    }

    uint8_t cmd;
    if (msg->extended) {
        cmd = msg->has_timestamp ? RMBCP_CMD_CAN29_TS : RMBCP_CMD_CAN29;
    } else {
        cmd = msg->has_timestamp ? RMBCP_CMD_CAN11_TS : RMBCP_CMD_CAN11;
    }

    uint8_t body[RMBCP_MAX_DATA];
    uint8_t n = 0;

    if (msg->channel) {
        /* Extended form: data[0]=channel, data[1]=the real command. */
        body[n++] = msg->channel;
        body[n++] = cmd;
        cmd = RMBCP_CMD_EXT_LO;
    }

    /* Identifier, MSB first. */
    for (int8_t i = (int8_t)(id_len - 1); i >= 0; i--) {
        body[n++] = (uint8_t)(msg->id >> (8 * i));
    }
    memcpy(&body[n], msg->data, msg->dlc);
    n = (uint8_t)(n + msg->dlc);

    if (msg->has_timestamp) {
        for (int8_t i = 3; i >= 0; i--) {
            body[n++] = (uint8_t)(msg->timestamp >> (8 * i));
        }
    }
    return rmbcp_encode(cmd, body, n, out);
}

uint8_t rmbcp_unwrap_extended(rmbcp_frame_t *frame)
{
    if (frame->command < RMBCP_CMD_EXT_LO || frame->command > RMBCP_CMD_EXT_HI) {
        return 0;
    }
    if (frame->len < 2) {
        return 0; /* malformed; leave it alone rather than read past the data */
    }
    const uint8_t channel = frame->data[0];
    frame->command = frame->data[1];
    frame->len = (uint8_t)(frame->len - 2);
    memmove(frame->data, &frame->data[2], frame->len);
    return channel;
}

bool rmbcp_frame_as_can(const rmbcp_frame_t *frame, rmbcp_can_t *out)
{
    bool extended, timestamped;
    switch (frame->command) {
    case RMBCP_CMD_CAN11:    extended = false; timestamped = false; break;
    case RMBCP_CMD_CAN11_TS: extended = false; timestamped = true;  break;
    case RMBCP_CMD_CAN29:    extended = true;  timestamped = false; break;
    case RMBCP_CMD_CAN29_TS: extended = true;  timestamped = true;  break;
    default: return false;
    }

    const uint8_t id_len = extended ? 4u : 2u;
    const uint8_t ts_len = timestamped ? 4u : 0u;
    if (frame->len < (uint8_t)(id_len + ts_len)) {
        return false;
    }
    const uint8_t dlc = (uint8_t)(frame->len - id_len - ts_len);
    if (dlc > 8) {
        return false;
    }

    memset(out, 0, sizeof(*out));
    out->extended = extended;
    out->has_timestamp = timestamped;
    out->dlc = dlc;

    for (uint8_t i = 0; i < id_len; i++) {
        out->id = (out->id << 8) | frame->data[i];
    }
    memcpy(out->data, &frame->data[id_len], dlc);
    if (timestamped) {
        const uint8_t *ts = &frame->data[id_len + dlc];
        out->timestamp = ((uint32_t)ts[0] << 24) | ((uint32_t)ts[1] << 16) |
                         ((uint32_t)ts[2] << 8) | ts[3];
    }
    return true;
}

/* --- Stream decoder ------------------------------------------------------- */

void rmbcp_decoder_init(rmbcp_decoder_t *dec)
{
    dec->used = 0;
    dec->bad_frames = 0;
}

size_t rmbcp_decoder_feed(rmbcp_decoder_t *dec, const uint8_t *data, size_t len)
{
    const size_t space = sizeof(dec->buf) - dec->used;
    const size_t take = len < space ? len : space;
    memcpy(&dec->buf[dec->used], data, take);
    dec->used += take;

    if (take == len) {
        return 0;
    }
    /* Buffer full with no valid frame in it: the peer is sending garbage. Keep
     * the newest bytes, which are the ones that might still resynchronise. */
    const size_t dropped = len - take;
    dec->used = 0;
    const size_t keep = dropped < sizeof(dec->buf) ? dropped : sizeof(dec->buf);
    memcpy(dec->buf, &data[len - keep], keep);
    dec->used = keep;
    return dropped;
}

/* Index of the next SOF at or after `from`, or -1. */
static long find_sof(const rmbcp_decoder_t *dec, size_t from)
{
    for (size_t i = from; i < dec->used; i++) {
        if (dec->buf[i] == RMBCP_SOF) {
            return (long)i;
        }
    }
    return -1;
}

static void consume(rmbcp_decoder_t *dec, size_t upto)
{
    if (upto >= dec->used) {
        dec->used = 0;
        return;
    }
    memmove(dec->buf, &dec->buf[upto], dec->used - upto);
    dec->used -= upto;
}

bool rmbcp_decoder_next(rmbcp_decoder_t *dec, rmbcp_frame_t *out)
{
    long pending = -1; /* earliest candidate that might still complete */
    long i = find_sof(dec, 0);

    while (i >= 0) {
        const size_t avail = dec->used - (size_t)i;
        if (avail < 3) { /* need SOF + Length + Command */
            if (pending < 0) {
                pending = i;
            }
            break;
        }

        const uint8_t length = dec->buf[i + 1];
        if (length == 0) {
            /* Length counts the command plus its data, so 1 is the smallest a
             * legal frame can declare. Zero underflows len to 255 below, which
             * reads up to 259 bytes past this SOF — off the end of buf when the
             * SOF lands late — and then memcpys 255 bytes into a 254-byte
             * data[], overwriting out->len with a byte the peer chose. TCP
             * 30000 is unauthenticated, so treat it as the hostile input it is:
             * a bad frame, resynchronise. */
            dec->bad_frames++;
            i = find_sof(dec, (size_t)i + 1);
            continue;
        }
        const size_t total = (size_t)length + 4;
        if (avail < total) {
            /* Might be a real frame in flight, or a garbage length byte. Note
             * it, but keep looking for one we can prove valid. */
            if (pending < 0) {
                pending = i;
            }
            i = find_sof(dec, (size_t)i + 1);
            continue;
        }

        const uint8_t command = dec->buf[i + 2];
        const uint8_t *data = &dec->buf[i + 3];
        const uint8_t len = (uint8_t)(length - 1);
        if (dec->buf[i + 3 + len] == rmbcp_checksum(length, command, data, len) &&
            dec->buf[i + 4 + len] == RMBCP_EOF) {
            out->command = command;
            out->len = len;
            memcpy(out->data, data, len);
            consume(dec, (size_t)i + total);
            return true;
        }

        dec->bad_frames++;
        i = find_sof(dec, (size_t)i + 1);
    }

    /* Nothing provably valid. Keep only what could still become a frame. */
    consume(dec, pending >= 0 ? (size_t)pending : dec->used);
    return false;
}
