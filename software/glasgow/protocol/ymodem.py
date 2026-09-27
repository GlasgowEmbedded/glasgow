# Ref: XMODEM File Transfer Protocol http://textfiles.com/programming/xmodem.txt
# Accession: G00135
# Ref: XMODEM/YMODEM PROTOCOL REFERENCE http://textfiles.com/programming/ymodem.txt
# Accession: G00136

"""XMODEM/YMODEM protocol implementation.

The XMODEM and YMODEM families of protocols are closely related. This module implements both;
the exact protocol used is determined by entry point and capability negotiation.
"""

from __future__ import annotations
from typing import Self
from abc import ABCMeta, abstractmethod
import enum
from enum_tools.documentation import document_enum
import struct
import dataclasses
import asyncio
import pathlib
import os
import re

from amaranth.lib.crc.catalog import CRC16_XMODEM

from glasgow.support import logging
from glasgow.support.progress import Progress


__all__ = [
    "YModemError", "YModemTransport", "YModemHeader", "YModemVariant", "YModemPacket",
    "YModemFileInfo", "YModemFile", "YModemProtocol",
]


logger = logging.getLogger(__name__)


class YModemError(Exception):
    """XMODEM/YMODEM communication error."""


class YModemTransport(metaclass=ABCMeta):
    """Abstract XMODEM/YMODEM transport."""

    @abstractmethod
    async def recv(self, length: int) -> bytes:
        """Receive :py:`length` bytes.

        Can be safely cancelled.
        """

    @abstractmethod
    async def send(self, data: bytes):
        """Send :py:`data` and flush."""

    @abstractmethod
    async def purge(self):
        """Clear any data in the receive buffer."""


@document_enum
class YModemHeader(bytes, enum.ReprEnum):
    """XMODEM/YMODEM packet header."""

    SOH = b"\x01"
    """128 bytes of data."""

    STX = b"\x02"
    """1024 bytes of data."""

    EOT = b"\x04"
    """End of transfer."""

    ACK = b"\x06"
    """Acknowledgement."""

    NAK = b"\x15"
    """Non-acknowledgement."""

    CAN = b"\x18"
    """Cancel."""

    C   = b"\x43"
    """Use XMODEM-CRC."""

    K   = b"\x4B"
    """Use XMODEM-1K (implies XMODEM-CRC)."""

    def packet(self) -> YModemPacket:
        """Create an XMODEM/YMODEM control packet."""
        return YModemPacket(self)

    def __repr__(self):
        return f"<{self.__class__.__name__}.{self.name}: 0x{self.value.hex()}>"


@document_enum
class YModemVariant(enum.Enum):
    """XMODEM/YMODEM protocol variant."""

    XMODEM     = "XMODEM"
    XMODEM_CRC = "XMODEM-CRC"
    XMODEM_1K  = "XMODEM-1K"

    def __repr__(self):
        return f"{self.__class__.__name__}.{self.name}"

    @property
    def has_crc16(self):
        """Whether to use CRC-16 for data packets.

        True for :py:enum:mem:`XMODEM_CRC` and :py:enum:mem:`XMODEM_1K`.
        """
        return self in (self.XMODEM_CRC, self.XMODEM_1K)

    @property
    def has_1k(self):
        """Whether to use 1024-byte data packets.

        True for :py:enum:mem:`XMODEM_1K`.
        """
        return self == self.XMODEM_1K


