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

import logging
import argparse
import asyncio
import enum
from contextlib import contextmanager
from nmigen import *

from ....support.logging import *
from ....gateware.pads import *
from ....gateware.uart import *
from ... import *


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


class ProgramM16CSubtarget(Elaboratable):
    def __init__(self, pads, out_fifo, in_fifo, bit_cyc, reset, mode, max_bit_cyc):
        self.pads     = pads
        self.out_fifo = out_fifo
        self.in_fifo  = in_fifo

        self.bit_cyc  = bit_cyc
        self.reset    = reset
        self.mode     = mode

        self.uart     = UART(pads, bit_cyc=max_bit_cyc)

    def elaborate(self, platform):
        m = Module()

        m.submodules.uart = self.uart
        m.d.comb += [
            self.uart.bit_cyc.eq(self.bit_cyc),
            # RX
            self.in_fifo.din.eq(self.uart.rx_data),
            self.in_fifo.we.eq(self.uart.rx_rdy),
            self.uart.rx_ack.eq(self.in_fifo.writable),
            # TX
            self.uart.tx_data.eq(self.out_fifo.dout),
            self.out_fifo.re.eq(self.uart.tx_rdy),
            self.uart.tx_ack.eq(self.out_fifo.readable),
        ]

        if hasattr(self.pads, "reset_t"):
            m.d.comb += [
                # Active low reset.
                self.pads.reset_t.o.eq(0),
                self.pads.reset_t.oe.eq(self.reset),
            ]

        if hasattr(self.pads, "cnvss_t"):
            m.d.comb += [
                # Active high bootloader enable (CNVSS).
                self.pads.cnvss_t.o.eq(1),
                self.pads.cnvss_t.oe.eq(self.mode),
            ]

        # There's also active low bootloader enable (MODE), but I'm not sure which chips use that,
        # so it's not implemented for now.

        return m


