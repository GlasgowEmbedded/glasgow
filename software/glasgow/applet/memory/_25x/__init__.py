# Note: flashes vary in their response to unimplemented commands. Some return 00, some return FF,
# some will tristate SO.

import re
import sys
import struct
import logging
import argparse

from ....support.logging import dump_hex
from ....database.jedec import *
from ....protocol.sfdp import *
from ...interface.spi_controller import SPIControllerApplet
from ... import *


class Memory25xError(GlasgowAppletError):
    pass


BIT_WIP  = 0b00000001
BIT_WEL  = 0b00000010
MSK_PROT = 0b00111100
BIT_CP   = 0b01000000
BIT_ERR  = 0b10000000


class Memory25xInterface:
    def __init__(self, interface, logger):
        self.lower       = interface
        self._logger     = logger
        self._level      = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

    def _log(self, message, *args):
        self._logger.log(self._level, "25x: " + message, *args)

    async def _command(self, cmd, arg=[], dummy=0, ret=0):
        arg = bytes(arg)

        self._log("cmd=%02X arg=<%s> dummy=%d ret=%d", cmd, dump_hex(arg), dummy, ret)

        await self.lower.write(bytearray([cmd, *arg, *[0 for _ in range(dummy)]]),
                               hold_ss=(ret > 0))
        result = await self.lower.read(ret)

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
            callback(len(data), length, "reading address {:#08x}".format(address))
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
        self._log("read status=%s", "{:#010b}".format(status))
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
                raise Memory25xError("{} command failed (status {:08b})".format(command, status))
        return bool(status & BIT_WIP)

    async def write_status(self, status):
        self._log("write status=%s", "{:#010b}".format(status))
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


class Memory25xSFDPParser(SFDPParser):
    async def __init__(self, m25x_iface):
        self._m25x_iface = m25x_iface
        await super().__init__()

    async def read(self, offset, length):
        return await self._m25x_iface.read_sfdp(offset, length)


