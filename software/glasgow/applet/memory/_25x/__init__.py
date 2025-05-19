# Note: flashes vary in their response to unimplemented commands. Some return 00, some return FF,
# some will tristate SO.

import re
import sys
import struct
import logging
import argparse

from amaranth import *
from amaranth.lib import enum, io

from glasgow.support.logging import dump_hex
from glasgow.database.jedec import *
from glasgow.protocol.sfdp import *
from glasgow.applet import GlasgowAppletError, GlasgowAppletV2
from glasgow.applet.interface.qspi_controller import QSPIControllerInterface, QSPIControllerApplet


__all__ = ["Memory25xError", "Memory25xInterface"]


class Memory25xError(GlasgowAppletError):
    pass


class Memory25xAddrMode(enum.Enum):
    ThreeByte = enum.auto()
    FourByte  = enum.auto()


BIT_WIP  = 0b00000001
BIT_WEL  = 0b00000010
MSK_PROT = 0b00111100
BIT_CP   = 0b01000000
BIT_ERR  = 0b10000000


class Memory25xInterface:
    def __init__(self, logger, assembly, *, cs, sck, io):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        self.qspi = QSPIControllerInterface(logger, assembly, cs=cs, sck=sck, io=io)

    def _log(self, message, *args):
        self._logger.log(self._level, "25x: " + message, *args)

    async def _command(self, cmd, arg=[], dummy=0, ret=0):
        arg = bytes(arg)

        self._log("cmd=%02X arg=<%s> dummy=%d ret=%d", cmd, dump_hex(arg), dummy, ret)

        async with self.qspi.select():
            await self.qspi.write(bytes([cmd, *arg]))
            await self.qspi.dummy(dummy * 8)
            result = await self.qspi.read(ret) if ret else None

        if result is not None:
            self._log("result=<%s>", dump_hex(result))

        return result

    async def wakeup(self):
        self._log("wakeup")
        await self._command(0xAB, dummy=4)

    async def deep_sleep(self):
        self._log("deep sleep")
        await self._command(0xB9)

    async def read_device_id(self):
        self._log("read device ID")
        device_id, = await self._command(0xAB, dummy=3, ret=1)
        return (device_id,)

    async def read_manufacturer_device_id(self):
        self._log("read manufacturer/8-bit device ID")
        manufacturer_id, device_id = await self._command(0x90, dummy=3, ret=2)
        return (manufacturer_id, device_id)

    async def read_manufacturer_long_device_id(self):
        self._log("read manufacturer/16-bit device ID")
        manufacturer_id, device_id = struct.unpack(">BH",
            await self._command(0x9F, ret=3))
        return (manufacturer_id, device_id)

    def _format_addr(self, addr):
        return bytes([(addr >> 16) & 0xff, (addr >> 8) & 0xff, addr & 0xff])

    async def _read_command(self, address, length, chunk_size, cmd, dummy=0,
                            callback=lambda done, total, status: None):
        if chunk_size is None:
            chunk_size = 0x10000 # for progress indication

        data = bytearray()
        while length > len(data):
            callback(len(data), length, f"reading address {address:#08x}")
            chunk    = await self._command(cmd, arg=self._format_addr(address),
                                           dummy=dummy, ret=min(chunk_size, length - len(data)))
            data    += chunk
            address += len(chunk)

        callback(len(data), length, None)
        return data

    async def read(self, address, length, chunk_size=None,
                   callback=lambda done, total, status: None):
        self._log("read addr=%#08x len=%d", address, length)
        return await self._read_command(address, length, chunk_size, cmd=0x03,
                                        callback=callback)

    async def fast_read(self, address, length, chunk_size=None,
                        callback=lambda done, total, status: None):
        self._log("fast read addr=%#08x len=%d", address, length)
        return await self._read_command(address, length, chunk_size, cmd=0x0B, dummy=1,
                                        callback=callback)

    async def read_sfdp(self, address, length):
        self._log("read sfdp addr=%#08x len=%d", address, length)
        return await self._read_command(address, length, chunk_size=0x100, cmd=0x5A, dummy=1)

    async def read_status(self):
        status, = await self._command(0x05, ret=1)
        self._log("read status=%s", f"{status:#010b}")
        return status

    async def write_enable(self):
        self._log("write enable")
        await self._command(0x06)

    async def write_disable(self):
        self._log("write disable")
        await self._command(0x04)

    async def write_in_progress(self, command="write"):
        status = await self.read_status()
        if status & BIT_WEL and not status & BIT_WIP:
            # Looks like some flashes (this was determined on Macronix MX25L3205D) have a race
            # condition between WIP going low and WEL going low, so we can sometimes observe
            # that. Work around by checking twice in a row. Sigh.
            status = await self.read_status()
            if status & BIT_WEL and not status & BIT_WIP:
                raise Memory25xError(f"{command} command failed (status {status:08b})")
        return bool(status & BIT_WIP)

    async def write_status(self, status):
        self._log("write status=%s", f"{status:#010b}")
        await self._command(0x01, arg=[status])
        while await self.write_in_progress(command="WRITE STATUS"): pass

    async def sector_erase(self, address):
        self._log("sector erase addr=%#08x", address)
        await self._command(0x20, arg=self._format_addr(address))
        while await self.write_in_progress(command="SECTOR ERASE"): pass

    async def block_erase(self, address):
        self._log("block erase addr=%#08x", address)
        await self._command(0x52, arg=self._format_addr(address))
        while await self.write_in_progress(command="BLOCK ERASE"): pass

    async def chip_erase(self):
        self._log("chip erase")
        await self._command(0x60)
        while await self.write_in_progress(command="CHIP ERASE"): pass

    async def page_program(self, address, data):
        data = bytes(data)
        self._log("page program addr=%#08x data=<%s>", address, data.hex())
        await self._command(0x02, arg=self._format_addr(address) + data)
        while await self.write_in_progress(command="PAGE PROGRAM"): pass

    async def program(self, address, data, page_size,
                      callback=lambda done, total, status: None):
        data = bytes(data)
        done, total = 0, len(data)
        while len(data) > 0:
            chunk    = data[:page_size - address % page_size]
            data     = data[len(chunk):]

            callback(done, total, f"programming page {address:#08x}")
            await self.write_enable()
            await self.page_program(address, chunk)

            address += len(chunk)
            done    += len(chunk)

        callback(done, total, None)

    async def erase_program(self, address, data, sector_size, page_size,
                            callback=lambda done, total, status: None):
        data = bytes(data)
        done, total = 0, len(data)
        while len(data) > 0:
            chunk    = data[:sector_size - address % sector_size]
            data     = data[len(chunk):]

            sector_start = address & ~(sector_size - 1)
            if address % sector_size == 0 and len(chunk) == sector_size:
                sector_data = chunk
            else:
                sector_data = await self.read(sector_start, sector_size)
                sector_data[address % sector_size:(address % sector_size) + len(chunk)] = chunk

            callback(done, total, f"erasing sector {sector_start:#08x}")
            await self.write_enable()
            await self.sector_erase(sector_start)

            if not re.match(rb"^\xff*$", sector_data):
                await self.program(sector_start, sector_data, page_size,
                    callback=lambda page_done, page_total, status:
                                callback(done + page_done, total, status))

            address += len(chunk)
            done    += len(chunk)

        callback(done, total, None)


