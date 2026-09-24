# Ref: Easy R8C/M16C/M32C/R32C Flash Programming (DJ Delorie)
# Accession: G00045
# Ref: M16C/80 Group Explanation of boot loader
# Accession: G00046
# Ref: R8C/Tiny Series R8C/10, 11, 12, 13 Groups Serial Protocol Specification
# Accession: G00047

# The autobaud sequence is described in G00047; that document describes R8C, but it applies to M16C
# as well. The rest of the commands are described in G00046 for M16C, though they are very similar
# to the commands described in G00047 for R8C.
#
# The code below is written with the intent that some day it will be reused across multiple Renesas
# MCU families, which is why it is intentionally minimal in terms of features. For example, not all
# MCUs have synchronous serial (Mode 1), and not all MCUs have a BUSY pin (M16C does, R8C doesn't).
#
# No partial reprogram functionality is provided because it requires knowing the erase block map.
# In the future, a database may be used to provide these.

import argparse
import asyncio
import enum

from glasgow.support import logging
from glasgow.support.logging import dump_hex
from glasgow.abstract import AbstractAssembly, GlasgowPin
from glasgow.applet.interface.uart import UARTInterface
from glasgow.applet.control.gpio import GPIOInterface
from glasgow.applet import GlasgowAppletError, GlasgowAppletV2


__all__ = ["M16CBootloaderError", "ProgramM16CInterface"]


BAUD_RATES = {
    9600:   0xB0,
    19200:  0xB1,
    38400:  0xB2,
    57600:  0xB3,
    115200: 0xB4,
}


PAGE_SIZE = 0x100


class Command(enum.IntEnum):
    # Flash array commands.
    READ_STATUS  = 0x70
    CLEAR_STATUS = 0x50
    READ_PAGE    = 0xFF
    PROGRAM_PAGE = 0x41
    ERASE_BLOCK  = 0x20
    ERASE_ALL    = 0xA7
    # Bootloader commands.
    VERSION      = 0xFB
    UNLOCK       = 0xF5
    # Not actually commands, but magic values provided as data.
    ERASE_KEY    = 0xD0


ID_MASK         = 0b0000_11_00
ID_MISSING      = 0b0000_00_00
ID_WRONG        = 0b0000_01_00
ID_CORRECT      = 0b0000_11_00

ST_READY        = 0b1000_0000
ST_ERASE_FAIL   = 0b0010_0000
ST_PROGRAM_FAIL = 0b0001_0000


class M16CBootloaderError(GlasgowAppletError):
    pass


