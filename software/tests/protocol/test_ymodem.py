import types
import unittest
import asyncio
import logging
import tempfile
import pathlib

from glasgow.protocol.ymodem import *


logger = logging.getLogger(__name__)
logging.basicConfig(level=0)


class MockTransport(YModemTransport):
    def __init__(self, data: bytes):
        self.data = data
        self.ptr = 0

    def check(self):
        assert self.ptr == len(self.data)

    async def recv(self, length: int) -> bytes:
        chunk = self.data[self.ptr:self.ptr+length]
        assert len(chunk) == length
        self.ptr += length
        return chunk

    async def send(self, data: bytes):
        chunk = self.data[self.ptr:self.ptr+len(data)]
        assert chunk == data, f"{data.hex()} != {chunk.hex()} @ {self.ptr}"
        self.ptr += len(data)

    async def purge(self):
        pass


def mock_await(coro: types.CoroutineType):
    try:
        coro.send(None)
        assert False, "unexpected await"
    except StopIteration:
        pass


class YModemTestCase(unittest.TestCase):
    def setUp(self):
        self.maxDiff = 10000

    def test_packet(self):
        for packet, serialized, use_crc16 in [
            (YModemPacket.for_data(number=0, data=b"foo.bin".ljust(128, b"\0")),
             b"\x01\x00\xff" + b"foo.bin".ljust(128, b"\0") + b"\xab", False),
            (YModemPacket.for_data(number=3, data=bytes(range(0x80)) * 8),
             b"\x02\x03\xfc" + bytes(range(0x80)) * 8 + b"\x00", False),
            (YModemPacket.for_data(number=0, data=b"foo.bin".ljust(128, b"\0")),
             b"\x01\x00\xff" + b"foo.bin".ljust(128, b"\0") + b"\x98\x68", True),
            (YModemPacket.for_data(number=3, data=bytes(range(0x80)) * 8),
             b"\x02\x03\xfc" + bytes(range(0x80)) * 8 + b"\x69\xaa", True),
            (YModemHeader.EOT.packet(), b"\x04", None),
            (YModemHeader.ACK.packet(), b"\x06", None),
            (YModemHeader.NAK.packet(), b"\x15", None),
            (YModemHeader.CAN.packet(), b"\x18", None),
            (YModemHeader.C.packet(), b"C", None),
            (YModemHeader.K.packet(), b"K", None),
        ]:
            variant = YModemVariant.XMODEM_1K if use_crc16 else YModemVariant.XMODEM

            with self.subTest(f"send {serialized!r}"):
                transport = MockTransport(serialized)
                mock_await(packet.send(transport, variant=variant))
                transport.check()

            with self.subTest(f"recv {serialized!r}"):
                transport = MockTransport(serialized)
                mock_await(packet.recv(transport, variant=variant))
                transport.check()

    def test_metadata(self):
        for metadata, serialized in [
            (YModemFileInfo(pathname=b"foo.bin"),
             b"foo.bin\x00\x00"),
            (YModemFileInfo(pathname=b"foo.bin", length=123),
             b"foo.bin\x00123\x00"),
            (YModemFileInfo(pathname=b"foo.bin", length=123, modified=1790506550),
             b"foo.bin\x00123 15256173066\x00"),
            (YModemFileInfo(pathname=b"foo.bin", length=123, modified=1790506550, mode=0o755),
             b"foo.bin\x00123 15256173066 100755\x00"),
        ]:
            with self.subTest(f"emit {serialized!r}"):
                self.assertEqual(metadata.emit(), serialized)

            with self.subTest(f"parse {serialized!r}"):
                self.assertEqual(YModemFileInfo.parse(serialized), metadata)

    def test_metadata_quirk_EMW3080(self):
        chunk = b"BootLoaderImage.bin\x0077824\xee\x03\x10t\xe9\x03\x10\x00\x00\x00"
        self.assertEqual(
            YModemFileInfo.parse(chunk),
            YModemFileInfo(pathname=b"BootLoaderImage.bin", length=77824),
        )

    def test_recv_single_128(self):
        transport = MockTransport(b"".join([
            b"\x4B",
                b"\x01\x01\xfeDATA1" + b"\0"*123 + b"\x5D\x5D",
            b"\x06",
                b"\x01\x02\xfdDATA2" + b"\0"*123 + b"\xAA\x0C",
            b"\x06",
                b"\x04",
            b"\x06"
        ]))
        protocol = YModemProtocol(transport, logger=logger)
        file_data = asyncio.run(protocol.recv_single())
        self.assertEqual(file_data, b"DATA1" + b"\0"*123 + b"DATA2" + b"\0"*123)

    def test_recv_single_1024(self):
        transport = MockTransport(b"".join([
            b"\x4B",
                b"\x02\x01\xfeCONTENTS" + b"\0"*1016 + b"\x4B\xB3",
            b"\x06",
                b"\x04",
            b"\x06"
        ]))
        protocol = YModemProtocol(transport, logger=logger)
        file_data = asyncio.run(protocol.recv_single())
        self.assertEqual(file_data, b"CONTENTS" + b"\0"*1016)

    def test_recv_single_retransmit(self):
        transport = MockTransport(b"".join([
            b"\x4B",
                b"\x01\x01\xfeDATA1" + b"\0"*123 + b"\x5D\x5D",
            b"\x06",
                b"\x01\x02\xfdDATA2" + b"\0"*123 + b"\xAA\x0D",
            b"\x15",
                b"\x01\x02\xfdDATA2" + b"\0"*123 + b"\xAA\x0C",
            b"\x06",
                b"\x04",
            b"\x06"
        ]))
        protocol = YModemProtocol(transport, logger=logger)
        file_data = asyncio.run(protocol.recv_single())
        self.assertEqual(file_data, b"DATA1" + b"\0"*123 + b"DATA2" + b"\0"*123)

    def test_recv_batch(self):
        transport = MockTransport(b"".join([
            b"\x43",
                b"\x01\x00\xff" + b"foo.bin".ljust(128, b"\0") + b"\x98\x68",
            b"\x06",
            b"\x4B",
                b"\x01\x01\xfeDATA1" + b"\0"*123 + b"\x5D\x5D",
            b"\x06",
                b"\x01\x02\xfdDATA2" + b"\0"*123 + b"\xAA\x0C",
            b"\x06",
                b"\x04",
            b"\x06"

            b"\x43",
                b"\x01\x00\xff" + b"bar.bin\x0010".ljust(128, b"\0") + b"\x18\xD0",
            b"\x06",
            b"\x4B",
                b"\x02\x01\xfeCONTENTS" + b"\0"*1016 + b"\x4B\xB3",
            b"\x06",
                b"\x04",
            b"\x06"

            b"\x43",
                b"\x01\x00\xff" + b"\0"*128 + b"\x00\x00",
            b"\x06",
        ]))
        protocol = YModemProtocol(transport, logger=logger)
        batch_data = asyncio.run(protocol.recv_batch())
        self.assertEqual(batch_data, [
            YModemFile(
                info=YModemFileInfo(pathname=b"foo.bin"),
                data=bytearray(b"DATA1" + b"\0"*123 + b"DATA2" + b"\0"*123),
            ),
            YModemFile(
                info=YModemFileInfo(pathname=b"bar.bin", length=10),
                data=bytearray(b"CONTENTS\0\0"),
            ),
        ])

    def test_send_single_128(self):
        transport = MockTransport(b"".join([
            b"\x43",
                b"\x01\x01\xfeDATA1" + b"\0"*123 + b"\x5D\x5D",
            b"\x06",
                b"\x01\x02\xfdDATA2" + b"\x1A"*123 + b"\x7B\xDA",
            b"\x06",
                b"\x04",
            b"\x06"
        ]))
        protocol = YModemProtocol(transport, logger=logger)
        asyncio.run(protocol.send_single(b"DATA1" + b"\0"*123 + b"DATA2"))

    def test_send_single_1024(self):
        transport = MockTransport(b"".join([
            b"\x4B",
                b"\x02\x01\xfeCONTENTS" + b"\0"*1016 + b"\x4B\xB3",
            b"\x06",
                b"\x04",
            b"\x06"
        ]))
        protocol = YModemProtocol(transport, logger=logger)
        asyncio.run(protocol.send_single(b"CONTENTS" + b"\0"*1016))

    def test_send_batch(self):
        transport = MockTransport(b"".join([
            b"\x4B",
                b"\x01\x00\xff" + b"foo.bin\x00256".ljust(128, b"\0") + b"\xF6\x4C",
            b"\x06",
            b"\x43",
                b"\x01\x01\xfeDATA1" + b"\0"*123 + b"\x5D\x5D",
            b"\x06",
                b"\x01\x02\xfdDATA2" + b"\0"*123 + b"\xAA\x0C",
            b"\x06",
                b"\x04",
            b"\x06"

            b"\x4B",
                b"\x01\x00\xff" + b"bar.bin\x001033".ljust(128, b"\0") + b"\x65\x15",
            b"\x06",
            b"\x4B",
                b"\x02\x01\xfeCONTENTS" + b"\0"*1016 + b"\x4B\xB3",
            b"\x06",
                b"\x01\x02\xfd\0\0\0\0\0\0\0\0X" + b"\x1A"*119 + b"\xF5\x78",
            b"\x06",
                b"\x04",
            b"\x06"

            b"\x4B",
                b"\x01\x00\xff" + b"\0"*128 + b"\x00\x00",
            b"\x06",
        ]))
        protocol = YModemProtocol(transport, logger=logger)
        asyncio.run(protocol.send_batch([
            YModemFile(
                info=YModemFileInfo(pathname=b"foo.bin"),
                data=bytearray(b"DATA1" + b"\0"*123 + b"DATA2" + b"\0"*123),
            ),
            YModemFile(
                info=YModemFileInfo(pathname=b"bar.bin"),
                data=bytearray(b"CONTENTS" + b"\0"*1024 + b"X"),
            ),
        ]))

    def test_send_single_quirk_xm_com(self):
        # XM.COM will send `CK` sequences to negotiate
        transport = MockTransport(b"".join([
            b"\x43",
                b"\x01\x01\xfeDATA1" + b"\0"*123 + b"\x5D\x5D",
            b"\x4B",
            b"\x06",
                b"\x01\x02\xfdDATA2" + b"\x1A"*123 + b"\x7B\xDA",
            b"\x06",
                b"\x04",
            b"\x06"
        ]))
        protocol = YModemProtocol(transport, logger=logger)
        asyncio.run(protocol.send_single(b"DATA1" + b"\0"*123 + b"DATA2"))

    def test_file_from_path(self):
        tmpfile = tempfile.NamedTemporaryFile("wb", prefix="meow_")
        tmpfile.write(b"meowmeow")
        tmpfile.flush()

        ymodem_file = YModemFile.from_path(tmpfile.name)
        self.assertEqual(ymodem_file.info.pathname, pathlib.Path(tmpfile.name).name.encode())
        self.assertEqual(ymodem_file.info.length, 8)
        self.assertEqual(ymodem_file.data, b"meowmeow")
