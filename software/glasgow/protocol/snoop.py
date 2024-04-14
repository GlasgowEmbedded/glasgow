# Ref: https://www.rfc-editor.org/rfc/rfc1761
# Accession: G00088

import enum
import struct
import typing


__all__ = ["SnoopDatalinkType", "SnoopPacket", "SnoopWriter", "SnoopReader"]


SNOOP_IDENT = b"snoop\x00\x00\x00"
SNOOP_VERSION = 2


class SnoopError(Exception):
    pass


class SnoopDatalinkType(enum.IntEnum):
    #: IEEE Ethernet
    IEEE_802_3 = 0
    #: IEEE Token Bus
    IEEE_802_4 = 1
    #: IEEE Metro Net
    IEEE_802_5 = 2
    #: Ethernet II
    Ethernet   = 4
    #: High-Level Data Link Control; ISO/IEC 13239
    HDLC       = 5
    #: Synchronous Data Link Control; Character Synchronous;
    SDLC       = 6
    #: IBM Channel-to-Channel
    FICON_CTC  = 7
    #: Fiber Distributed Data Interface
    FDDI       = 8
    Other      = 9


class SnoopPacket:
    def __init__(self, payload: bytes, *, orig_length: 'None | int' = None, timestamp_ns: int = 0):
        assert orig_length is None or orig_length >= len(payload)
        self._length: int = len(payload)
        self._orig_length: int = len(payload) if orig_length is None else orig_length
        self._payload: bytes = bytes(payload) + b"\0" * (-len(payload) % 4)
        self._timestamp_ns: int = timestamp_ns

    @property
    def length(self):
        return self._length

    @property
    def orig_length(self):
        return self._orig_length

    @property
    def payload(self):
        return self._payload[:self._length]

    @property
    def timestamp_ns(self):
        return self._timestamp_ns

    @property
    def timestamp(self):
        return self._timestamp_ns / 1_000_000_000

    def __repr__(self):
        return (
            f"SnoopPacket({self.payload!r}, orig_length={self.orig_length!r}, "
            f"timestamp_ns={self.timestamp_ns!r})"
        )


class SnoopWriter:
    def __init__(self, file: typing.BinaryIO, *, datalink_type: SnoopDatalinkType):
        assert isinstance(datalink_type, SnoopDatalinkType)
        self.file = file
        self.file.write(struct.pack(">8sLL",
            SNOOP_IDENT, # Identification Pattern
            SNOOP_VERSION, # Version Number
            datalink_type, # Datalink Type (Ethernet)
        ))

    def write(self, packet: SnoopPacket):
        self.file.write(struct.pack(">LLLLLL",
            packet._orig_length, # Original Length
            packet._length, # Included Length
            24 + len(packet._payload), # Packet Record Length
            0, # Cumulative Drops (ignored by Wireshark)
            packet._timestamp_ns // 1_000_000_000, # Timestamp Seconds
            packet._timestamp_ns // 1_000 % 1_000_000, # Timestamp Microseconds
        ) + packet._payload)


class SnoopReader:
    def __init__(self, file: typing.BinaryIO):
        self.file = file
        try:
            ident, version, datalink_type = \
                struct.unpack(">8sLL", self.file.read(struct.calcsize(">8sLL")))
        except struct.error:
            raise SnoopError("unexpected end of file")
        if ident != SNOOP_IDENT:
            raise SnoopError(f"unexpected snoop identification pattern: {ident!r}")
        if version != SNOOP_VERSION:
            raise SnoopError(f"unexpected snoop version number: {version!r}")
        self.datalink_type = SnoopDatalinkType(datalink_type)

    def read(self) -> 'SnoopPacket | None':
        try:
            orig_length, length, record_length, cumulative_drops, timestamp_s, timestamp_us = \
                struct.unpack(">LLLLLL", self.file.read(struct.calcsize(">LLLLLL")))
        except struct.error:
            return None
        payload = self.file.read(record_length - struct.calcsize(">LLLLLL"))
        timestamp_ns = timestamp_s * 1_000_000_000 + timestamp_us * 1_000
        return SnoopPacket(payload[:length], orig_length=orig_length, timestamp_ns=timestamp_ns)