class ProgramM16CInterface:
    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
                 rx: GlasgowPin, tx: GlasgowPin,
                 reset: GlasgowPin | None = None, cnvss: GlasgowPin | None = None,
                 timeout: float = 1.0):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        self._uart_iface = UARTInterface(logger, assembly, rx=rx, tx=tx)
        if reset is not None:
            self._reset_iface = GPIOInterface(logger, assembly, pins=(reset,), name="reset")
        else:
            self._reset_iface = None
        if cnvss is not None:
            self._cnvss_iface = GPIOInterface(logger, assembly, pins=(cnvss,), name="cnvss")
        else:
            self._cnvss_iface = None
        # There's also active low bootloader enable (MODE), but I'm not sure which chips use that,
        # so it's not implemented for now.

        self.timeout = timeout

    def _log(self, message, *args):
        self._logger.log(self._level, "M16C: " + message, *args)

    async def _set_reset(self, active: bool):
        # Active low reset; open drain.
        if self._reset_iface is not None:
            if active:
                await self._reset_iface.output(0, False)
            else:
                await self._reset_iface.input(0)

    async def _set_bootloader(self, active: bool):
        # Active high bootloader enable (CNVSS); open source.
        if self._cnvss_iface is not None:
            if active:
                await self._cnvss_iface.output(0, True)
            else:
                await self._cnvss_iface.input(0)

    async def reset_application(self):
        """Reset the target into the application."""
        self._log("reset mode=application")
        await self._set_reset(True)
        await self._set_bootloader(False)
        await self._set_reset(False)

    async def reset_bootloader(self):
        """Reset the target into the ROM bootloader."""
        self._log("reset mode=bootloader")
        await self._set_reset(True)
        await self._set_bootloader(True)
        await self._set_reset(False)
        await asyncio.sleep(0.150) # make sure it's out of reset

    async def _sync_autobaud(self):
        self._log("sync autobaud")
        for _ in range(16):
            await self._uart_iface.write(b"\x00")
            await self._uart_iface.flush()
            await asyncio.sleep(0.040) # >20 ms delay
        await self._uart_iface.write([BAUD_RATES[9600]])
        async def response():
            while True:
                new_baud, = await self._uart_iface.read(1)
                if new_baud == BAUD_RATES[9600]:
                    return
        try:
            await asyncio.wait_for(response(), timeout=self.timeout)
        except TimeoutError:
            raise M16CBootloaderError("cannot synchronize with ROM bootloader")

    async def sync_bootloader(self):
        """Reset the target into the ROM bootloader and synchronize with it at 9600 baud."""
        await self._uart_iface.set_baud(9600)
        await self.reset_bootloader()
        await self._sync_autobaud()

    async def bootloader_set_baud(self, baud_rate: int):
        """Switch the bootloader, and then the UART, to :py:`baud_rate`."""
        self._log("command set-baud rate=%d", baud_rate)
        await self._uart_iface.write([BAUD_RATES[baud_rate]])
        async def response():
            new_baud, = await self._uart_iface.read(1)
            assert new_baud == BAUD_RATES[baud_rate]
        try:
            await asyncio.wait_for(response(), timeout=self.timeout)
        except TimeoutError:
            raise M16CBootloaderError(f"bootloader does not support baud rate {baud_rate}")
        await self._uart_iface.set_baud(baud_rate)

    async def bootloader_version(self):
        self._log("command version")
        await self._uart_iface.write([Command.VERSION])
        async def response():
            version = await self._uart_iface.read(8)
            self._log("response version=<%s>", version.hex())
            return str(version, encoding="ASCII")
        try:
            return await asyncio.wait_for(response(), timeout=self.timeout)
        except TimeoutError:
            raise M16CBootloaderError("command timeout")

    async def _bootloader_read_status(self):
        self._log("command read-status")
        await self._uart_iface.write([Command.READ_STATUS])
        async def response():
            srd1, srd2 = await self._uart_iface.read(2)
            self._log("response srd1=%s srd2=%s", f"{srd1:08b}", f"{srd2:08b}")
            return srd1, srd2
        try:
            return await asyncio.wait_for(response(), timeout=self.timeout)
        except TimeoutError:
            raise M16CBootloaderError("command timeout")

    async def _bootloader_poll_status(self, timeout):
        while timeout >= 0:
            self._log("command read-status")
            await self._uart_iface.write([Command.READ_STATUS])
            async def response():
                srd1, srd2 = await self._uart_iface.read(2)
                self._log("response srd1=%s srd2=%s", f"{srd1:08b}", f"{srd2:08b}")
                return srd1, srd2
            try:
                return await asyncio.wait_for(response(), timeout=0.1)
            except TimeoutError:
                self._log("poll timeout")
                timeout -= 0.1
        raise M16CBootloaderError("command timeout")

    async def is_bootloader_locked(self):
        _srd1, srd2 = await self._bootloader_read_status()
        if (srd2 & ID_MASK) in (ID_MISSING, ID_WRONG):
            return True
        if (srd2 & ID_MASK) == ID_CORRECT:
            return False
        assert False

    async def unlock_bootloader(self, key, address):
        assert isinstance(key, (bytes, bytearray)) and len(key) <= 7
        self._log("command unlock key=<%s>", key.hex())
        await self._uart_iface.write([Command.UNLOCK])
        await self._uart_iface.write([
            (address >> 0)  & 0xFF,
            (address >> 8)  & 0xFF,
            (address >> 16) & 0xFF,
        ])
        await self._uart_iface.write([len(key)])
        await self._uart_iface.write(key)

        _srd1, srd2 = await self._bootloader_read_status()
        if (srd2 & ID_MASK) == ID_CORRECT:
            return True
        if (srd2 & ID_MASK) == ID_WRONG:
            return False
        assert False

    async def read_page(self, address):
        assert address % PAGE_SIZE == 0
        self._log("command read-page page=%04x", (address >> 8) & 0xFFFF)
        await self._uart_iface.write([Command.READ_PAGE])
        await self._uart_iface.write([
            (address >> 8)  & 0xFF,
            (address >> 16) & 0xFF,
        ])
        async def response():
            data = bytes(await self._uart_iface.read(0x100))
            self._log("response data=<%s>", dump_hex(data))
            return data
        try:
            return await asyncio.wait_for(response(), timeout=self.timeout)
        except TimeoutError:
            raise M16CBootloaderError(f"cannot read page {address:06x}")

    async def program_page(self, address, data):
        assert address % PAGE_SIZE == 0 and len(data) == PAGE_SIZE
        self._log("command program-page page=%04x data=<%s>",
                  (address >> 8) & 0xFFFF, dump_hex(data))
        await self._uart_iface.write([Command.CLEAR_STATUS, Command.PROGRAM_PAGE])
        await self._uart_iface.write([
            (address >> 8)  & 0xFF,
            (address >> 16) & 0xFF,
        ])
        await self._uart_iface.write(data)
        try:
            srd1, _srd2 = await self._bootloader_poll_status(1.0)
            assert (srd1 & ST_READY) != 0
            if (srd1 & ST_PROGRAM_FAIL) != 0:
                raise M16CBootloaderError(f"cannot program page {address:06x}")
        except TimeoutError:
            raise M16CBootloaderError("page program timeout")

    async def erase_block(self, address):
        assert address % PAGE_SIZE == 0
        self._log("command erase-block block=%04x", (address >> 8) & 0xFFFF)
        await self._uart_iface.write([Command.CLEAR_STATUS, Command.ERASE_BLOCK])
        await self._uart_iface.write([
            (address >> 8)  & 0xFF,
            (address >> 16) & 0xFF,
        ])
        await self._uart_iface.write([Command.ERASE_KEY])
        try:
            srd1, _srd2 = await self._bootloader_poll_status(1.0)
            assert (srd1 & ST_READY) != 0
            if (srd1 & ST_ERASE_FAIL) != 0:
                raise M16CBootloaderError(f"cannot erase block {address:06x}")
        except TimeoutError:
            raise M16CBootloaderError("block erase timeout")

    async def erase_all(self):
        self._log("command erase-all")
        await self._uart_iface.write([Command.CLEAR_STATUS, Command.ERASE_ALL, Command.ERASE_KEY])
        try:
            srd1, _srd2 = await self._bootloader_poll_status(10.0)
            assert (srd1 & ST_READY) != 0
            if (srd1 & ST_ERASE_FAIL) != 0:
                raise M16CBootloaderError("cannot erase entire array")
        except TimeoutError:
            raise M16CBootloaderError("entire array erase timeout")


