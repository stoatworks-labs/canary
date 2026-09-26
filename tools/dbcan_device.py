"""
A stand-in d&b amplifier on the dbCAN bus.

**Scope warning.** dbCAN's *identifier* layout is documented (see PROTOCOL.md §5)
but its *application layer* — what the up-to-8 payload bytes mean — is not, in
any vendor document we have. The R70 never needed it: it is a transparent
layer-2 bridge. So this module can address frames correctly and cannot, yet,
speak an amplifier's language.

It exists to answer one question empirically: does R1 change its behaviour when
something replies on the bus? Every request and reply is logged so the exchange
can be read off and turned into a real implementation.

The reply payload is therefore a deliberate placeholder — by default we echo the
master's payload back. Treat any R1 reaction as evidence about the protocol, not
as proof this device is correct.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rmbcp import (
    OBJ_DEVICE_PROCESS_DATA,
    OBJ_PRIMARY_MASTER,
    OBJ_SECONDARY_MASTER,
    dbcan_id,
    parse_dbcan_id,
)

MASTER_CLASSES = frozenset({OBJ_PRIMARY_MASTER, OBJ_SECONDARY_MASTER})


@dataclass
class VirtualDevice:
    """
    One virtual amplifier at a dbCAN address.

    `subnet` 0-7 and `device` 1-63, written as e.g. "1.2" — matching how d&b
    writes dbCAN-IDs (TI 312 §12).
    """

    subnet: int
    device: int
    reply_payload: bytes | None = None  # None = echo the request back
    seen: list[tuple[int, bytes]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not 0 <= self.subnet <= 7:
            raise ValueError("dbCAN subnet is 0-7")
        if not 1 <= self.device <= 63:
            raise ValueError("dbCAN device id is 1-63 (0 is the subnet broadcast)")

    @classmethod
    def parse(cls, text: str, reply_payload: bytes | None = None) -> "VirtualDevice":
        """Build from the 'subnet.device' notation d&b uses, e.g. '1.2'."""
        try:
            subnet_s, device_s = text.split(".", 1)
            return cls(subnet=int(subnet_s), device=int(device_s),
                       reply_payload=reply_payload)
        except ValueError as exc:
            raise ValueError(
                f"{text!r} is not a dbCAN address like '1.2' (subnet.device)"
            ) from exc

    @property
    def address(self) -> str:
        return f"{self.subnet}.{self.device:02d}"

    @property
    def response_id(self) -> int:
        """Frames from a device use object class 2, 'Process data from device'."""
        return dbcan_id(OBJ_DEVICE_PROCESS_DATA, self.subnet, self.device)

    def addressed_by(self, can_id: int) -> bool:
        """Is this master telegram for us — directly or via a subnet broadcast?"""
        cls_, subnet, device = parse_dbcan_id(can_id)
        if cls_ not in MASTER_CLASSES:
            return False
        if subnet != self.subnet:
            return False
        return device in (0, self.device)  # 0 = broadcast into the subnet

    def respond(self, can_id: int, payload: bytes) -> list[tuple[int, bytes]]:
        """Return the frames this device would put on the bus, as (id, payload)."""
        if not self.addressed_by(can_id):
            return []
        self.seen.append((can_id, payload))
        reply = self.reply_payload if self.reply_payload is not None else payload
        return [(self.response_id, reply)]
