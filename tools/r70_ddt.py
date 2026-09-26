"""
R70 Device Detection (DDT) — the UDP 33333 discovery protocol.

This is the one part of the R70's behaviour that is NOT in any vendor document.
The layout below is documented from captures of R1 V3's discovery traffic and
confirmed live against R1: it discovers, lists and connects to a device that
answers this way. See docs/PROTOCOL.md §4.

Packet = 4-byte header + N fixed 64-byte records:

    off 0   interface index   R1 numbers its local interfaces 0,1,2,… per scan
    off 1   0
    off 2   opcode            0x80 = request (R1 -> broadcast), 0x00 = answer
    off 3   record count
    off 4   record[0], record[1], … each exactly 64 bytes

Record:

    off  0..3   IPv4 address, big-endian
    off  4      service   (1 or 2 — anything else and R1 drops the record)
    off  5      protocol  (never 2 or 0xFF; and service==1 with protocol==0 is dropped)
    off  6..7   port, big-endian
    off  8..13  MAC address
    off 14..17  device-type tag, ASCII "R70 " — R1 sends it in the request and
                ignores it in the answer, so it selects which device type replies
    off 36..    host name, NUL-terminated UTF-8 (28 bytes available)

Two findings worth stating plainly, because both remove risk from the project:

* R1 accepts an answer on exactly ONE condition: byte 2 (the opcode) is 0.
  R1 receives its own broadcast (opcode 0x80) and ignores it that way. There is
  no checksum, magic number or length check.
* R1 ignores the UDP sender address, so the device's IP is taken from INSIDE the
  record — and the MAC is not checked against any OUI. We do not need to borrow RM
  Michaelides' MAC range for real hardware.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass

HEADER_LEN = 4
RECORD_LEN = 64

OP_REQUEST = 0x80
OP_ANSWER = 0x00

TAG_R70 = b"R70 "

# Record field offsets
OFF_IP, OFF_SERVICE, OFF_PROTOCOL, OFF_PORT = 0, 4, 5, 6
OFF_MAC, OFF_TAG, OFF_HOSTNAME = 8, 14, 36

# rec[4] — R1 accepts 1 or 2; anything else is rejected outright.
SERVICE_SERVER = 1
SERVICE_CLIENT = 2

# rec[5] — 0 = none, 1 = TCP, 3 = UDP.
# Values 2 and 0xFF are rejected, as is protocol 0 combined with service 1.
PROTOCOL_NONE = 0
PROTOCOL_TCP = 1
PROTOCOL_UDP = 3


def _valid_combination(service: int, protocol: int) -> bool:
    """Reproduce R1's record filter (which records it keeps)."""
    if service not in (1, 2):
        return False
    if protocol in (2, 0xFF):
        return False
    # `(service ^ 1) | protocol == 0` -> dropped
    return ((service ^ 1) | protocol) != 0


@dataclass
class Record:
    """One advertised socket on an interface."""

    ip: str
    port: int
    mac: bytes
    hostname: str
    service: int = SERVICE_SERVER
    protocol: int = PROTOCOL_TCP
    tag: bytes = TAG_R70

    def __post_init__(self) -> None:
        if len(self.mac) != 6:
            raise ValueError("MAC must be 6 bytes")
        if len(self.hostname.encode()) > RECORD_LEN - OFF_HOSTNAME - 1:
            raise ValueError("host name too long for the record")

    def encode(self) -> bytes:
        # Validated on the way out only. R1's own request carries a template
        # record with service=0/protocol=0, which decode() must accept happily —
        # but emitting that combination would have R1 silently drop us.
        if not _valid_combination(self.service, self.protocol):
            raise ValueError(
                f"service={self.service} protocol={self.protocol} is a combination "
                "R1 discards — see docs/PROTOCOL.md §4"
            )
        rec = bytearray(RECORD_LEN)
        rec[OFF_IP:OFF_IP + 4] = socket.inet_aton(self.ip)
        rec[OFF_SERVICE] = self.service
        rec[OFF_PROTOCOL] = self.protocol
        rec[OFF_PORT:OFF_PORT + 2] = self.port.to_bytes(2, "big")
        rec[OFF_MAC:OFF_MAC + 6] = self.mac
        rec[OFF_TAG:OFF_TAG + 4] = self.tag
        name = self.hostname.encode()
        rec[OFF_HOSTNAME:OFF_HOSTNAME + len(name)] = name  # NUL already present
        return bytes(rec)

    @classmethod
    def decode(cls, rec: bytes) -> "Record":
        if len(rec) != RECORD_LEN:
            raise ValueError(f"record must be {RECORD_LEN} bytes, got {len(rec)}")
        name = rec[OFF_HOSTNAME:].split(b"\x00", 1)[0].decode("utf-8", "replace")
        return cls(
            ip=socket.inet_ntoa(rec[OFF_IP:OFF_IP + 4]),
            port=int.from_bytes(rec[OFF_PORT:OFF_PORT + 2], "big"),
            mac=rec[OFF_MAC:OFF_MAC + 6],
            hostname=name,
            service=rec[OFF_SERVICE],
            protocol=rec[OFF_PROTOCOL],
            tag=bytes(rec[OFF_TAG:OFF_TAG + 4]),
        )


