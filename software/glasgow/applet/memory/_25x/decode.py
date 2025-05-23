from typing import Optional, BinaryIO
from abc import ABCMeta, abstractmethod
import enum
import struct
import logging
import argparse

from glasgow.database.jedec import jedec_mfg_name_from_bytes
from glasgow.support.logging import dump_hex
from glasgow.protocol.sfdp import SFDPParser, SFDPJEDECFlashParametersTable
from glasgow.applet import GlasgowAppletTool
from . import Memory25xAddrMode, Memory25xApplet


__all__ = ["MemoryImage", "Memory25xDecoder"]


class MemoryImage:
    def __init__(self, size=None, *, wrap=None):
        self._wrap = wrap
        if wrap is not None:
            assert size is None
            size = wrap
        elif size is None:
            size = 0
        self._data = bytearray(size)
        self._mask = bytearray(size)

    def __len__(self):
        return len(self._data)

    def __bool__(self):
        try:
            self._mask.index(b"\xff")
            return True
        except ValueError:
            return False

    @property
    def data(self) -> memoryview:
        return memoryview(self._data)

    @property
    def mask(self) -> memoryview:
        return memoryview(self._mask)

    def read(self, addr: int, size: int, *, if_present=False) -> Optional[memoryview]:
        if addr < 0:
            raise IndexError(f"start address {addr:#x} is out of bounds")
        if len(self._data) < addr + size:
            raise IndexError(f"end address {addr + size:#x} is out of bounds")
        if if_present:
            if self.mask[addr:addr + size] != b"\xff" * len(chunk):
                return None
        return self.data[addr:addr + size]

    def write(self, addr: int, chunk: bytes | bytearray | memoryview):
        if self._wrap is None:
            extra_len = addr + len(chunk) - len(self.data)
            if extra_len > 0:
                self._data.extend(bytearray(extra_len))
                self._mask.extend(bytearray(extra_len))
            self._data[addr:addr + len(chunk)] = chunk
            self._mask[addr:addr + len(chunk)] = b"\xff" * len(chunk)
        else:
            # This is very slow, but currenly is only used for very small images.
            for offset, byte in enumerate(chunk):
                byte_addr = (addr + offset) % self._wrap
                self._data[byte_addr] = byte
                self._mask[byte_addr] = 0xff

    def save(self, data_file: Optional[BinaryIO], mask_file: Optional[BinaryIO] = None):
        if data_file is not None:
            data_file.write(self._data)
        if mask_file is not None:
            mask_file.write(self._mask)


class Memory25xTraceTypeError(Exception):
    pass


class Memory25xAbstractTrace(metaclass=ABCMeta):
    @abstractmethod
    def read_copi(self, count: Optional[int] = None) -> memoryview:
        """Reads ``count`` bytes (or until the end of trace) by sampling COPI line."""

    @abstractmethod
    def read_cipo(self, count: Optional[int] = None) -> memoryview:
        """Reads ``count`` bytes (or until the end of trace) by sampling CIPO line."""

    @abstractmethod
    def read_dual(self, count: Optional[int] = None) -> memoryview:
        """Reads ``count`` bytes (or until the end of trace) by sampling IO0/IO1
        (COPI/CIPO) lines."""

    @abstractmethod
    def read_quad(self, count: Optional[int] = None) -> memoryview:
        """Reads ``count`` bytes (or until the end of trace) by sampling IO0/IO1/IO2/IO3
        (COPI/CIPO/WP#/HOLD#) lines."""


class Memory25xSPITrace(Memory25xAbstractTrace):
    def __init__(self, copi: bytes, cipo: bytes):
        self._at   = 0
        self._copi = memoryview(copi)
        self._cipo = memoryview(cipo)

    def read_copi(self, count: Optional[int] = None) -> memoryview:
        if count is None:
            count = len(self._copi) - self._at
        if self._at + count > len(self._copi):
            raise IndexError("read past end of trace")
        data = self._copi[self._at:self._at + count]
        self._at += count
        return data

    def read_cipo(self, count: Optional[int] = None) -> memoryview:
        if count is None:
            count = len(self._cipo) - self._at
        if self._at + count > len(self._cipo):
            raise IndexError("read past end of trace")
        data = self._cipo[self._at:self._at + count]
        self._at += count
        return data

    def read_dual(self, count: Optional[int] = None) -> memoryview:
        raise Memory25xTraceTypeError("dual I/O read requires a QSPI trace")

    def read_quad(self, count: Optional[int] = None) -> memoryview:
        raise Memory25xTraceTypeError("quad I/O read requires a QSPI trace")


