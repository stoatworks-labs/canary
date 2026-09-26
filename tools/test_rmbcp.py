"""
Tests for the RM Byte Command Protocol codec.

The two `test_spec_example_*` cases are the worked examples printed in the
vendor spec, checksums included — they pin the codec to the document rather than
to our reading of it. Run: python3 -m pytest tools/ -q   (or: python3 tools/test_rmbcp.py)
"""

import pytest

import rmbcp
from rmbcp import Decoder, Frame, describe_dbcan_id, dbcan_id, parse_dbcan_id


# --- Vendor spec worked examples ---------------------------------------------

def test_spec_example_basic_command():
    """Spec §2.1.1: 11-bit CAN id 0x789, data 0x11..0x18, checksum 0xCE."""
    frame = rmbcp.encode_can(0x789, bytes(range(0x11, 0x19)))
    assert frame == bytes(
        [0x43, 0x0B, 0x00, 0x07, 0x89, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0xCE, 0x0D]
    )


def test_spec_example_extended_command():
    """Spec §2.2.1: same message on CAN channel 2 (index 1), checksum 0x19."""
    frame = rmbcp.encode_can(0x789, bytes(range(0x11, 0x19)), channel=1)
    assert frame == bytes(
        [0x43, 0x0D, 0xD0, 0x01, 0x00, 0x07, 0x89,
         0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19, 0x0D]
    )


def test_length_counts_command_plus_data():
    """Length is the byte count between Length and Checksum."""
    frame = rmbcp.encode(rmbcp.CMD_DEVICE_ID, b"")
    assert frame[1] == 1  # command byte only
    assert len(frame) == 5


# --- Round-trip ---------------------------------------------------------------

@pytest.mark.parametrize(
    "can_id,payload,extended,timestamp",
    [
        (0x001, b"", False, None),
        (0x789, bytes(range(8)), False, None),
        (0x400, b"\x01\x02", False, 0xDEADBEEF),
        (0x1FFFFFFF, bytes(range(8)), True, None),
        (0x0ABCDEF, b"\xff", True, 12345),
    ],
)
def test_can_round_trip(can_id, payload, extended, timestamp):
    wire = rmbcp.encode_can(can_id, payload, extended=extended, timestamp=timestamp)
    (frame,) = Decoder().feed(wire)
    assert frame.is_extended_id is extended
    assert frame.as_can() == (can_id, payload, timestamp)


def test_extended_command_round_trip():
    wire = rmbcp.encode_can(0x123, b"\xaa\xbb", channel=3)
    (frame,) = Decoder().feed(wire)
    channel, inner = rmbcp.unwrap_extended(frame)
    assert channel == 3
    assert inner.as_can() == (0x123, b"\xaa\xbb", None)


# --- Stream decoding ----------------------------------------------------------

def test_blocked_frames_in_one_segment():
    """Block Time batches several CAN frames into one TCP segment."""
    wire = b"".join(rmbcp.encode_can(i, bytes([i])) for i in range(1, 6))
    frames = Decoder().feed(wire)
    assert [f.as_can()[0] for f in frames] == [1, 2, 3, 4, 5]


def test_byte_at_a_time_reassembly():
    """A frame split across arbitrarily many reads must still decode once."""
    wire = rmbcp.encode_can(0x2AA, b"\x01\x02\x03")
    dec, got = Decoder(), []
    for b in wire:
        got += dec.feed(bytes([b]))
    assert len(got) == 1
    assert got[0].as_can() == (0x2AA, b"\x01\x02\x03", None)


def test_payload_containing_sof_and_eof_bytes():
    """0x43 and 0x0D are legal CAN data — the codec must not resync on them."""
    payload = b"\x43\x0d\x43\x43\x0d"
    wire = rmbcp.encode_can(0x100, payload)
    (frame,) = Decoder().feed(wire)
    assert frame.as_can() == (0x100, payload, None)


def test_resyncs_after_leading_garbage():
    good = rmbcp.encode_can(0x321, b"\x09")
    frames = Decoder().feed(b"\x00\xff\x43\x99" + good)
    assert [f.as_can()[0] for f in frames] == [0x321]