@dataclass
class Packet:
    opcode: int
    records: list[Record]
    interface_index: int = 0

    def encode(self) -> bytes:
        head = bytes([self.interface_index & 0xFF, 0, self.opcode, len(self.records)])
        return head + b"".join(r.encode() for r in self.records)

    @classmethod
    def decode(cls, data: bytes) -> "Packet":
        if len(data) < HEADER_LEN:
            raise ValueError("datagram shorter than the header")
        count = data[3]
        body = data[HEADER_LEN:]
        if len(body) < count * RECORD_LEN:
            raise ValueError(
                f"header claims {count} records ({count * RECORD_LEN} bytes) "
                f"but only {len(body)} bytes follow"
            )
        return cls(
            opcode=data[2],
            interface_index=data[0],
            records=[
                Record.decode(body[i * RECORD_LEN:(i + 1) * RECORD_LEN])
                for i in range(count)
            ],
        )

    @property
    def is_request(self) -> bool:
        return self.opcode == OP_REQUEST

    @property
    def requested_tags(self) -> list[bytes]:
        return [r.tag for r in self.records]


def local_ip_towards(peer_ip: str) -> str:
    """
    Our own address on whichever interface reaches `peer_ip`.

    R1 discards the UDP sender address and reads the IP out of the record, so we
    must advertise the address on the same subnet R1 probed from — otherwise it
    would list us and then try to connect somewhere unreachable.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect((peer_ip, 9))  # discard port; UDP connect sends nothing
        return probe.getsockname()[0]
    except OSError:
        return "0.0.0.0"
    finally:
        probe.close()


def build_answer(probe: bytes, *, hostname: str, mac: bytes,
                 sockets: list[tuple[int, int, int]], peer_ip: str) -> bytes | None:
    """
    Build the answer to one of R1's identification requests.

    `sockets` is a list of (service, protocol, port) — one record per socket the
    device offers. A real R70 has four and advertises them all, which matters:
    R1 leaves the socket column read-only unless the device advertises at
    least two sockets, so a device advertising a single socket
    appears in R1's list but cannot be fully configured.

    Records must differ in at least one of (service, protocol, port) — R1
    discards any record matching an earlier one on exactly that triple.

    Returns None if the datagram is not a request for a device type we emulate —
    including one of our own answers echoed back.
    """
    packet = Packet.decode(probe)
    if not packet.is_request:
        return None
    if packet.records and TAG_R70 not in packet.requested_tags:
        return None

    seen: set[tuple[int, int, int]] = set()
    for spec in sockets:
        if spec in seen:
            raise ValueError(f"duplicate socket {spec}; R1 would discard the repeat")
        seen.add(spec)

    ip = local_ip_towards(peer_ip)
    records = [
        Record(ip=ip, port=port, mac=mac, hostname=hostname,
               service=service, protocol=protocol)
        for service, protocol, port in sockets
    ]
    return Packet(
        opcode=OP_ANSWER,
        records=records,
        interface_index=packet.interface_index,
    ).encode()