class Memory25xQSPITrace(Memory25xAbstractTrace):
    def __init__(self, data: bytes):
        self._at   = 0
        self._data = memoryview(data)

    def _get(self, count: int):
        data = self._data[self._at:self._at + count]
        self._at += count
        return data

    def read_copi(self, count: Optional[int] = None) -> memoryview:
        if count is None:
            count = (len(self._data) - self._at) // 4
        if self._at + 4 * count > len(self._data):
            raise IndexError("read past end of trace")
        def get_copi():
            byte = 0
            for code in self._get(4):
                byte = (byte << 1) | (code & 0x10) >> 4
                byte = (byte << 1) | (code & 0x01)
            return byte
        return memoryview(bytes(get_copi() for _ in range(count)))

    def read_cipo(self, count: Optional[int] = None) -> memoryview:
        if count is None:
            count = (len(self._data) - self._at) // 4
        if self._at + 4 * count > len(self._data):
            raise IndexError("read past end of trace")
        def get_cipo():
            byte = 0
            for code in self._get(4):
                byte = (byte << 1) | (code & 0x20) >> 5
                byte = (byte << 1) | (code & 0x02) >> 1
            return byte
        return memoryview(bytes(get_cipo() for _ in range(count)))

    def read_dual(self, count: Optional[int] = None) -> memoryview:
        if count is None:
            count = (len(self._data) - self._at) // 2
        if self._at + 2 * count > len(self._data):
            raise IndexError("read past end of trace")
        def get_dual():
            byte = 0
            for code in self._get(2):
                byte = (byte << 2) | (code & 0x30) >> 4
                byte = (byte << 2) | (code & 0x03)
            return byte
        return memoryview(bytes(get_dual() for _ in range(count)))

    def read_quad(self, count: Optional[int] = None) -> memoryview:
        if count is None:
            count = len(self._data) - self._at
        return self._get(count)


class MemoryImageSFDPParser(SFDPParser):
    async def __init__(self, image):
        self._image = image
        await super().__init__()

    async def read(self, offset, length):
        return self._image.read(offset, length)