@dataclasses.dataclass(frozen=True)
class YModemPacket:
    """Abstract XMODEM/YMODEM packet.

    Represents the contents of a control or data packet.
    """

    control: YModemHeader
    """Header byte."""

    number: int | None = None
    """Packet number, for data packets."""

    data: bytes | None = None
    """Packet payload, for data packets."""

    @classmethod
    def for_data(cls, *, number: int, data: bytes) -> YModemPacket:
        """Create an XMODEM/YMODEM data packet.

        Raises
        ------
        ValueError
            If :py:`len(data)` is neither 128 nor 1024.
        """
        if len(data) == 128:
            return YModemPacket(YModemHeader.SOH, number, data)
        elif len(data) == 1024:
            return YModemPacket(YModemHeader.STX, number, data)
        else:
            assert False, f"invalid length {len(data)}"

    def __post_init__(self):
        match self.control:
            case YModemHeader.SOH:
                assert self.number is not None and self.data is not None
                assert self.number in range(0x100)
                assert len(self.data) == 128

            case YModemHeader.STX:
                assert self.number is not None and self.data is not None
                assert self.number in range(0x100)
                assert len(self.data) == 1024

            case (YModemHeader.ACK | YModemHeader.NAK | YModemHeader.EOT | YModemHeader.CAN |
                  YModemHeader.C | YModemHeader.K):
                assert self.number is None and self.data is None

            case _:
                assert False

    @staticmethod
    def _data_format(control: YModemHeader, *, variant: YModemVariant) -> str:
        match control, variant.has_crc16:
            case YModemHeader.SOH, False: return ">BB128sB"
            case YModemHeader.SOH, True:  return ">BB128sH"
            case YModemHeader.STX, False: return ">BB1024sB"
            case YModemHeader.STX, True:  return ">BB1024sH"
            case _: assert False

    @classmethod
    async def recv(cls, transport: YModemTransport, *, variant: YModemVariant) -> Self | None:
        """Receive a packet from :py:`transport`.

        Reads and returns a single XMODEM/YMODEM packet from :py:`transport`. If the first byte
        read from :py:`transport` is not a valid :class:`YModemControl` header, returns :py:`None`.

        Raises
        ------
        YModemError
            If a checksum or CRC-16 was incorrect.
        Exception
            Any error raised by :py:`transport.recv()`.
        """
        header = await transport.recv(1)
        if header not in YModemHeader:
            return None

        control = YModemHeader(header)
        match control:
            case YModemHeader.SOH | YModemHeader.STX:
                packet_format = cls._data_format(control, variant=variant)
                packet_data = await transport.recv(struct.calcsize(packet_format))
                serial, serial_cksum, data, data_cksum = \
                    struct.unpack(packet_format, packet_data)

                if serial + serial_cksum != 0xff:
                    raise YModemError("serial checksum incorrect")
                if variant.has_crc16:
                    if CRC16_XMODEM(data_width=8).compute(data) != data_cksum:
                        raise YModemError("data crc16 incorrect")
                else:
                    if sum(data) & 0xff != data_cksum:
                        raise YModemError("data checksum incorrect")

                return cls(control, serial, data)

            case (YModemHeader.ACK | YModemHeader.NAK | YModemHeader.EOT | YModemHeader.CAN |
                  YModemHeader.C | YModemHeader.K):
                return cls(control)

            case _:
                return None

    async def send(self, transport: YModemTransport, *, variant: YModemVariant):
        """Send a packet to :py:`transport`.

        Formats and writes a single XMODEM/YMODEM packet to :py:`transport`.

        Raises
        ------
        Exception
            Any error raised by :py:`transport.send()`.
        """
        packet_data = self.control.value
        match self.control:
            case YModemHeader.SOH | YModemHeader.STX:
                serial_cksum = 0xff - self.number
                if variant.has_crc16:
                    data_cksum = CRC16_XMODEM(data_width=8).compute(self.data)
                else:
                    data_cksum = sum(self.data) & 0xff

                packet_format = self._data_format(self.control, variant=variant)
                packet_data += struct.pack(packet_format,
                    self.number, serial_cksum, self.data, data_cksum)

        await transport.send(packet_data)

    def __str__(self):
        match self.control:
            case YModemHeader.SOH | YModemHeader.STX:
                return f"{self.control.name},{self.number:02x},{self.data.hex()}"
            case _:
                return f"{self.control.name}"


@dataclasses.dataclass(kw_only=True)
class YModemFileInfo:
    """YMODEM file metadata, transmitted in block zero."""

    pathname: bytes
    """File pathname.

    The exact format of the pathname is not specified, but it "must be acceptable to both
    the sender and receiving operating systems". Drive letters and backslashes may not appear
    in the pathname in any case. It is recommended but not required to translate the pathname
    to lower case.
    """

    length: int | None = None
    """File length.

    If present, this field should be used to discard any padding in the final block of the transfer.
    """

    modified: int | None = None
    """Modification date.

    If present, this field indicates modification date as number of seconds from 1970-01-01 GMT.
    """

    mode: int | None = None
    """File mode.

    If present, this field indicates that the file has been sent from a Unix system and has
    the specified mode.
    """

    @classmethod
    def parse(cls, data: bytes):
        """Parse YMODEM metadata.

        The metadata parser tolerates significant deviations from the specified format in order
        to try and maximize compatibility.

        Raises
        ------
        YModemError
            If the metadata has invalid format.
        """
        # The MICO bootloader in EMW3080 transmits block 0 as follows:
        #   b'BootLoaderImage.bin\x0077824\xee\x03\x10t\xe9\x03\x10\x00\x00\x00 ...
        # We have to deal with the trailing garbage.
        if m := re.match(
            rb"^([^\0]+)\0(?:([0-9]+)(?: ([0-7]+)(?: ([0-7]+)?)?)?)?", data
        ):
            return cls(
                pathname=m[1],
                length=int(m[2], 10) if m[2] else None,
                modified=int(m[3], 8) if m[3] else None,
                mode=int(m[4], 8) & 0x7fff if m[4] else None,
            )
        else:
            raise YModemError(f"malformed metadata: {data!r}")

    def emit(self) -> bytes:
        """Serialize YMODEM metadata.

        .. note::

            For each of :py:`self.modified` and :py:`self.mode`, the preceding field must be
            defined as well for this field to be serialized.
        """
        fields = []
        if self.length is not None:
            fields.append(f"{self.length:d}".encode())
            if self.modified is not None:
                fields.append(f"{self.modified:o}".encode())
                if self.mode is not None:
                    fields.append(f"{self.mode | 0x8000:o}".encode())

        return self.pathname + b"\0" + b" ".join(fields) + b"\0"


