/*
 * RM Byte Command Protocol — the wire protocol the d&b R70 speaks to R1.
 *
 * Kept ESP-IDF-free so the framing can be tested on the host against the worked
 * examples printed in the vendor spec (see test/). Everything here is from
 * "RM Byte Command Protocol — API description"; see docs/PROTOCOL.md §2.
 *
 *   SOF | Length | Command | Data... | Checksum | EOF
 *   0x43   1 by     1 by     n bytes    1 byte    0x0D
 *
 *   Length   = command byte + data bytes (i.e. bytes between Length and Checksum)
 *   Checksum = XOR of SOF, Length, Command and every Data byte
 *
 * Two hazards this API exists to handle:
 *   - 0x43 and 0x0D are legal CAN payload bytes and are NOT escaped, so only
 *     Length + Checksum + EOF agreeing together identifies a frame.
 *   - Many frames share one TCP segment (that is what the R70's "Block Time"
 *     batches), so decoding must be stream-oriented.
 */
#ifndef RMBCP_H
#define RMBCP_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define RMBCP_SOF 0x43u /* 'C' */
#define RMBCP_EOF 0x0Du /* <CR> */

/* Length is one byte, so a frame is at most SOF+Len+255+checksum+EOF. */
#define RMBCP_MAX_DATA  254
#define RMBCP_MAX_FRAME 259

/* Process data */
#define RMBCP_CMD_CAN11     0x00u /* 11-bit CAN message */
#define RMBCP_CMD_CAN11_TS  0x01u /* ... plus 32-bit timestamp */
#define RMBCP_CMD_CAN29     0x02u /* 29-bit CAN message */
#define RMBCP_CMD_CAN29_TS  0x03u /* ... plus 32-bit timestamp */
/* Diagnosis / settings */
#define RMBCP_CMD_DEVICE_ID 0x40u
#define RMBCP_CMD_VERSION   0x41u
#define RMBCP_CMD_ERROR     0x42u
#define RMBCP_CMD_IFVERSION 0x44u
#define RMBCP_CMD_BUSLOAD   0x47u
#define RMBCP_CMD_NOTSUPP   0x48u
#define RMBCP_CMD_BAUD_REQ  0x56u
#define RMBCP_CMD_BAUD_SET  0x57u
#define RMBCP_CMD_CAN_RESET 0x58u
#define RMBCP_CMD_BLOCKTIME 0xA3u
#define RMBCP_CMD_BAUDCALC  0xA4u
#define RMBCP_CMD_RESET_DEV 0xC0u
/* Extended form: data[0]=CAN channel, data[1]=real command */
#define RMBCP_CMD_EXT_LO 0xD0u
#define RMBCP_CMD_EXT_HI 0xDFu

/* Baud-rate codes, from the spec's table. dbCAN is fixed at 100 kbit/s. */
#define RMBCP_BAUD_100K 0xFEu

typedef struct {
    uint8_t command;
    uint8_t data[RMBCP_MAX_DATA];
    uint8_t len; /* bytes used in data */
} rmbcp_frame_t;

typedef struct {
    uint32_t id;
    uint8_t data[8];
    uint8_t dlc;
    bool extended;      /* 29-bit identifier */
    bool has_timestamp;
    uint32_t timestamp; /* only valid when has_timestamp */
    uint8_t channel;    /* 0 unless the frame used the extended command form */
} rmbcp_can_t;

/* XOR checksum over SOF, Length, Command and the data bytes. */
uint8_t rmbcp_checksum(uint8_t length, uint8_t command,
                       const uint8_t *data, uint8_t len);

/* Encode one frame into out (needs RMBCP_MAX_FRAME bytes). Returns length, or
 * 0 if len exceeds RMBCP_MAX_DATA. */
size_t rmbcp_encode(uint8_t command, const uint8_t *data, uint8_t len,
                    uint8_t *out);

/* Encode a CAN frame. channel 0 uses the plain command form; 1..127 uses the
 * extended form. Returns bytes written, or 0 on invalid input. */
size_t rmbcp_encode_can(const rmbcp_can_t *msg, uint8_t *out);

/* Interpret a decoded frame as CAN process data. false if it is not one. */
bool rmbcp_frame_as_can(const rmbcp_frame_t *frame, rmbcp_can_t *out);

/* If the frame is the extended form, unwrap it in place to the inner command.
 * Returns the CAN channel (0 when not extended). */
uint8_t rmbcp_unwrap_extended(rmbcp_frame_t *frame);

/* --- Stream decoder ---
 * Feed arbitrary byte runs; pull whole frames out one at a time. Resynchronises
 * by scanning every SOF position for the first provably valid frame, so a
 * corrupt length byte costs one frame rather than stalling the stream. */
typedef struct {
    uint8_t buf[RMBCP_MAX_FRAME * 2];
    size_t used;
    uint32_t bad_frames; /* complete-but-malformed candidates rejected */
} rmbcp_decoder_t;

void rmbcp_decoder_init(rmbcp_decoder_t *dec);

/* Append bytes. Returns the number dropped because the buffer was full (only
 * possible if the peer sends garbage containing no valid frame). */
size_t rmbcp_decoder_feed(rmbcp_decoder_t *dec, const uint8_t *data, size_t len);

/* Pop the next complete frame. Returns false when none is available yet. */
bool rmbcp_decoder_next(rmbcp_decoder_t *dec, rmbcp_frame_t *out);

/* --- dbCAN identifiers ---
 * CAN 2.0A, 11-bit: bits 10-9 object class, 8-6 subnet, 5-0 device id. */
#define DBCAN_OBJ_PRIMARY_MASTER   0u
#define DBCAN_OBJ_SECONDARY_MASTER 1u
#define DBCAN_OBJ_DEVICE_DATA      2u
#define DBCAN_OBJ_STREAM           3u

#define DBCAN_BITRATE 100000 /* fixed; "can not be changed" per the R70 manual */

static inline uint16_t dbcan_id(uint8_t object_class, uint8_t subnet,
                                uint8_t device)
{
    return (uint16_t)(((object_class & 0x3u) << 9) | ((subnet & 0x7u) << 6) |
                      (device & 0x3Fu));
}
static inline uint8_t dbcan_object_class(uint16_t id) { return (id >> 9) & 0x3u; }
static inline uint8_t dbcan_subnet(uint16_t id) { return (id >> 6) & 0x7u; }
static inline uint8_t dbcan_device(uint16_t id) { return id & 0x3Fu; }

#endif /* RMBCP_H */