class Memory25xDecoder:
    def __init__(self, logger: Optional[logging.Logger] = None):
        self._logger   = logger

        self._jedec_id = None
        self._data     = MemoryImage()
        self._sfdp     = MemoryImage(256)
        self._uid      = MemoryImage(wrap=16)
        self._unknown  = set()

        self._index    = 0
        self._write    = False
        self._mode     = Memory25xAddrMode.ThreeByte

    def _log(self, message, *args, level=logging.DEBUG):
        if self._logger:
            self._logger.log(level, f"25x decode: [{self._index}] " + message, *args)

    @property
    def jedec_id(self) -> Optional[tuple[int, int]]:
        return self._jedec_id

    @property
    def data(self) -> MemoryImage:
        return self._data

    @property
    def sfdp(self) -> MemoryImage:
        return self._sfdp

    @property
    def uid(self) -> MemoryImage:
        return self._uid

    @property
    def unknown(self) -> set[int]:
        return self._unknown

    def _decode_addr(self, trace, mode, *, x=1) -> int:
        match mode:
            case Memory25xAddrMode.ThreeByte:
                match x:
                    case 1: data = trace.read_copi(3)
                    case 2: data = trace.read_dual(3)
                    case 4: data = trace.read_quad(3)
                addr = data[0] << 16 | data[1] << 8  | data[2] << 0
                self._log(f"  {addr=:06x}")
            case Memory25xAddrMode.FourByte:
                match x:
                    case 1: data = trace.read_copi(4)
                    case 2: data = trace.read_dual(4)
                    case 4: data = trace.read_quad(4)
                addr = data[0] << 24 | data[1] << 16 | data[2] << 8 | data[3] << 0
                self._log(f"  {addr=:08x}")
        return addr

    def decode_trace(self, trace):
        try:
            cmd = None
            cmd = trace.read_copi(1)[0] # this can raise
            match cmd:
                case 0x03:
                    self._log(f"{cmd=:02X} (Read Data)")
                    addr = self._decode_addr(trace, self._mode)
                    data = trace.read_cipo()
                    self._log("  data=%s", dump_hex(data))
                    self._data.write(addr, data)

                case 0x04:
                    self._log(f"{cmd=:02X} (Write Disable)")
                    self._write = False

                case 0x05:
                    self._log(f"{cmd=:02X} (Read Status Register)")
                    # We don't do anything with the value; this could be used to verify whether
                    # preceding writes have completed or not.

                case 0x06:
                    self._log(f"{cmd=:02X} (Write Enable)")
                    self._write = True

                case 0x0B:
                    self._log(f"{cmd=:02X} (Fast Read)")
                    addr = self._decode_addr(trace, self._mode)
                    _    = trace.read_cipo(1)
                    data = trace.read_cipo()
                    self._log("  data=%s", dump_hex(data))
                    self._data.write(addr, data)

                case 0x4B:
                    self._log(f"{cmd=:02X} (Read Unique ID)")
                    addr = self._decode_addr(trace, Memory25xAddrMode.ThreeByte)
                    _    = trace.read_cipo(1)
                    data = trace.read_cipo()
                    self._log("  data=%s", dump_hex(data))
                    self._uid.write(addr, data)

                case 0x5A:
                    self._log(f"{cmd=:02X} (Read SFDP)")
                    addr = self._decode_addr(trace, Memory25xAddrMode.ThreeByte)
                    _    = trace.read_cipo(1)
                    data = trace.read_cipo()
                    self._log("  data=%s", dump_hex(data))
                    self._sfdp.write(addr, data)

                case 0x9F:
                    self._log(f"{cmd=:02X} (Read JEDEC ID)")
                    mfg_id, device_id = struct.unpack(">BH", trace.read_cipo(3))
                    self._jedec_id = (mfg_id, device_id)

                case 0xB7:
                    self._log(f"{cmd=:02X} (Enter 4-Byte Address Mode)")
                    self._mode = Memory25xAddrMode.FourByte

                case 0xE9:
                    self._log(f"{cmd=:02X} (Exit 4-Byte Address Mode)")
                    self._mode = Memory25xAddrMode.ThreeByte

                case 0x3B:
                    self._log(f"{cmd=:02X} (Dual Output Fast Read)")
                    addr = self._decode_addr(trace, self._mode, x=1)
                    _    = trace.read_copi(2)
                    data = trace.read_dual()
                    assert mode == 0, f"mode bits ({mode:08b}) not implemented"
                    self._log("  data=%s", dump_hex(data))
                    self._data.write(addr, data)

                case 0x6B:
                    self._log(f"{cmd=:02X} (Quad Output Fast Read)")
                    addr = self._decode_addr(trace, self._mode, x=1)
                    _    = trace.read_copi(2)
                    data = trace.read_quad()
                    assert mode == 0, f"mode bits ({mode:08b}) not implemented"
                    self._log("  data=%s", dump_hex(data))
                    self._data.write(addr, data)

                case 0xBB:
                    self._log(f"{cmd=:02X} (Dual I/O Fast Read)")
                    addr = self._decode_addr(trace, self._mode, x=2)
                    mode = trace.read_dual(1)[0]
                    _    = trace.read_dual(2)
                    data = trace.read_dual()
                    assert mode == 0, f"mode bits ({mode:08b}) not implemented"
                    self._log("  data=%s", dump_hex(data))
                    self._data.write(addr, data)

                case 0xEB:
                    self._log(f"{cmd=:02X} (Quad I/O Fast Read)")
                    addr = self._decode_addr(trace, self._mode, x=4)
                    mode = trace.read_quad(1)[0]
                    _    = trace.read_quad(2)
                    data = trace.read_quad()
                    assert mode == 0, f"mode bits ({mode:08b}) not implemented"
                    self._log("  data=%s", dump_hex(data))
                    self._data.write(addr, data)

                case _:
                    self._log(f"{cmd=:02X} (unknown)", level=logging.WARNING)
                    self._unknown.add(cmd)

        except IndexError:
            if cmd is None:
                self._log("(truncated)", level=logging.WARN)
            else:
                self._log(f"{cmd=:02X} (truncated)", level=logging.ERROR)

        except Memory25xTraceTypeError as exn:
            self._log(str(exn), level=logging.ERROR)

        finally:
            self._index += 1

    def decode_spi(self, copi, cipo):
        self.decode_trace(Memory25xSPITrace(copi, cipo))

    def decode_qspi(self, data):
        self.decode_trace(Memory25xQSPITrace(data))