@dataclasses.dataclass(kw_only=True)
class YModemFile:
    """YMODEM file representation."""

    info: YModemFileInfo
    """YMODEM file metadata."""

    data: bytes
    """File data."""

    @classmethod
    def from_path(cls, path: str | pathlib.PurePath) -> Self:
        """Read file from filesystem :py:`path`.

        .. note::

            The :py:`meta.pathname` field receives the file name only (without a path and without
            case conversion). Callers should update this field if different behavior is desired.
        """
        path = pathlib.Path(path)
        with path.open("rb") as f:
            stat = os.fstat(f.fileno())
            data = f.read()
        return YModemFile(
            info=YModemFileInfo(
                pathname=path.name.encode(),
                length=len(data),
                modified=int(stat.st_mtime),
            ),
            data=data,
        )


class YModemProtocol:
    """XMODEM/YMODEM protocol handler.

    Handles packet sequencing, retransmission, and data storage.
    """

    def __init__(self, transport: YModemTransport, *, logger: logging.Logger = logger,
                 progress: Progress | None = None):
        self._transport = transport
        self._logger    = logger
        self._progress  = progress

        self._retrans_count = 10
        self._retrans_time  = 1.0 # seconds

    async def _send(self, out_packet: YModemPacket, *, variant: YModemVariant):
        self._logger.log(logging.DEBUG, "YMODEM: -> %s", out_packet)
        await out_packet.send(self._transport, variant=variant)
        if self._progress is not None and out_packet.data is not None:
            self._progress.advance(len(out_packet.data))

    async def _recv(self, *, variant: YModemVariant) -> YModemPacket:
        in_packet = await YModemPacket.recv(self._transport, variant=variant)
        if in_packet is None:
            raise YModemError("malformed header")
        if self._progress is not None and in_packet.data is not None:
            self._progress.advance(len(in_packet.data))
        self._logger.log(logging.DEBUG, "YMODEM: <- %s", in_packet)
        return in_packet

    async def _recv_retry(self, out_packet: YModemPacket, *,
                          variant: YModemVariant) -> YModemPacket:
        await self._send(out_packet, variant=variant)
        for _attempt in range(self._retrans_count):
            try:
                in_packet = await asyncio.wait_for(
                    self._recv(variant=variant),
                    timeout=self._retrans_time
                )
            except YModemError:
                self._logger.log(logging.DEBUG, "YMODEM: <- (error)")
            except TimeoutError:
                self._logger.log(logging.DEBUG, "YMODEM: <- (timeout)")
            else:
                return in_packet

            match out_packet.control:
                case YModemHeader.K | YModemHeader.C:
                    await self._send(out_packet, variant=variant)
                case _:
                    await self._send(YModemHeader.NAK.packet(), variant=variant)

        raise YModemError("retransmit attempts exceeded")

    async def recv_single(self, *, variant = YModemVariant.XMODEM_1K) -> bytearray:
        """Receive a single file using the XMODEM protocol.

        Returns the concatenation of every data block; this will include padding at the end.

        Raises
        ------
        YModemError
            If retransmit count is exceeded.
        YModemError
            If another protocol violation occurs.
        Exception
            Any error raised by :py:`transport.send()` or :py:`transport.recv()`.
        """
        match variant:
            case YModemVariant.XMODEM:
                start = YModemHeader.NAK
            case YModemVariant.XMODEM_CRC:
                start = YModemHeader.C
            case YModemVariant.XMODEM_1K:
                start = YModemHeader.K
        packet = await self._recv_retry(start.packet(), variant=variant)

        file_data = bytearray()
        next_number = 0x01
        while True:
            match packet:
                case YModemPacket(YModemHeader.EOT):
                    await self._send(YModemHeader.ACK.packet(), variant=variant)
                    return file_data

                case YModemPacket() if packet.number is not None and packet.number != next_number:
                    raise YModemError(
                        f"unexpected YMODEM packet number: {packet.number} != {next_number}")

                case YModemPacket() if packet.data is not None:
                    file_data += packet.data
                    next_number = (packet.number + 1) & 0xff
                    packet = await self._recv_retry(YModemHeader.ACK.packet(), variant=variant)

                case _:
                    raise YModemError(f"unexpected YMODEM packet: {packet.control!r}")

    async def recv_batch(self) -> list[YModemFile]:
        """Receive a batch of files using the YMODEM protocol.

        Returns a list of files received in the batch, with the file data trimmed to remove any
        padding.

        Raises
        ------
        YModemError
            If YMODEM metadata is malformed.
        YModemError
            If retransmit count is exceeded.
        YModemError
            If another protocol violation occurs.
        Exception
            Any error raised by :py:`transport.send()` or :py:`transport.recv()`.
        """
        variant = YModemVariant.XMODEM_1K # implied by YMODEM
        files = []
        while True:
            packet = await self._recv_retry(YModemHeader.C.packet(), variant=variant)
            await self._send(YModemHeader.ACK.packet(), variant=variant)
            if packet.number != 0x00:
                raise YModemError("unexpected YMODEM data block")
            if re.match(rb"^\0+$", packet.data):
                return files # all done

            meta = YModemFileInfo.parse(packet.data)
            data = await self.recv_single(variant=variant)
            if meta.length is not None:
                del data[meta.length:]

            files.append(YModemFile(info=meta, data=data))

    async def _send_start(self) -> YModemVariant:
        match await self._recv(variant=YModemVariant.XMODEM):
            case YModemPacket(YModemHeader.NAK):
                return YModemVariant.XMODEM
            case YModemPacket(YModemHeader.C):
                return YModemVariant.XMODEM_CRC
            case YModemPacket(YModemHeader.K):
                return YModemVariant.XMODEM_1K
            case YModemPacket(control):
                raise YModemError(f"unexpected YMODEM start packet: {control}")

    async def _send_ack(self, packet: YModemPacket, *, variant: YModemVariant):
        while True:
            await self._send(packet, variant=variant)
            while True:
                match await self._recv(variant=variant):
                    case YModemPacket(YModemHeader.ACK):
                        return # acknowledged
                    case YModemPacket(YModemHeader.NAK):
                        break # not acknowledged, retry
                    case YModemPacket(YModemHeader.C | YModemHeader.K):
                        continue # XM.COM uses `CK` sequences to negotiate, ignore
                    case YModemPacket(control):
                        raise YModemError(f"unexpected YMODEM acknowledge packet: {control}")

    async def send_single(self, file_data: bytearray):
        r"""Send a single file using the XMODEM protocol.

        Last block will be padded with ASCII :py:`0x1A` (SUB) characters up to a 128-byte block
        boundary.

        Raises
        ------
        YModemError
            If a protocol violation occurs.
        Exception
            Any error raised by :py:`transport.send()` or :py:`transport.recv()`.
        """
        variant = await self._send_start()

        file_data = memoryview(file_data)
        next_number = 0x01
        while True:
            if len(file_data) >= 1024 and variant.has_1k:
                packet = YModemPacket.for_data(
                    number=next_number, data=bytes(file_data[:1024]))
            elif len(file_data) >= 128:
                packet = YModemPacket.for_data(
                    number=next_number, data=bytes(file_data[:128]))
            elif len(file_data) > 0:
                packet = YModemPacket.for_data(
                    number=next_number, data=bytes(file_data).ljust(128, b"\x1A"))
            else:
                packet = YModemHeader.EOT.packet()
            await self._send_ack(packet, variant=variant)

            next_number = (next_number + 1) & 0xff
            if packet.control == YModemHeader.EOT:
                break
            else:
                file_data = file_data[len(packet.data):]

    async def send_batch(self, files: list[YModemFile]):
        r"""Send a batch of files using the YMODEM protocol.

        See remark in :meth:`send_single`.

        Raises
        ------
        YModemError
            If a protocol violation occurs.
        Exception
            Any error raised by :py:`transport.send()` or :py:`transport.recv()`.
        """
        for file_index, file in enumerate(files):
            if file.info is None:
                raise YModemError(f"file #{file_index} does not have metadata")
            info = dataclasses.replace(file.info, length=len(file.data))

            packet = YModemPacket.for_data(number=0, data=info.emit().ljust(128, b"\0"))
            variant = await self._send_start()
            await self._send_ack(packet, variant=variant)

            await self.send_single(file.data)

        # Terminate the batch.
        packet = YModemPacket.for_data(number=0, data=b"".ljust(128, b"\0"))
        variant = await self._send_start()
        await self._send_ack(packet, variant=variant)
