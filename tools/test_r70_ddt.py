"""
Tests for the R70 device-detection (UDP 33333) protocol.

`REAL_PROBE` is a byte-exact capture of R1 V3.46 scanning, so the decoder is
pinned to captured traffic. The filter tests encode R1's accept/reject
behaviour for discovery records.
"""

import pytest

import r70_ddt
from r70_ddt import OP_ANSWER, OP_REQUEST, Packet, Record, build_answer

# Captured from R1 V3 on 2026-07-22, interface index 2 (en0 / 192.0.2.129).
REAL_PROBE = bytes.fromhex(
    "02008001" + "00" * 14 + "52373020" + "00" * 46
)


def test_real_probe_is_the_expected_size():
    """4-byte header + exactly one 64-byte record."""
    assert len(REAL_PROBE) == 68
    assert len(REAL_PROBE) == r70_ddt.HEADER_LEN + r70_ddt.RECORD_LEN


def test_decode_real_probe():
    pkt = Packet.decode(REAL_PROBE)
    assert pkt.is_request
    assert pkt.opcode == OP_REQUEST
    assert pkt.interface_index == 2
    assert len(pkt.records) == 1
    assert pkt.records[0].tag == b"R70 "


def test_answer_to_real_probe():
    reply = build_answer(
        REAL_PROBE, hostname="db-70", mac=bytes.fromhex("0050c25dc0be"),
        sockets=[(1, 1, 30000)], peer_ip="127.0.0.1",
    )
    assert reply is not None
    # Same shape as the probe — this protocol is symmetric.
    assert len(reply) == 68
    # The single thing R1 checks before accepting a datagram.
    assert reply[2] == OP_ANSWER
    assert reply[3] == 1
    assert reply[0] == 2  # interface index echoed back

    rec = Packet.decode(reply).records[0]
    assert rec.port == 30000
    assert rec.mac == bytes.fromhex("0050c25dc0be")
    assert rec.hostname == "db-70"


def test_answer_carries_a_reachable_ip():
    """R1 ignores the UDP sender and connects to the IP inside the record."""
    reply = build_answer(REAL_PROBE, hostname="db-70", mac=b"\x00" * 6,
                         sockets=[(1, 1, 30000)], peer_ip="127.0.0.1")
    assert Packet.decode(reply).records[0].ip == "127.0.0.1"


def test_own_broadcast_is_not_answered():
    """An answer (opcode 0) must never trigger another answer — no storms."""
    answer = build_answer(REAL_PROBE, hostname="db-70", mac=b"\x00" * 6,
                          sockets=[(1, 1, 30000)], peer_ip="127.0.0.1")
    assert build_answer(answer, hostname="db-70", mac=b"\x00" * 6,
                        sockets=[(1, 1, 30000)], peer_ip="127.0.0.1") is None


def test_request_for_another_device_type_is_ignored():
    """R60 is a USB interface — not us."""
    probe = bytearray(REAL_PROBE)
    probe[4 + r70_ddt.OFF_TAG:4 + r70_ddt.OFF_TAG + 4] = b"R60 "
    assert build_answer(bytes(probe), hostname="db-70", mac=b"\x00" * 6,
                        sockets=[(1, 1, 30000)], peer_ip="127.0.0.1") is None


def test_record_round_trip():
    rec = Record(ip="192.0.2.70", port=30000, mac=bytes.fromhex("0050c25dc0be"),
                 hostname="db-70")
    out = Record.decode(rec.encode())
    assert (out.ip, out.port, out.mac, out.hostname) == (
        "192.0.2.70", 30000, rec.mac, "db-70")


def test_ip_and_port_are_big_endian():
    """R1 reads the address and the port big-endian."""
    raw = Record(ip="192.0.2.129", port=30000, mac=b"\x00" * 6,
                 hostname="x").encode()
    assert raw[0:4] == bytes([192, 0, 2, 129])
    assert raw[6:8] == (30000).to_bytes(2, "big")


def test_hostname_is_nul_terminated_at_offset_36():
    raw = Record(ip="1.2.3.4", port=1, mac=b"\x00" * 6, hostname="db-70").encode()
    assert raw[r70_ddt.OFF_HOSTNAME:r70_ddt.OFF_HOSTNAME + 6] == b"db-70\x00"


@pytest.mark.parametrize("service,protocol", [
    (0, 1),      # service must be 1 or 2
    (3, 1),
    (1, 2),      # protocol 2 rejected
    (1, 0xFF),   # protocol 0xFF rejected
    (1, 0),      # service 1 + protocol 0 rejected
])
def test_rejects_combinations_r1_would_discard(service, protocol):
    """Fail loudly rather than emit a record R1 silently drops."""
    with pytest.raises(ValueError):
        Record(ip="1.2.3.4", port=1, mac=b"\x00" * 6, hostname="x",
               service=service, protocol=protocol).encode()


@pytest.mark.parametrize("service,protocol", [(1, 1), (2, 1), (2, 0), (1, 3)])
def test_accepts_combinations_r1_would_keep(service, protocol):
    Record(ip="1.2.3.4", port=1, mac=b"\x00" * 6, hostname="x",
           service=service, protocol=protocol).encode()


def test_truncated_packet_is_rejected():
    with pytest.raises(ValueError):
        Packet.decode(REAL_PROBE[:40])


def test_multi_record_packet():
    """The R70 has four sockets; the header counts records."""
    recs = [Record(ip="10.0.0.1", port=30000 + i, mac=b"\x01" * 6,
                   hostname=f"db-70-{i}") for i in range(4)]
    data = Packet(opcode=OP_ANSWER, records=recs).encode()
    assert len(data) == 4 + 4 * 64
    assert [r.port for r in Packet.decode(data).records] == [30000, 30001, 30002, 30003]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_four_sockets_satisfy_the_socket_count_gate():
    """
    R1 leaves the socket column read-only unless the device advertises at least
    two sockets, so a real-looking R70 must advertise all four.
    """
    reply = build_answer(
        REAL_PROBE, hostname="db-70", mac=bytes.fromhex("0050c25dc0be"),
        sockets=[(1, 1, 30000 + i) for i in range(4)], peer_ip="127.0.0.1",
    )
    pkt = Packet.decode(reply)
    assert len(pkt.records) == 4
    assert len(reply) == 4 + 4 * 64
    assert [r.port for r in pkt.records] == [30000, 30001, 30002, 30003]


def test_duplicate_sockets_rejected():
    """R1 dedups on (service, protocol, port) — emitting a repeat is a bug."""
    with pytest.raises(ValueError):
        build_answer(REAL_PROBE, hostname="db-70", mac=b"\x00" * 6,
                     sockets=[(1, 1, 30000), (1, 1, 30000)], peer_ip="127.0.0.1")