class Memory25xAppletTool(GlasgowAppletTool, applet=Memory25xApplet):
    logger = logging.getLogger(__name__)
    help = "decode communications with 25-series Flash memories and extract data"
    description = """
    Dissect captured SPI/QSPI transactions and extract data into linear memory image files.

    The expected capture file format is the same as ones used by `spi-analyzer` and `qspi-analyzer`
    applets. Specifically, one of the following Comma-Separated Value line formats is expected:

    * ``<COPI>,<CIPO>``, where <COPI> and <CIPO> are hexadecimal byte sequences with each eight
      bits corresponding to samples of COPI and CIPO, respectively (from MSB to LSB).

    * ``<DATA>``, where <DATA> is a hexadecimal nibble sequence with each four bits corresponding
      to samples of HOLD#, WP#, CIPO, COPI (from MSB to LSB).

    The extracted data can be saved as pairs of data files and mask files, where the mask file
    contains a 1 bit for every bit in the data file that has been observed in a transaction,
    and a 0 bit otherwise.

    The list below details every command that is recognized by this tool. If your capture includes
    commands not currently recognized, please open an issue with a capture file attached.

    * 03h (Read Data)\n
    * 04h (Write Disable)\n
    * 05h (Read Status Register)\n
    * 06h (Write Enable)\n
    * 0Bh (Fast Read)\n
    * 4Bh (Read Unique ID)\n
    * 5Ah (Read SFDP)\n
    * 9Fh (Read JEDEC ID)\n
    * B7h (Enter 4-Byte Address Mode)\n
    * E9h (Exit 4-Byte Address Mode)\n
    * 3Bh (Dual Output Fast Read)\n
    * 6Bh (Quad Output Fast Read)\n
    * BBh (Dual I/O Fast Read)\n
    * EBh (Quad I/O Fast Read)\n
    """

    @classmethod
    def add_arguments(cls, parser):
        parser.add_argument(
            "capture_file", metavar="CAPTURE-FILE", type=argparse.FileType("r"),
            help="read captured SPI transactions from CAPTURE-FILE")

        parser.add_argument(
            "--data", dest="data_file", metavar="DATA-FILE", type=argparse.FileType("wb"),
            help="write extracted data to DATA-FILE")
        parser.add_argument(
            "--data-mask", dest="data_mask_file", metavar="MASK-FILE", type=argparse.FileType("wb"),
            help="write data presence mask to MASK-FILE")

        parser.add_argument(
            "--sfdp", dest="sfdp_file", metavar="DATA-FILE", type=argparse.FileType("wb"),
            help="write extracted SFDP data to DATA-FILE")
        parser.add_argument(
            "--sfdp-mask", dest="sfdp_mask_file", metavar="MASK-FILE", type=argparse.FileType("wb"),
            help="write SFDP data presence mask to MASK-FILE")

        parser.add_argument(
            "--uid", dest="uid_file", metavar="DATA-FILE", type=argparse.FileType("wb"),
            help="write extracted UID data to DATA-FILE")
        parser.add_argument(
            "--uid-mask", dest="uid_mask_file", metavar="MASK-FILE", type=argparse.FileType("wb"),
            help="write UID data presence mask to MASK-FILE")

    async def run(self, args):
        decoder = Memory25xDecoder(self.logger)

        for index, line in enumerate(args.capture_file):
            try:
                match line.split(","):
                    case (copi, cipo):
                        decoder.decode_spi(bytes.fromhex(copi), bytes.fromhex(cipo))
                    case (data,):
                        decoder.decode_qspi(bytes.fromhex(data))
                    case _:
                        self.logger.error(f"line {index + 1}: unrecognized data")
            except ValueError:
                self.logger.error(f"line {index + 1}: invalid hex digit")

        if decoder.unknown:
            self.logger.warning("unknown commands encountered: %s",
                ", ".join(f"{cmd:02X}" for cmd in decoder.unknown))

        if decoder.jedec_id is not None:
            mfg_id, device_id = decoder.jedec_id
            mfg_name = jedec_mfg_name_from_bytes([mfg_id]) or "unknown"
            self.logger.info(
                f"JEDEC manufacturer {mfg_id:#04x} ({mfg_name}) device {device_id:#06x}")
        else:
            self.logger.info("capture does not have JEDEC device ID")

        try:
            sfdp = await MemoryImageSFDPParser(decoder.sfdp)
            self.logger.info(f"capture contains valid {sfdp} descriptor")
            for line in sfdp.description():
                self.logger.info(f"  {line}")

            for table in sfdp:
                if isinstance(table, SFDPJEDECFlashParametersTable):
                    decoder.data.write(table.density >> 3, b"") # stretch to real size

        except ValueError as exn:
            self.logger.info(f"capture does not have valid SFDP data: {exn}")

        if decoder.uid:
            self.logger.info("capture contains UID")

        decoder.data.save(args.data_file, args.data_mask_file)
        decoder.sfdp.save(args.sfdp_file, args.sfdp_mask_file)
        decoder.uid.save(args.uid_file, args.uid_mask_file)