class Memory25xSFDPParser(SFDPParser):
    async def __init__(self, m25x_iface):
        self._m25x_iface = m25x_iface
        await super().__init__()

    async def read(self, offset, length):
        return await self._m25x_iface.read_sfdp(offset, length)


class Memory25xApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "read and write 25-series SPI Flash memories"
    description = """
    Identify, read, erase, or program memories compatible with 25-series Flash memory, such as
    Microchip 25C320, Winbond 25Q64, Macronix MX25L1605, or hundreds of other memories that
    typically have "25X" where X is a letter in their part number.

    When using this applet for erasing or programming, it is necessary to look up the page
    and sector sizes. These values are displayed by the `identify` command when the memory is
    self-describing, and can be found in the memory datasheet otherwise.

    The pinout of a typical 25-series IC is as follows:

    ::

                16-pin                     8-pin
        IO3/HOLD# @ * SCK               CS# @ * VCC
              VCC * * IO0/COPI     IO1/CIPO * * IO3/HOLD#
              N/C * * N/C           IO2/WP# * * SCK
              N/C * * N/C               GND * * IO0/COPI
              N/C * * N/C
              N/C * * N/C
              CS# * * GND
         IO1/CIPO * * IO2/WP#

    The default pin assignment follows the pinouts above in the clockwise direction, making it easy
    to connect the memory with probes or, alternatively, crimp an IDC cable wired to a SOIC clip.

    It is also possible to flash 25-series flash chips using the `spi-flashrom` applet, which
    requires a third-party tool `flashrom`.
    The advantage of using the `spi-flashrom` applet is that flashrom offers compatibility with
    a wider variety of devices, some of which may not be supported by the `memory-25x` applet.
    """
    required_revision = QSPIControllerApplet.required_revision

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "cs",  required=True,          default="A5")
        access.add_pins_argument(parser, "io",  required=True, width=4, default="A2,A4,A3,A0",
            help="bind the applet I/O lines 'copi', 'cipo', 'wp', 'hold' to PINS")
        access.add_pins_argument(parser, "sck", required=True,          default="A1")

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.m25x_iface = Memory25xInterface(self.logger, self.assembly,
                cs=args.cs, sck=args.sck, io=args.io)

    @classmethod
    def add_setup_arguments(cls, parser):
        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=12000,
            help="set SCK frequency to FREQ kHz (default: %(default)s)")

    async def setup(self, args):
        await self.m25x_iface.qspi.set_sck_freq(args.frequency * 1000)

    @classmethod
    def add_run_arguments(cls, parser):
        def address(arg):
            return int(arg, 0)
        def length(arg):
            return int(arg, 0)
        def hex_bytes(arg):
            return bytes.fromhex(arg)
        def bits(arg):
            return int(arg, 2)

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

        p_identify = p_operation.add_parser(
            "identify", help="identify memory using REMS and RDID commands")

        def add_read_arguments(parser):
            parser.add_argument(
                "address", metavar="ADDRESS", type=address,
                help="read memory starting at address ADDRESS, with wraparound")
            parser.add_argument(
                "length", metavar="LENGTH", type=length,
                help="read LENGTH bytes from memory")
            parser.add_argument(
                "-f", "--file", metavar="FILENAME", type=argparse.FileType("wb"),
                help="write memory contents to FILENAME")

        p_read = p_operation.add_parser(
            "read", help="read memory using READ command")
        add_read_arguments(p_read)

        p_fast_read = p_operation.add_parser(
            "fast-read", help="read memory using FAST READ command")
        add_read_arguments(p_fast_read)

        def add_program_arguments(parser):
            parser.add_argument(
                "address", metavar="ADDRESS", type=address,
                help="program memory starting at address ADDRESS")
            g_data = parser.add_mutually_exclusive_group(required=True)
            g_data.add_argument(
                "-d", "--data", metavar="DATA", type=hex_bytes,
                help="program memory with DATA as hex bytes")
            g_data.add_argument(
                "-f", "--file", metavar="FILENAME", type=argparse.FileType("rb"),
                help="program memory with contents of FILENAME")

        p_program_page = p_operation.add_parser(
            "program-page", help="program memory page using PAGE PROGRAM command")
        add_program_arguments(p_program_page)

        def add_page_argument(parser):
            parser.add_argument(
                "-P", "--page-size", metavar="SIZE", type=length, required=True,
                help="program memory region using SIZE byte pages")

        p_program = p_operation.add_parser(
            "program", help="program a memory region using PAGE PROGRAM command")
        add_page_argument(p_program)
        add_program_arguments(p_program)

        def add_erase_arguments(parser, kind):
            parser.add_argument(
                "addresses", metavar="ADDRESS", type=address, nargs="+",
                help="erase %s(s) starting at address ADDRESS" % kind)

        p_erase_sector = p_operation.add_parser(
            "erase-sector", help="erase memory using SECTOR ERASE command")
        add_erase_arguments(p_erase_sector, "sector")

        p_erase_block = p_operation.add_parser(
            "erase-block", help="erase memory using BLOCK ERASE command")
        add_erase_arguments(p_erase_block, "block")

        p_erase_chip = p_operation.add_parser(
            "erase-chip", help="erase memory using CHIP ERASE command")

        p_erase_program = p_operation.add_parser(
            "erase-program", help="modify a memory region using SECTOR ERASE and "
                                  "PAGE PROGRAM commands")
        p_erase_program.add_argument(
            "-S", "--sector-size", metavar="SIZE", type=length, required=True,
            help="erase memory in SIZE byte sectors")
        add_page_argument(p_erase_program)
        add_program_arguments(p_erase_program)

        p_protect = p_operation.add_parser(
            "protect", help="query and set block protection using READ/WRITE STATUS "
                            "REGISTER commands")
        p_protect.add_argument(
            "bits", metavar="BITS", type=bits, nargs="?",
            help="set SR.BP[3:0] to BITS")

        p_verify = p_operation.add_parser(
            "verify", help="read memory using READ command and verify contents")
        add_program_arguments(p_verify)

    @staticmethod
    def _show_progress(done, total, status):
        if sys.stdout.isatty():
            sys.stdout.write("\r\033[0K")
            if done < total:
                sys.stdout.write(f"{done}/{total} bytes done")
                if status:
                    sys.stdout.write(f"; {status}")
            sys.stdout.flush()

    async def run(self, args):
        await self.m25x_iface.wakeup()

        if args.operation in ("program-page", "program",
                              "erase-sector", "erase-block", "erase-chip",
                              "erase-program"):
            status = await self.m25x_iface.read_status()
            if status & MSK_PROT:
                self.logger.warning("block protect bits are set to %s, program/erase command "
                                    "might not succeed", "{:04b}"
                                    .format((status & MSK_PROT) >> 2))

        if args.operation == "identify":
            legacy_device_id, = \
                await self.m25x_iface.read_device_id()
            short_manufacturer_id, short_device_id = \
                await self.m25x_iface.read_manufacturer_device_id()
            long_manufacturer_id, long_device_id = \
                await self.m25x_iface.read_manufacturer_long_device_id()
            if short_manufacturer_id not in (0x00, 0xff):
                manufacturer_name = jedec_mfg_name_from_bytes([short_manufacturer_id]) or "unknown"
                self.logger.info("JEDEC manufacturer %#04x (%s) device %#04x (8-bit ID)",
                                 short_manufacturer_id, manufacturer_name, short_device_id)
            if long_manufacturer_id not in (0x00, 0xff):
                manufacturer_name = jedec_mfg_name_from_bytes([long_manufacturer_id]) or "unknown"
                self.logger.info("JEDEC manufacturer %#04x (%s) device %#06x (16-bit ID)",
                                 long_manufacturer_id, manufacturer_name, long_device_id)
            if short_manufacturer_id in (0x00, 0xff) and long_manufacturer_id in (0x00, 0xff):
                if legacy_device_id in (0x00, 0xff):
                    self.logger.warning("no electronic signature detected; device not present?")
                else:
                    self.logger.info("device lacks JEDEC manufacturer/device ID")
                    self.logger.info("electronic signature %#04x",
                                     legacy_device_id)

            try:
                sfdp = await Memory25xSFDPParser(self.m25x_iface)
                self.logger.info(f"device has valid {sfdp} descriptor")
                for line in sfdp.description():
                    self.logger.info(f"  {line}")
            except ValueError as e:
                self.logger.info("device does not have valid SFDP data: %s", str(e))

        if args.operation in ("read", "fast-read"):
            if args.operation == "read":
                data = await self.m25x_iface.read(args.address, args.length,
                                             callback=self._show_progress)
            if args.operation == "fast-read":
                data = await self.m25x_iface.fast_read(args.address, args.length,
                                                  callback=self._show_progress)

            if args.file:
                args.file.write(data)
            else:
                self._show_progress(0, 0, "")
                print(data.hex())

        if args.operation in ("program-page", "program", "erase-program"):
            if args.data is not None:
                data = args.data
            if args.file is not None:
                data = args.file.read()

            if args.operation == "program-page":
                await self.m25x_iface.write_enable()
                await self.m25x_iface.page_program(args.address, data)
            if args.operation == "program":
                await self.m25x_iface.program(args.address, data, args.page_size,
                                         callback=self._show_progress)
            if args.operation == "erase-program":
                await self.m25x_iface.erase_program(args.address, data, args.sector_size,
                                               args.page_size, callback=self._show_progress)

        if args.operation == "verify":
            if args.data is not None:
                gold_data = args.data
            if args.file is not None:
                gold_data = args.file.read()

            flash_data = await self.m25x_iface.read(args.address, len(gold_data))
            if gold_data == flash_data:
                self.logger.info("verify PASS")
            else:
                for offset, (gold_byte, flash_byte) in enumerate(zip(gold_data, flash_data)):
                    if gold_byte != flash_byte:
                        different_at = args.address + offset
                        break
                self.logger.error("first differing byte at %#08x (expected %#04x, actual %#04x)",
                                  different_at, gold_byte, flash_byte)
                raise GlasgowAppletError("verify FAIL")

        if args.operation in ("erase-sector", "erase-block"):
            for address in args.addresses:
                await self.m25x_iface.write_enable()
                if args.operation == "erase-sector":
                    await self.m25x_iface.sector_erase(address)
                if args.operation == "erase-block":
                    await self.m25x_iface.block_erase(address)

        if args.operation == "erase-chip":
            await self.m25x_iface.write_enable()
            await self.m25x_iface.chip_erase()

        if args.operation == "protect":
            status = await self.m25x_iface.read_status()
            if args.bits is None:
                self.logger.info("block protect bits are set to %s",
                                 f"{(status & MSK_PROT) >> 2:04b}")
            else:
                status = (status & ~MSK_PROT) | ((args.bits << 2) & MSK_PROT)
                await self.m25x_iface.write_enable()
                await self.m25x_iface.write_status(status)

    @classmethod
    def tests(cls):
        from . import test
        return test.Memory25xAppletTestCase