class ProgramM16CInterface:
    def __init__(self, interface, logger, addr_reset, addr_mode, timeout=1.0):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._addr_reset = addr_reset
        self._addr_mode  = addr_mode
        self.timeout = timeout

    def _log(self, message, *args):
        self._logger.log(self._level, "M16C: " + message, *args)

    async def reset_application(self):
        self._log("reset mode=application")
        await self.lower.device.write_register(self._addr_reset, 1)
        await self.lower.device.write_register(self._addr_mode, 0)
        await self.lower.device.write_register(self._addr_reset, 0)
        await self.lower.reset()

    async def reset_bootloader(self):
        self._log("reset mode=bootloader")
        await self.lower.device.write_register(self._addr_reset, 1)
        await self.lower.device.write_register(self._addr_mode, 1)
        await self.lower.device.write_register(self._addr_reset, 0)
        await self.lower.reset()
        await asyncio.sleep(0.150) # make sure it's out of reset

    async def _sync_autobaud(self):
        self._log("sync autobaud")
        for _ in range(16):
            await self.lower.write(b"\x00")
            await self.lower.flush()
            await asyncio.sleep(0.040) # >20 ms delay
        await self.lower.write([BAUD_RATES[9600]])
        async def response():
            while True:
                new_baud, = await self.lower.read(1)
                if new_baud == BAUD_RATES[9600]:
                    return
        try:
            await asyncio.wait_for(response(), timeout=self.timeout)
        except asyncio.TimeoutError:
            raise M16CBootloaderError("cannot synchronize with ROM bootloader")

    async def sync_bootloader(self):
        await self.reset_bootloader()
        await self._sync_autobaud()

    async def bootloader_set_baud(self, baud_rate):
        self._log("command set-baud rate=%d", baud_rate)
        await self.lower.write([BAUD_RATES[baud_rate]])
        async def response():
            new_baud, = await self.lower.read(1)
            assert new_baud == BAUD_RATES[baud_rate]
        try:
            return await asyncio.wait_for(response(), timeout=self.timeout)
        except asyncio.TimeoutError:
            raise M16CBootloaderError("bootloader does not support baud rate {}".format(baud_rate))

    async def bootloader_version(self):
        self._log("command version")
        await self.lower.write([Command.VERSION])
        async def response():
            version = await self.lower.read(8)
            self._log("response version=<%s>", version.hex())
            return str(version, encoding="ASCII")
        try:
            return await asyncio.wait_for(response(), timeout=self.timeout)
        except asyncio.TimeoutError:
            raise M16CBootloaderError("command timeout")

    async def _bootloader_read_status(self):
        self._log("command read-status")
        await self.lower.write([Command.READ_STATUS])
        async def response():
            srd1, srd2 = await self.lower.read(2)
            self._log("response srd1=%s srd2=%s", "{:08b}".format(srd1), "{:08b}".format(srd2))
            return srd1, srd2
        try:
            return await asyncio.wait_for(response(), timeout=self.timeout)
        except asyncio.TimeoutError:
            raise M16CBootloaderError("command timeout")

    async def _bootloader_poll_status(self, timeout):
        while timeout >= 0:
            self._log("command read-status")
            await self.lower.write([Command.READ_STATUS])
            async def response():
                srd1, srd2 = await self.lower.read(2)
                self._log("response srd1=%s srd2=%s", "{:08b}".format(srd1), "{:08b}".format(srd2))
                return srd1, srd2
            try:
                return await asyncio.wait_for(response(), timeout=0.1)
            except asyncio.TimeoutError:
                self._log("poll timeout")
                timeout -= 0.1

    async def is_bootloader_locked(self):
        srd1, srd2 = await self._bootloader_read_status()
        if (srd2 & ID_MASK) in (ID_MISSING, ID_WRONG):
            return True
        if (srd2 & ID_MASK) == ID_CORRECT:
            return False
        assert False

    async def unlock_bootloader(self, key, address):
        assert isinstance(key, (bytes, bytearray)) and len(key) <= 7
        self._log("command unlock key=<%s>", key.hex())
        await self.lower.write([Command.UNLOCK])
        await self.lower.write([
            (address >> 0)  & 0xFF,
            (address >> 8)  & 0xFF,
            (address >> 16) & 0xFF,
        ])
        await self.lower.write([len(key)])
        await self.lower.write(key)

        srd1, srd2 = await self._bootloader_read_status()
        if (srd2 & ID_MASK) == ID_CORRECT:
            return True
        if (srd2 & ID_MASK) == ID_WRONG:
            return False
        assert False

    async def read_page(self, address):
        assert address % PAGE_SIZE == 0
        self._log("command read-page page=%04x", (address >> 8) & 0xFFFF)
        await self.lower.write([Command.READ_PAGE])
        await self.lower.write([
            (address >> 8)  & 0xFF,
            (address >> 16) & 0xFF,
        ])
        async def response():
            data = await self.lower.read(0x100)
            self._log("response data=<%s>", dump_hex(data))
            return data
        try:
            return await asyncio.wait_for(response(), timeout=self.timeout)
        except asyncio.TimeoutError:
            raise M16CBootloaderError("cannot read page {:06x}".format(address))

    async def program_page(self, address, data):
        assert address % PAGE_SIZE == 0 and len(data) == PAGE_SIZE
        self._log("command program-page page=%04x data=<%s>",
                  (address >> 8) & 0xFFFF, dump_hex(data))
        await self.lower.write([Command.CLEAR_STATUS, Command.PROGRAM_PAGE])
        await self.lower.write([
            (address >> 8)  & 0xFF,
            (address >> 16) & 0xFF,
        ])
        await self.lower.write(data)
        try:
            srd1, srd2 = await self._bootloader_poll_status(1.0)
            assert (srd1 & ST_READY) != 0
            if (srd1 & ST_PROGRAM_FAIL) != 0:
                raise M16CBootloaderError("cannot program page {:06x}".format(address))
        except asyncio.TimeoutError:
            raise M16CBootloaderError("page program timeout")

    async def erase_block(self, address):
        assert address % PAGE_SIZE == 0
        self._log("command erase-block block=%04x", (address >> 8) & 0xFFFF)
        await self.lower.write([Command.CLEAR_STATUS, Command.ERASE_BLOCK])
        await self.lower.write([
            (address >> 8)  & 0xFF,
            (address >> 16) & 0xFF,
        ])
        await self.lower.write([Command.ERASE_KEY])
        try:
            srd1, srd2 = await self._bootloader_poll_status(1.0)
            assert (srd1 & ST_READY) != 0
            if (srd1 & ST_ERASE_FAIL) != 0:
                raise M16CBootloaderError("cannot erase block {:06x}".format(address))
        except asyncio.TimeoutError:
            raise M16CBootloaderError("block erase timeout")

    async def erase_all(self):
        self._log("command erase-all")
        await self.lower.write([Command.CLEAR_STATUS, Command.ERASE_ALL, Command.ERASE_KEY])
        try:
            srd1, srd2 = await self._bootloader_poll_status(10.0)
            assert (srd1 & ST_READY) != 0
            if (srd1 & ST_ERASE_FAIL) != 0:
                raise M16CBootloaderError("cannot erase entire array")
        except asyncio.TimeoutError:
            raise M16CBootloaderError("entire array erase timeout")


