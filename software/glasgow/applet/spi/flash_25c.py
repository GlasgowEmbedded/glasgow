import re
import sys
import struct
import logging
import argparse

from .. import *
from .master import SPIMasterApplet


class SPIFlash25CInterface:
    def __init__(self, interface, logger):
        self.lower       = interface
        self._logger     = logger
        self._level      = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

    def _log(self, message, *args):
        self._logger.log(self._level, "SPI Flash 25C: " + message, *args)

    async def _command(self, cmd, arg=[], dummy=0, ret=0):
        arg = bytes(arg)

        self._log("cmd=%02X arg=<%s> dummy=%d ret=%d", cmd, arg.hex(), dummy, ret)

        result = await self.lower.transfer([cmd, *arg, *[0 for _ in range(dummy + ret)]])
        result = result[1 + len(arg) + dummy:]

        self._log("result=<%s>", result.hex())

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

    async def _read_command(self, address, length, chunk_size, cmd, dummy=0):
        if chunk_size is None:
            chunk_size = 512

        data = bytearray()
        while length > 0:
            chunk   = await self._command(cmd, arg=self._format_addr(address),
                                          dummy=dummy, ret=min(chunk_size, length))
            data   += chunk

            length  -= len(chunk)
            address += len(chunk)

        return data

    async def read(self, address, length, chunk_size=None):
        self._log("read addr=%#08x len=%d", address, length)
        return await self._read_command(address, length, chunk_size, cmd=0x03)

    async def fast_read(self, address, length, chunk_size=None):
        self._log("fast read addr=%#08x len=%d", address, length)
        return await self._read_command(address, length, chunk_size, cmd=0x0B, dummy=1)

    async def read_status(self):
        status, = await self._command(0x05, ret=1)
        self._log("read status=%s", "{:#010b}".format(status))
        return status

    async def write_status(self, status):
        self._log("write status=%s", "{:#010b}".format(status))
        await self._command(0x01, arg=[status])

    async def write_enable(self):
        self._log("write enable")
        await self._command(0x06)

    async def write_disable(self):
        self._log("write disable")
        await self._command(0x04)

    async def write_in_progress(self):
        return bool((await self.read_status()) & 1)

    async def sector_erase(self, address):
        self._log("sector erase addr=%#08x", address)
        await self._command(0x20, arg=self._format_addr(address))
        while await self.write_in_progress(): pass

    async def block_erase(self, address):
        self._log("block erase addr=%#08x", address)
        await self._command(0x52, arg=self._format_addr(address))
        while await self.write_in_progress(): pass

    async def chip_erase(self):
        self._log("chip erase")
        await self._command(0x60)
        while await self.write_in_progress(): pass

    async def page_program(self, address, data):
        data = bytes(data)
        self._log("page program addr=%#08x data=<%s>", address, data.hex())
        await self._command(0x02, arg=self._format_addr(address) + data)
        while await self.write_in_progress(): pass

    async def program(self, address, data, page_size,
                      callback=lambda done, total, status: None):
        data = bytes(data)
        done, total = 0, len(data)
        while len(data) > 0:
            chunk    = data[:page_size - address % page_size]
            data     = data[len(chunk):]

            callback(done, total, "programming page {:#08x}".format(address))
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

            callback(done, total, "erasing sector {:#08x}".format(sector_start))
            await self.write_enable()
            await self.sector_erase(sector_start)

            if not re.match(rb"^\xff*$", sector_data):
                await self.program(sector_start, sector_data, page_size,
                    callback=lambda page_done, page_total, status:
                                callback(done + page_done, total, status))

            address += len(chunk)
            done    += len(chunk)

        callback(done, total, None)


class SPIFlash25CApplet(SPIMasterApplet, name="spi-flash-25c"):
    logger = logging.getLogger(__name__)
    help = "read and write 25C-compatible Flash memories"
    description = """
    Identify, read, and write arbitrary areas of a 25Cxx-compatible Flash memory.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_argument(parser, "hold")

    def build(self, target, args):
        subtarget = super().build(target, args)
        subtarget.comb += subtarget.bus.oe.eq(subtarget.bus.ss == args.ss_active)

        if args.pin_hold:
            hold_t = self.mux_interface.get_pin(args.pin_hold)
            subtarget.comb += [
                hold_t.oe.eq(1),
                hold_t.o.eq(1),
            ]

    async def run(self, device, args):
        spi_iface = await super().run(device, args)
        return SPIFlash25CInterface(spi_iface, self.logger)

    @classmethod
    def add_interact_arguments(cls, parser):
        def address(arg):
            return int(arg, 0)
        def length(arg):
            return int(arg, 0)
        def hex_bytes(arg):
            return bytes.fromhex(arg)

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION")

        p_identify = p_operation.add_parser(
            "identify", help="identify memory using REMS and RDID commands")

        def add_read_arguments(parser):
            parser.add_argument(
                "address", metavar="ADDRESS", type=address, default=0,
                help="read memory starting at address ADDRESS, with wraparound")
            parser.add_argument(
                "length", metavar="LENGTH", type=length, default=0,
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
                "address", metavar="ADDRESS", type=address, default=0,
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

    @staticmethod
    def _show_progress(done, total, status):
        if sys.stdout.isatty():
            sys.stdout.write("\r\033[0K")
            if done < total:
                sys.stdout.write("{}/{} bytes done".format(done, total))
                if status:
                    sys.stdout.write("; {}".format(status))
            sys.stdout.flush()

    async def interact(self, device, args, flash_iface):
        await flash_iface.wakeup()

        if args.operation == "identify":
            manufacturer_id, device_id = \
                await flash_iface.read_manufacturer_device_id()
            long_manufacturer_id, long_device_id = \
                await flash_iface.read_manufacturer_long_device_id()
            if long_manufacturer_id == manufacturer_id:
                self.logger.info("JEDEC manufacturer ID: %#04x, device ID: %#06x",
                                 long_manufacturer_id, long_device_id)
            else:
                self.logger.info("JEDEC manufacturer ID: %#04x, device ID: %#04x",
                                 manufacturer_id, device_id)

        if args.operation in ("read", "fast-read"):
            if args.operation == "read":
                data = await flash_iface.read(args.address, args.length)
            if args.operation == "fast-read":
                data = await flash_iface.fast_read(args.address, args.length)

            if args.file:
                args.file.write(data)
            else:
                print(data.hex())

        if args.operation in ("program-page", "program", "erase-program"):
            if args.data is not None:
                data = args.data
            if args.file is not None:
                data = args.file.read()

            if args.operation == "program-page":
                await flash_iface.write_enable()
                await flash_iface.page_program(args.address, data)
            if args.operation == "program":
                await flash_iface.program(args.address, data, args.page_size,
                                          callback=self._show_progress)
            if args.operation == "erase-program":
                await flash_iface.erase_program(args.address, data, args.sector_size,
                                                args.page_size, callback=self._show_progress)

        if args.operation in ("erase-sector", "erase-block"):
            for address in args.addresses:
                await flash_iface.write_enable()
                if args.operation == "erase-sector":
                    await flash_iface.sector_erase(address)
                if args.operation == "erase-block":
                    await flash_iface.block_erase(address)

        if args.operation == "erase-chip":
            await flash_iface.write_enable()
            await flash_iface.chip_erase()

# -------------------------------------------------------------------------------------------------

class SPIFlash25CAppletTestCase(GlasgowAppletTestCase, applet=SPIFlash25CApplet):
    def test_build(self):
        self.assertBuilds(args=["--pin-sck",  "0", "--pin-ss",   "1",
                                "--pin-mosi", "2", "--pin-miso", "3"])