class ProgramM16CApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "program Renesas M16C microcomputers via UART"
    description = """
    Read and write Renesas M16C series microcomputer integrated Flash memory via asynchronous
    serial interface ("Mode 2" in Renesas terminology).

    If provided, this applet will drive the reset and bootloader mode pins. However, it will not
    drive the bootloader serial interface mode pin, which must be strapped externally to select
    Mode 2. Consult the datasheet for details.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "rx", required=True, default=True)
        access.add_pins_argument(parser, "tx", required=True, default=True)
        access.add_pins_argument(parser, "reset", default=True)
        access.add_pins_argument(parser, "cnvss")
        # access.add_pins_argument(parser, "mode")

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.m16c_iface = ProgramM16CInterface(self.logger, self.assembly,
                rx=args.rx, tx=args.tx, reset=args.reset, cnvss=args.cnvss)

    @classmethod
    def add_run_arguments(cls, parser):
        parser.add_argument(
            "-b", "--baud", metavar="RATE", type=int, default=9600, choices=BAUD_RATES.keys(),
            help="set baud rate to RATE bits per second (default: %(default)s)")

        def unlock_key(arg):
            try:
                key = bytes.fromhex(arg)
            except ValueError:
                raise argparse.ArgumentTypeError(f"{arg} is not a hexadecimal string")
            if len(key) > 7:
                raise argparse.ArgumentTypeError(f"{arg} is not a valid bootloader key")
            return key

        parser.add_argument(
            "-k", "--key", metavar="HEX-ID", type=unlock_key, action="append",
            help="unlock bootloader with key(s) HEX-ID (default: 00000000000000, FFFFFFFFFFFFFF)")

        def page_address(arg):
            address = int(arg, 0)
            if address % PAGE_SIZE != 0:
                raise argparse.ArgumentTypeError(f"{arg} is not a page-aligned address")
            return address
        def page_length(arg):
            address = int(arg, 0)
            if address % PAGE_SIZE != 0:
                raise argparse.ArgumentTypeError(f"{arg} is not a page-aligned length")
            return address

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION")

        p_read = p_operation.add_parser(
            "read", help="read Flash memory array")
        p_read.add_argument(
            "address", metavar="ADDRESS", type=page_address,
            help="read memory from address ADDRESS, which must be page-aligned")
        p_read.add_argument(
            "length", metavar="LENGTH", type=page_length,
            help="read LENGTH bytes from memory, which must be a multiple of page size")
        p_read.add_argument(
            "file", metavar="FILENAME", type=argparse.FileType("wb"),
            help="read memory contents to binary file FILENAME")

        p_program = p_operation.add_parser(
            "program", help="program Flash memory array")
        p_program.add_argument(
            "address", metavar="ADDRESS", type=page_address,
            help="program memory from address ADDRESS, which must be page-aligned")
        p_program.add_argument(
            "file", metavar="FILENAME", type=argparse.FileType("rb"),
            help="program memory contents from binary file FILENAME, which must be a multiple "
                 "of page size long")

        p_erase = p_operation.add_parser(
            "erase", help="erase entire Flash memory array")

        p_erase_block = p_operation.add_parser(
            "erase-block", help="erase a single block of Flash memory array")
        p_erase_block.add_argument(
            "address", metavar="ADDRESS", type=page_address,
            help="erase block at address ADDRESS, which must be page-aligned")

    async def run(self, args):
        iface = self.m16c_iface
        try:
            await iface.sync_bootloader()
            self.logger.info("bootloader identification %s", await iface.bootloader_version())

            is_locked = await iface.is_bootloader_locked()
            self.logger.info("bootloader is %s", "locked" if is_locked else "unlocked")

            if is_locked:
                for key in args.key or [b"\xff" * 7, b"\x00" * 7]:
                    # Hardcode M16C key address for now.
                    if await iface.unlock_bootloader(key, address=0x0FFFDF):
                        self.logger.info("unlocked with key %s", key.hex())
                        break
                    else:
                        self.logger.info("failed to unlock with key %s", key.hex())
                else:
                    raise M16CBootloaderError("cannot unlock bootloader")

            if args.baud != 9600:
                await iface.bootloader_set_baud(args.baud)

            if args.operation == "read":
                for address in range(args.address, args.address + args.length, PAGE_SIZE):
                    self.logger.info("reading page %0.*x", 5, address)
                    args.file.write(await iface.read_page(address))

            if args.operation == "program":
                firmware = args.file.read()
                if (len(firmware) % PAGE_SIZE) != 0:
                    raise M16CBootloaderError(
                        f"file size ({len(firmware)}) is not a multiple of page size")

                for offset in range(0, len(firmware), PAGE_SIZE):
                    address   = args.address + offset
                    page_data = firmware[offset:offset + PAGE_SIZE]

                    self.logger.info("programming page %0.*x", 5, address)
                    await iface.program_page(address, page_data)
                    if await iface.read_page(address) != page_data:
                        raise M16CBootloaderError(f"verifying page {address:0{5}x} failed")

            if args.operation == "erase":
                self.logger.info("erasing array")
                await iface.erase_all()

            if args.operation == "erase-block":
                self.logger.info("erasing block %0.*x", 5, args.address)
                await iface.erase_block(args.address)

        finally:
            await iface.reset_application()

    @classmethod
    def tests(cls):
        from . import test
        return test.ProgramM16CAppletTestCase