class Memory25xApplet(SPIControllerApplet, name="memory-25x"):
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
            16-pin             8-pin
        HOLD# @ * SCK       CS# @ * VCC
          VCC * * COPI     CIPO * * HOLD#
          N/C * * N/C       WP# * * SCK
          N/C * * N/C       GND * * COPI
          N/C * * N/C
          N/C * * N/C
          CS# * * GND
         CIPO * * WP#

    The default pin assignment follows the pinouts above in the clockwise direction, making it easy
    to connect the memory with probes or, alternatively, crimp an IDC cable wired to a SOIC clip.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access, omit_pins=True)

        access.add_pin_argument(parser, "cs",   default=True, required=True)
        access.add_pin_argument(parser, "cipo", default=True, required=True)
        access.add_pin_argument(parser, "wp",   default=True)
        access.add_pin_argument(parser, "copi", default=True, required=True)
        access.add_pin_argument(parser, "sck",  default=True, required=True)
        access.add_pin_argument(parser, "hold", default=True)

    def build(self, target, args):
        subtarget = super().build(target, args)
        subtarget.comb += subtarget.bus.oe.eq(subtarget.bus.cs == args.cs_active)

        if args.pin_hold is not None:
            hold_t = self.mux_interface.get_pin(args.pin_hold)
            subtarget.comb += [
                hold_t.oe.eq(1),
                hold_t.o.eq(1),
            ]

        return subtarget

    async def run(self, device, args):
        spi_iface = await self.run_lower(Memory25xApplet, device, args)
        return Memory25xInterface(spi_iface, self.logger)

    @classmethod
    def add_interact_arguments(cls, parser):
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
                sys.stdout.write("{}/{} bytes done".format(done, total))
                if status:
                    sys.stdout.write("; {}".format(status))
            sys.stdout.flush()

    async def interact(self, device, args, m25x_iface):
        await m25x_iface.wakeup()

        if args.operation in ("program-page", "program",
                              "erase-sector", "erase-block", "erase-chip",
                              "erase-program"):
            status = await m25x_iface.read_status()
            if status & MSK_PROT:
                self.logger.warning("block protect bits are set to %s, program/erase command "
                                    "might not succeed", "{:04b}"
                                    .format((status & MSK_PROT) >> 2))

        if args.operation == "identify":
            legacy_device_id, = \
                await m25x_iface.read_device_id()
            short_manufacturer_id, short_device_id = \
                await m25x_iface.read_manufacturer_device_id()
            long_manufacturer_id, long_device_id = \
                await m25x_iface.read_manufacturer_long_device_id()
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
                    self.logger.warn("no electronic signature detected; device not present?")
                else:
                    self.logger.info("device lacks JEDEC manufacturer/device ID")
                    self.logger.info("electronic signature %#04x",
                                     legacy_device_id)

            try:
                sfdp = await Memory25xSFDPParser(m25x_iface)
                self.logger.info("device has valid SFDP %d.%d (%s) descriptor",
                                 *sfdp.version, sfdp.jedec_revision)
                for index, table in enumerate(sfdp):
                    if table.vendor_id == 0x00: # JEDEC
                        self.logger.info("  SFDP table #%d: %s %d.%d (%s)",
                                         index, table, *table.version, table.jedec_revision)
                    else:
                        self.logger.info("  SFDP table #%d: %s %d.%d",
                                         index, table, *table.version)
                    if any(table):
                        key_width = max(len(k) for k, v in table) + 1
                        for key, value in table:
                            self.logger.info("    %-*s: %s", key_width, key, value)
            except ValueError as e:
                self.logger.info("device does not have valid SFDP data: %s", str(e))

        if args.operation in ("read", "fast-read"):
            if args.operation == "read":
                data = await m25x_iface.read(args.address, args.length,
                                              callback=self._show_progress)
            if args.operation == "fast-read":
                data = await m25x_iface.fast_read(args.address, args.length,
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
                await m25x_iface.write_enable()
                await m25x_iface.page_program(args.address, data)
            if args.operation == "program":
                await m25x_iface.program(args.address, data, args.page_size,
                                          callback=self._show_progress)
            if args.operation == "erase-program":
                await m25x_iface.erase_program(args.address, data, args.sector_size,
                                                args.page_size, callback=self._show_progress)

        if args.operation == "verify":
            if args.data is not None:
                gold_data = args.data
            if args.file is not None:
                gold_data = args.file.read()

            flash_data = await m25x_iface.read(args.address, len(gold_data))
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
                await m25x_iface.write_enable()
                if args.operation == "erase-sector":
                    await m25x_iface.sector_erase(address)
                if args.operation == "erase-block":
                    await m25x_iface.block_erase(address)

        if args.operation == "erase-chip":
            await m25x_iface.write_enable()
            await m25x_iface.chip_erase()

        if args.operation == "protect":
            status = await m25x_iface.read_status()
            if args.bits is None:
                self.logger.info("block protect bits are set to %s",
                                 "{:04b}".format((status & MSK_PROT) >> 2))
            else:
                status = (status & ~MSK_PROT) | ((args.bits << 2) & MSK_PROT)
                await m25x_iface.write_enable()
                await m25x_iface.write_status(status)

# -------------------------------------------------------------------------------------------------

import unittest


class Memory25xAppletTestCase(GlasgowAppletTestCase, applet=Memory25xApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--pin-sck",  "0", "--pin-cs",   "1",
                                "--pin-copi", "2", "--pin-cipo", "3"])

    # Flash used for testing: Winbond 25Q32BVSIG
    hardware_args = [
        "--voltage",  "3.3",
        "--pin-cs",   "0", "--pin-cipo", "1",
        "--pin-copi", "2", "--pin-sck",  "3",
        "--pin-hold", "4"
    ]
    dut_ids = (0xef, 0x15, 0x4016)
    dut_page_size   = 0x100
    dut_sector_size = 0x1000
    dut_block_size  = 0x10000

    async def setup_flash_data(self, mode):
        m25x_iface = await self.run_hardware_applet(mode)
        if mode == "record":
            await m25x_iface.write_enable()
            await m25x_iface.sector_erase(0)
            await m25x_iface.write_enable()
            await m25x_iface.page_program(0, b"Hello, world!")
            await m25x_iface.write_enable()
            await m25x_iface.sector_erase(self.dut_sector_size)
            await m25x_iface.write_enable()
            await m25x_iface.page_program(self.dut_sector_size, b"Some more data")
            await m25x_iface.write_enable()
            await m25x_iface.sector_erase(self.dut_block_size)
            await m25x_iface.write_enable()
            await m25x_iface.page_program(self.dut_block_size, b"One block later")
        return m25x_iface

    @applet_hardware_test(args=hardware_args)
    async def test_api_sleep_wake(self, m25x_iface):
        await m25x_iface.wakeup()
        await m25x_iface.deep_sleep()

    @applet_hardware_test(args=hardware_args)
    async def test_api_device_ids(self, m25x_iface):
        self.assertEqual(await m25x_iface.read_device_id(),
                         (self.dut_ids[1],))
        self.assertEqual(await m25x_iface.read_manufacturer_device_id(),
                         (self.dut_ids[0], self.dut_ids[1]))
        self.assertEqual(await m25x_iface.read_manufacturer_long_device_id(),
                         (self.dut_ids[0], self.dut_ids[2]))

    @applet_hardware_test(setup="setup_flash_data", args=hardware_args)
    async def test_api_read(self, m25x_iface):
        self.assertEqual(await m25x_iface.read(0, 13),
                         b"Hello, world!")
        self.assertEqual(await m25x_iface.read(self.dut_sector_size, 14),
                         b"Some more data")

    @applet_hardware_test(setup="setup_flash_data", args=hardware_args)
    async def test_api_fast_read(self, m25x_iface):
        self.assertEqual(await m25x_iface.fast_read(0, 13),
                         b"Hello, world!")
        self.assertEqual(await m25x_iface.fast_read(self.dut_sector_size, 14),
                         b"Some more data")

    @applet_hardware_test(setup="setup_flash_data", args=hardware_args)
    async def test_api_sector_erase(self, m25x_iface):
        await m25x_iface.write_enable()
        await m25x_iface.sector_erase(0)
        self.assertEqual(await m25x_iface.read(0, 16),
                         b"\xff" * 16)
        self.assertEqual(await m25x_iface.read(self.dut_sector_size, 14),
                         b"Some more data")
        await m25x_iface.write_enable()
        await m25x_iface.sector_erase(self.dut_sector_size)
        self.assertEqual(await m25x_iface.read(self.dut_sector_size, 16),
                         b"\xff" * 16)

    @applet_hardware_test(setup="setup_flash_data", args=hardware_args)
    async def test_api_block_erase(self, m25x_iface):
        await m25x_iface.write_enable()
        await m25x_iface.block_erase(0)
        self.assertEqual(await m25x_iface.read(0, 16),
                         b"\xff" * 16)
        self.assertEqual(await m25x_iface.read(self.dut_sector_size, 16),
                         b"\xff" * 16)
        self.assertEqual(await m25x_iface.read(self.dut_block_size, 15),
                         b"One block later")
        await m25x_iface.write_enable()
        await m25x_iface.block_erase(self.dut_block_size)
        self.assertEqual(await m25x_iface.read(self.dut_block_size, 16),
                         b"\xff" * 16)

    @applet_hardware_test(setup="setup_flash_data", args=hardware_args)
    async def test_api_chip_erase(self, m25x_iface):
        await m25x_iface.write_enable()
        await m25x_iface.chip_erase()
        self.assertEqual(await m25x_iface.read(0, 16),
                         b"\xff" * 16)
        self.assertEqual(await m25x_iface.read(self.dut_sector_size, 16),
                         b"\xff" * 16)
        self.assertEqual(await m25x_iface.read(self.dut_block_size, 16),
                         b"\xff" * 16)

    @applet_hardware_test(setup="setup_flash_data", args=hardware_args)
    async def test_api_page_program(self, m25x_iface):
        await m25x_iface.write_enable()
        await m25x_iface.page_program(self.dut_page_size * 2, b"test")
        self.assertEqual(await m25x_iface.read(self.dut_page_size * 2, 4),
                         b"test")

    @applet_hardware_test(setup="setup_flash_data", args=hardware_args)
    async def test_api_program(self, m25x_iface):
        # crosses the page boundary
        await m25x_iface.write_enable()
        await m25x_iface.program(self.dut_page_size * 2 - 6, b"before/after", page_size=0x100)
        self.assertEqual(await m25x_iface.read(self.dut_page_size * 2 - 6, 12),
                         b"before/after")

    @unittest.skip("seems broken??")
    @applet_hardware_test(setup="setup_flash_data", args=hardware_args)
    async def test_api_erase_program(self, m25x_iface):
        await m25x_iface.write_enable()
        await m25x_iface.erase_program(0, b"Bye  ",
            page_size=0x100, sector_size=self.dut_sector_size)
        self.assertEqual(await m25x_iface.read(0, 14),
                         b"Bye  , world!")