class ProgramM16CApplet(GlasgowApplet, name="program-m16c"):
    logger = logging.getLogger(__name__)
    help = "program Renesas M16C microcomputers via UART"
    description = """
    Read and write Renesas M16C series microcomputer integrated Flash memory via asynchronous
    serial interface ("Mode 2" in Renesas terminology).

    If provided, this applet will drive the reset and bootloader mode pins. However, it will not
    drive the bootloader serial interface mode pin, which must be strapped externally to select
    Mode 2. Consult the datasheet for details.
    """

    __pins = ("rx", "tx", "reset", "cnvss") # "mode"

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_argument(parser, "rx", required=True, default=True)
        access.add_pin_argument(parser, "tx", required=True, default=True)
        access.add_pin_argument(parser, "reset", default=True)
        access.add_pin_argument(parser, "cnvss")
        # access.add_pin_argument(parser, "mode")

    def build(self, target, args):
        self.__bit_cyc_for_baud = {
            baud: self.derive_clock(input_hz=target.sys_clk_freq, output_hz=baud)
            for baud in BAUD_RATES
        }
        max_bit_cyc = max(self.__bit_cyc_for_baud.values())

        bit_cyc, self.__addr_bit_cyc = target.registers.add_rw(24, reset=max_bit_cyc) # slowest
        reset,   self.__addr_reset   = target.registers.add_rw(1)
        mode,    self.__addr_mode    = target.registers.add_rw(1)

        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        subtarget = iface.add_subtarget(ProgramM16CSubtarget(
            pads=iface.get_pads(args, pins=self.__pins),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(),
            bit_cyc=bit_cyc,
            reset=reset,
            mode=mode,
            max_bit_cyc=max_bit_cyc,
        ))

    @classmethod
    def add_run_arguments(cls, parser, access):
        access.add_run_arguments(parser)

        parser.add_argument(
            "-b", "--baud", metavar="RATE", type=int, default=9600, choices=BAUD_RATES.keys(),
            help="set baud rate to RATE bits per second (default: %(default)s)")

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        return ProgramM16CInterface(iface, self.logger,
            addr_reset=self.__addr_reset,
            addr_mode=self.__addr_mode)

    @classmethod
    def add_interact_arguments(cls, parser):
        def unlock_key(arg):
            try:
                key = bytes.fromhex(arg)
            except ValueError:
                raise argparse.ArgumentTypeError("{} is not a hexadecimal string".format(arg))
            if len(key) > 7:
                raise argparse.ArgumentTypeError("{} is not a valid bootloader key".format(arg))
            return key

        parser.add_argument(
            "-k", "--key", metavar="HEX-ID", type=unlock_key, action="append",
            help="unlock bootloader with key(s) HEX-ID (default: 00000000000000, FFFFFFFFFFFFFF)")

        def page_address(arg):
            address = int(arg, 0)
            if address % PAGE_SIZE != 0:
                raise argparse.ArgumentTypeError("{} is not a page-aligned address".format(arg))
            return address
        def page_length(arg):
            address = int(arg, 0)
            if address % PAGE_SIZE != 0:
                raise argparse.ArgumentTypeError("{} is not a page-aligned length".format(arg))
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

    async def interact(self, device, args, iface):
        try:
            await device.write_register(
                self.__addr_bit_cyc, self.__bit_cyc_for_baud[9600], width=3)
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
                await device.write_register(
                    self.__addr_bit_cyc, self.__bit_cyc_for_baud[args.baud], width=3)

            if args.operation == "read":
                for address in range(args.address, args.address + args.length, PAGE_SIZE):
                    self.logger.info("reading page %0.*x", 5, address)
                    args.file.write(await iface.read_page(address))

            if args.operation == "program":
                firmware = args.file.read()
                if (len(firmware) % PAGE_SIZE) != 0:
                    raise M16CBootloaderError("file size ({}) is not a multiple of page size"
                                              .format(len(firmware)))

                for offset in range(0, len(firmware), PAGE_SIZE):
                    address   = args.address + offset
                    page_data = firmware[offset:offset + PAGE_SIZE]

                    self.logger.info("programming page %0.*x", 5, address)
                    await iface.program_page(address, page_data)
                    if await iface.read_page(address) != page_data:
                        raise M16CBootloaderError("verifying page {:0{}x} failed"
                                                  .format(address, 5))

            if args.operation == "erase":
                self.logger.info("erasing array")
                await iface.erase_all()

            if args.operation == "erase-block":
                self.logger.info("erasing block %0.*x", 5, args.address)
                await iface.erase_block(args.address)

        finally:
            await iface.reset_application()

# -------------------------------------------------------------------------------------------------

class ProgramM16CAppletTestCase(GlasgowAppletTestCase, applet=ProgramM16CApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
