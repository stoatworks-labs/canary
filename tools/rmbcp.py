"""
RM Byte Command Protocol (RMBCP) codec.

This is the wire protocol spoken by the d&b R70 Ethernet-to-CAN interface. The
R70 is an OEM RM Michaelides gateway (now Proemion) — see docs/PROTOCOL.md for
how that was established. The protocol is publicly documented, so nothing here
is guesswork: every field below comes from "RM Byte Command Protocol — API
description" — see docs/SOURCES.md for where to get it.

Frame layout:

    SOF | Length | Command | Data... | Checksum | EOF
    0x43   1 byte   1 byte    n bytes   1 byte     0x0D

  Length   = number of bytes between Length and Checksum (command + data)
  Checksum = XOR of SOF, Length, Command and every Data byte
  SOF/EOF  = configurable on some devices; the R70 uses the defaults.

Several frames may be concatenated inside a single TCP segment or UDP datagram —
that is what the R70's "Block Time (x10ms)" setting batches. Decoding therefore
has to be stream-oriented, not datagram-oriented.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SOF = 0x43  # 'C'
EOF = 0x0D  # <CR>

# --- Command bytes (subset relevant to a transparent CAN bridge) -------------
# Process data
CMD_CAN11 = 0x00  # 11-bit ID CAN message
CMD_CAN11_TS = 0x01  # ... + 32-bit timestamp
CMD_CAN29 = 0x02  # 29-bit ID CAN message
CMD_CAN29_TS = 0x03  # ... + 32-bit timestamp
# Diagnosis
CMD_DEVICE_ID = 0x40  # device ID string; last 2 data bytes = 16-bit device id
CMD_VERSION = 0x41  # HW ver, FW ver, bootloader ver (2 bytes each)
CMD_BUSLOAD = 0x47  # CAN bus load, messages/interval
# Device parameters
CMD_IP_BLOCK_WAIT = 0xA3  # "Block Time", interval in units of 10 ms

# Extended-command range: data[0]=CAN channel, data[1]=command, data[2:]=payload
CMD_EXT_LO, CMD_EXT_HI = 0xD0, 0xDF

_TS_CMDS = frozenset({CMD_CAN11_TS, CMD_CAN29_TS})
_29BIT_CMDS = frozenset({CMD_CAN29, CMD_CAN29_TS})
_CAN_CMDS = frozenset({CMD_CAN11, CMD_CAN11_TS, CMD_CAN29, CMD_CAN29_TS})


def checksum(sof: int, length: int, command: int, data: bytes) -> int:
    """XOR checksum over SOF, Length, Command and the data bytes."""
    c = sof ^ length ^ command
    for b in data:
        c ^= b
    return c


def encode(command: int, data: bytes = b"") -> bytes:
    """Build one RMBCP frame."""
    length = 1 + len(data)  # command byte + data bytes
    if not 0 <= length <= 0xFF:
        raise ValueError(f"frame too long: {length} bytes")
    return bytes([SOF, length, command, *data, checksum(SOF, length, command, data), EOF])


@dataclass(frozen=True)
class Frame:
    """A decoded RMBCP frame."""

    command: int
    data: bytes

    # --- CAN convenience views ----------------------------------------------
    @property
    def is_can(self) -> bool:
        return self.command in _CAN_CMDS

    @property
    def is_extended_id(self) -> bool:
        return self.command in _29BIT_CMDS

    @property
    def has_timestamp(self) -> bool:
        return self.command in _TS_CMDS

    def as_can(self) -> tuple[int, bytes, int | None]:
        """Return (can_id, payload, timestamp_or_None) for a process-data frame."""
        if not self.is_can:
            raise ValueError(f"command 0x{self.command:02X} is not a CAN process-data frame")
        id_len = 4 if self.is_extended_id else 2
        body = self.data
        ts = None
        if self.has_timestamp:
            if len(body) < id_len + 4:
                raise ValueError("frame too short to contain its timestamp")
            ts = int.from_bytes(body[-4:], "big")
            body = body[:-4]
        can_id = int.from_bytes(body[:id_len], "big")
        return can_id, body[id_len:], ts


def encode_can(can_id: int, payload: bytes, *, extended: bool = False,
               timestamp: int | None = None, channel: int | None = None) -> bytes:
    """Encode a CAN frame as RMBCP. `channel` selects the extended command form."""
    if len(payload) > 8:
        raise ValueError("CAN 2.0 payload is at most 8 bytes")
    id_len = 4 if extended else 2
    if can_id >= (1 << 29 if extended else 1 << 11) or can_id < 0:
        raise ValueError(f"CAN id 0x{can_id:X} out of range")

    if extended:
        cmd = CMD_CAN29_TS if timestamp is not None else CMD_CAN29
    else:
        cmd = CMD_CAN11_TS if timestamp is not None else CMD_CAN11
    data = can_id.to_bytes(id_len, "big") + payload
    if timestamp is not None:
        data += timestamp.to_bytes(4, "big")

    if channel is None:
        return encode(cmd, data)
    # Extended form: command 0xD0, data[0]=channel, data[1]=real command
    return encode(CMD_EXT_LO, bytes([channel, cmd]) + data)


def unwrap_extended(frame: Frame) -> tuple[int, Frame]:
    """Split an extended-command frame into (channel, inner frame)."""
    if not CMD_EXT_LO <= frame.command <= CMD_EXT_HI:
        return 0, frame
    if len(frame.data) < 2:
        raise ValueError("extended command needs at least channel + command bytes")
    return frame.data[0], Frame(command=frame.data[1], data=frame.data[2:])


@dataclass
class Decoder:
    """
    Incremental, resynchronising RMBCP decoder.

    Feed it arbitrary byte runs; it yields whole frames.

    Resynchronisation matters here: a TCP stream can start mid-frame, and 0x43 is
    perfectly legal CAN payload, so any given SOF may be a false start. We cannot
    distinguish "incomplete real frame" from "garbage length byte" by looking at
    one candidate, so each pass scans *every* SOF position and takes the first
    that yields a complete, checksum-valid frame. Only if none does do we keep the
    earliest still-incomplete candidate and wait for more bytes — which is what
    stops a bogus length from stalling the stream forever.
    """

    buf: bytearray = field(default_factory=bytearray)
    bad_frames: int = 0

    def feed(self, chunk: bytes) -> list[Frame]:
        self.buf.extend(chunk)
        out: list[Frame] = []
        while True:
            frame = self._next()
            if frame is None:
                return out
            out.append(frame)

    def _next(self) -> Frame | None:
        pending: int | None = None  # earliest candidate that may still complete
        i = self.buf.find(SOF)
        while i >= 0:
            avail = len(self.buf) - i
            if avail < 3:  # need at least SOF + Length + Command
                pending = i if pending is None else pending
                break

            length = self.buf[i + 1]
            if length == 0:
                # Length counts the command plus its data, so 1 is the minimum a
                # legal frame can declare. Python would reject this anyway — the
                # checksum byte and the command byte end up being the same byte,
                # which can never satisfy c = SOF ^ 0 ^ command — but only by
                # accident, and the C decoder had a real out-of-bounds read here
                # (see the regression vectors in test_rmbcp.py). Both sides
                # reject it deliberately now.
                self.bad_frames += 1
                i = self.buf.find(SOF, i + 1)
                continue

            total = length + 4  # SOF + Length + (command+data) + checksum + EOF
            if avail < total:
                # Might be a real frame still in flight, or a garbage length.
                # Remember it, but keep looking for a frame we can prove valid.
                pending = i if pending is None else pending
                i = self.buf.find(SOF, i + 1)
                continue

            command = self.buf[i + 2]
            data = bytes(self.buf[i + 3:i + 2 + length])
            got_ck, got_eof = self.buf[i + 2 + length], self.buf[i + 3 + length]
            if got_eof == EOF and got_ck == checksum(SOF, length, command, data):
                del self.buf[:i + total]
                return Frame(command=command, data=data)

            # Complete but malformed: that SOF was payload or the frame is corrupt.
            self.bad_frames += 1
            i = self.buf.find(SOF, i + 1)

        # Nothing provably valid this pass. Keep only what could still become a
        # frame; a buffer with no SOF at all is pure garbage and gets dropped.
        del self.buf[:pending if pending is not None else len(self.buf)]
        return None


# --- dbCAN identifier helpers ------------------------------------------------
# dbCAN is CAN 2.0A layer 2 at 100 kbit/s. The 11-bit identifier is structured:
#   bits 10-9  object class   bits 8-6  subnet (0-7)   bits 5-0  device id (0-63)

OBJ_PRIMARY_MASTER = 0
OBJ_SECONDARY_MASTER = 1
OBJ_DEVICE_PROCESS_DATA = 2
OBJ_STREAM = 3

OBJECT_CLASS_NAMES = {
    OBJ_PRIMARY_MASTER: "primary-master",
    OBJ_SECONDARY_MASTER: "secondary-master",
    OBJ_DEVICE_PROCESS_DATA: "device-process-data",
    OBJ_STREAM: "stream",
}


def dbcan_id(object_class: int, subnet: int, device: int) -> int:
    """Pack a dbCAN 11-bit identifier. Device 0 broadcasts into the subnet."""
    if not 0 <= object_class <= 3:
        raise ValueError("object class is 0-3")
    if not 0 <= subnet <= 7:
        raise ValueError("subnet is 0-7")
    if not 0 <= device <= 63:
        raise ValueError("device id is 0-63")
    return (object_class << 9) | (subnet << 6) | device


def parse_dbcan_id(can_id: int) -> tuple[int, int, int]:
    """Unpack an 11-bit dbCAN identifier into (object_class, subnet, device)."""
    if not 0 <= can_id < (1 << 11):
        raise ValueError(f"not an 11-bit identifier: 0x{can_id:X}")
    return (can_id >> 9) & 0x3, (can_id >> 6) & 0x7, can_id & 0x3F


def describe_dbcan_id(can_id: int) -> str:
    """
    Human-readable dbCAN id, e.g. 'device-process-data 0.01'.

    Always shows the subnet. Device 0 is a broadcast *into a subnet*, not a
    global one, so collapsing it to the word "broadcast" alone would hide which
    subnet is being addressed — which is exactly what you need when watching R1
    sweep all eight of them.
    """
    cls, subnet, device = parse_dbcan_id(can_id)
    who = f"{subnet}.{device:02d}"
    if device == 0:
        who += " (broadcast)"
    return f"{OBJECT_CLASS_NAMES[cls]} {who}"