def test_bad_checksum_does_not_swallow_following_frame():
    """A corrupt frame must cost us that frame only, not the stream."""
    bad = bytearray(rmbcp.encode_can(0x111, b"\x01\x02"))
    bad[-2] ^= 0xFF  # break the checksum
    good = rmbcp.encode_can(0x222, b"\x03")
    dec = Decoder()
    frames = dec.feed(bytes(bad) + good)
    assert [f.as_can()[0] for f in frames] == [0x222]
    assert dec.bad_frames > 0


def test_partial_frame_is_held_not_dropped():
    wire = rmbcp.encode_can(0x123, bytes(range(8)))
    dec = Decoder()
    assert dec.feed(wire[:6]) == []
    assert [f.as_can()[0] for f in dec.feed(wire[6:])] == [0x123]


# --- dbCAN identifier layout --------------------------------------------------

def test_dbcan_id_layout():
    """Spec: bits 10-9 class, 8-6 subnet, 5-0 device."""
    assert dbcan_id(rmbcp.OBJ_PRIMARY_MASTER, 0, 1) == 0x001
    assert dbcan_id(rmbcp.OBJ_DEVICE_PROCESS_DATA, 0, 1) == 0x401
    assert dbcan_id(rmbcp.OBJ_STREAM, 7, 63) == 0x7FF


def test_dbcan_id_matches_r70_filtering_example():
    """
    R70 software manual §1.3.2 worked example: with mask 0x600 / arbitration
    0x400, id 0x001 (primary master to device 0.01) is blocked and id 0x401
    (that device's reply) passes.
    """
    mask, arbitration = 0x600, 0x400
    assert ((0x001 ^ arbitration) & mask) != 0  # blocked
    assert ((0x401 ^ arbitration) & mask) == 0  # passed
    assert parse_dbcan_id(0x401) == (rmbcp.OBJ_DEVICE_PROCESS_DATA, 0, 1)


def test_describe_dbcan_id():
    assert describe_dbcan_id(0x401) == "device-process-data 0.01"
    # Device 0 broadcasts into ONE subnet, so the subnet must stay visible.
    assert describe_dbcan_id(0x040) == "primary-master 1.00 (broadcast)"
    assert describe_dbcan_id(0x000) == "primary-master 0.00 (broadcast)"
    assert describe_dbcan_id(0x442) == "device-process-data 1.02"


@pytest.mark.parametrize("bad", [(4, 0, 1), (0, 8, 1), (0, 0, 64)])
def test_dbcan_id_rejects_out_of_range(bad):
    with pytest.raises(ValueError):
        dbcan_id(*bad)


# --- Length=0 regression -----------------------------------------------------
# The same vectors as the C suite, per the project rule that both sides are
# checked against one set. Found by firmware/hostsim/fuzz: in C, Length=0 made
# len underflow to 255, reading past the decode buffer and then overwriting the
# frame's own length field with a byte the peer chose. Python was safe by
# accident; both reject it deliberately now.

def test_length_zero_is_rejected():
    decoder = rmbcp.Decoder()
    assert decoder.feed(bytes([rmbcp.SOF, 0x00, 0x40, rmbcp.EOF])) == []
    assert decoder.bad_frames == 1


def test_length_zero_with_matching_checksum_is_rejected():
    """The shape that reached the memcpy in C."""
    crafted = bytearray(260)
    crafted[0] = rmbcp.SOF
    crafted[1] = 0x00
    crafted[2] = 0x40
    crafted[3 + 254] = 0x7E  # the byte that landed on the length field
    crafted[3 + 255] = rmbcp.checksum(rmbcp.SOF, 0x00, 0x40, bytes(crafted[3:258]))
    crafted[4 + 255] = rmbcp.EOF
    assert rmbcp.Decoder().feed(bytes(crafted)) == []


def test_decoder_resynchronises_after_length_zero():
    decoder = rmbcp.Decoder()
    good = rmbcp.encode_can(0x222, b"\xaa\xbb")
    frames = decoder.feed(bytes([rmbcp.SOF, 0x00, 0x40, rmbcp.EOF]) + good)
    assert len(frames) == 1
    assert frames[0].as_can()[0] == 0x222


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
