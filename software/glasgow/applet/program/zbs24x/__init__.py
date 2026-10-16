# Implements the flashing protocol for ZBS24x microcontrollers as used in some
# electronic price tags. The microcontroller is built around an 8051, and the
# flashing protocol is based around SPI (but with very slow access patterns).
#
# There are no publicly available docs for either the ZBS24x family of
# microcontrollers or their programming protocol, so this implementation is
# based on community references.
#
# Reference: https://dmitry.gr/?r=05.Projects&proj=30.%20Reverse%20Engineering%20an%20Unknown%20Microcontroller
# Reference: https://github.com/atc1441/ZBS_Flasher/blob/main/README.md
#
# Tested on ZB243 in an ST-GR2900N tag. Might work on others.

import argparse
import asyncio
from dataclasses import dataclass
import enum
import logging
import struct

from fx2.format import input_data, output_data

from glasgow.abstract import AbstractAssembly, GlasgowPin, ClockDivisor
from glasgow.applet import GlasgowAppletError, GlasgowAppletV2
from glasgow.applet.control.gpio import GPIOInterface
from glasgow.applet.interface.spi_controller import SPIControllerInterface, SPICommand
from glasgow.gateware import spi


__all__ = ["ProgramZBS24xError", "ProgramZBS24xInterface"]


class ProgramZBS24xError(GlasgowAppletError):
    pass


class _Op(enum.Enum):
    """Operations/commands within the ZBS24x debug/program protocol."""

    RAM_WRITE   = 0x02
    RAM_READ    = 0x03
    FLASH_WRITE = 0x08
    FLASH_READ  = 0x09
    WRITE_SFR   = 0x12
    READ_SFR    = 0x13

    ERASE_INFOBLOCK = 0x48
    ERASE_FLASH = 0x88


@dataclass
class MemoryArea:
    name: str
    bank: int
    size: int


memory_areas = [
    # This order will be reflected in the generated IHEX files. Most
    # 8051-related IHEX parsers seem to want to have the main code area last.
    MemoryArea("infoblock", 0x80, 0x400),
    MemoryArea("main", 0x00, 0x10000),
]


class ProgramZBS24xInterface:
    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
                 cs: GlasgowPin, sck: GlasgowPin, copi: GlasgowPin, cipo: GlasgowPin,
                 reset: GlasgowPin):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        self._spi_iface = SPIControllerInterface(logger, assembly,
            sck=sck, copi=copi, cipo=cipo, cs=cs, mode=0)
        self._reset_iface = GPIOInterface(logger, assembly, pins=(~reset,))

    def _log(self, message, *args):
        self._logger.log(self._level, "ZBS24x: " + message, *args)

    @property
    def clock(self) -> ClockDivisor:
        return self._spi_iface.clock

    async def reset(self, program: bool = True):
        """Resets the chip, optionally putting it into programming mode."""
        self._log("reset")
        await self._spi_iface.synchronize()

        # In the beginning, reset is not being asserted. The chip does what it
        # wants.
        await self._reset_iface.output(0, False)
        await asyncio.sleep(0.02)

        # Then, reset gets asserted. The chip ceases to execute code. But a
        # part of it still listens.
        await self._reset_iface.output(0, True)
        await asyncio.sleep(0.032)

        # A secret handshake in the form of rapidly toggling the clock line:
        # the user wishes for the chip to switch to programming mode.
        if program:
            # Reference says that CS should not be asserted during this
            # process, but in testing this seems to actually be required?
            async with self._spi_iface.select(0):
                await self._spi_iface.dummy(4)
                await self._spi_iface.synchronize()
        await asyncio.sleep(0.01)

        # And then, just like that, the reset period is over.
        await self._reset_iface.output(0, False)
        await asyncio.sleep(0.1)

        # Has the chip switched into programming mode? The only way to find out
        # is to speak its tongue and hope that it talks back to us.

    def _command(self, cmd: bytes, ret: int = 0) -> bytes:
        """Build a command buffer for the SPI controller peripheral.

        We need to do this here because the current SPIController host-side
        implementation expects some level of sanity from the SPI peripheral,
        eg. being able to roundtrip multiple bytes per read and not needing to
        assert CS for every byte.

        We could implement custom gateware that is purpose specific to this SPI
        flavour, but this is probably good enough.
        """
        def set_mode(mode: int):
            return struct.pack("<B", (SPICommand.SetMode.value << 4) | mode)

        def select(ix: int):
            return struct.pack("<B", (SPICommand.Select.value << 4) | (1 + ix))

        def deselect():
            return struct.pack("<B", (SPICommand.Select.value << 4) | (0))

        def write(data: bytes):
            return struct.pack("<BH",
                (SPICommand.Transfer.value << 4) | spi.Operation.Put.value,
                len(data)) + data

        def read(count: int):
            return struct.pack("<BH",
                (SPICommand.Transfer.value << 4) | spi.Operation.Get.value,
                count)

        def delay_us(us: int):
            return struct.pack("<BH", (SPICommand.Delay.value << 4), us)

        buf = b""
        buf += set_mode(0)
        for c in cmd:
            buf += select(0)
            buf += write(bytes([c]))
            buf += deselect()
            buf += delay_us(3)

        for _ in range(ret):
            buf += select(0)
            buf += read(1)
            buf += deselect()
            buf += delay_us(3)

        return buf

    async def _exec_single_command(self, cmd: [int], ret: int = 0) -> bytes | None:
        """Execute a single ZBS24x flash protocol command synchronously."""
        buf = self._command(cmd, ret)

        # Send command buffer.
        await self._spi_iface._pipe.send(buf)
        await self._spi_iface._pipe.flush()

        # Read data back.
        if ret > 0:
            return await self._spi_iface._pipe.recv(ret)
        return None

    async def check_presence(self):
        """Returns true if chip seems to be responsive to our communcation
        attempts.
        """
        # Vendor programmer tool does a memory read/write of a constant value
        # to a constant address.
        addr = 0xba
        value = 0xa5

        await self._exec_single_command(struct.pack(">BBB", _Op.RAM_WRITE.value, addr, value))
        res = await self._exec_single_command(struct.pack(">BB", _Op.RAM_READ.value, addr), 1)
        return res[0] == value

    async def read_flash_range(self, start: int, length: int) -> bytes:
        """Reads length bytes from currently selected flash bank at given start
        offset.
        """
        assert start + length <= 0x10000

        async def send():
            """Command buffer sender, running in an asyncio task."""
            for addr in range(start, start+length):
                buf = self._command(struct.pack(">BH", _Op.FLASH_READ.value, addr), 1)
                await self._spi_iface._pipe.send(buf)
            await self._spi_iface._pipe.flush()

        # Start sending requests for data.
        send_task = asyncio.create_task(send())
        # Receive resulting bytes.
        try:
            return await self._spi_iface._pipe.recv(length)
        except asyncio.CancelledError:
            # If we get canceled, cancel the send task, too.
            send_task.cancel()
            raise

    async def write_flash(self, start: int, data: bytes):
        """Writes data to currently selected flash bank at given start offset."""
        assert start + len(data) <= 0x10000

        for i, byte in enumerate(data):
            addr = start + i
            buf = self._command(struct.pack(">BHB", _Op.FLASH_WRITE.value, addr, byte))
            await self._spi_iface._pipe.send(buf)
        await self._spi_iface._pipe.flush()

    async def read_sfr(self, sfr: int) -> int:
        """Writes value to the given 8051 SFR."""
        res = await self._exec_single_command(struct.pack(">BB", _Op.READ_SFR.value, sfr), 1)
        return res[0]

    async def write_sfr(self, sfr: int, value: int):
        """Reads value from the given 8051 SFR."""
        await self._exec_single_command(struct.pack(">BBB", _Op.WRITE_SFR.value, sfr, value))

    async def select_flash_bank(self, bank: int):
        """Selects flash bank for flash operations (read, write).

        Currently known are:

          - 0x00: main flash, 0x10000 bytes
          - 0x80: infoblock, 0x400 bytes
        """
        await self.write_sfr(0xd8, bank)
        assert await self.read_sfr(0xd8) == bank

    async def erase_infoblock(self):
        """Erases entire infoblock flash area."""
        # Seems the infoblock only gets erased if we first switch over the
        # bank to the infoblock.
        await self.select_flash_bank(0x80)
        await self._exec_single_command(bytes([_Op.ERASE_INFOBLOCK.value, 0x00, 0x00, 0x00]))
        # Give the chip some time to actually perform the erase. Immediately
        # resetting out of programming mode sometimes causes a partial erase.
        await asyncio.sleep(1)

    async def erase_flash(self):
        """Erases entire main flash area."""
        # Converesely, switch over to the main flash area before attempting to
        # erase.
        await self.select_flash_bank(0x00)
        await self._exec_single_command(bytes([_Op.ERASE_FLASH.value, 0x00, 0x00, 0x00]))
        await asyncio.sleep(1)


class ProgramZBS24xApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "program Samsung ZBS24x microcontrollers"
    description = """
    Program the non-volatile memory of Samsung ZBS243 microcontrollers.
    """

    required_revision = "C0"
    zbs24x_iface: ProgramZBS24xInterface

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        # Order matches debug pins on ST-GR2900N e-paper tag test pads,
        # skipping UART pins.
        access.add_pins_argument(parser, "copi", default=True, required=True)
        access.add_pins_argument(parser, "cs", default=True, required=True)
        access.add_pins_argument(parser, "sck", default=True, required=True)
        access.add_pins_argument(parser, "cipo", default=True, required=True)
        access.add_pins_argument(parser, "reset", default=True, required=True)

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.zbs24x_iface = ProgramZBS24xInterface(self.logger, self.assembly,
                cs=args.cs, sck=args.sck, copi=args.copi, cipo=args.cipo,
                reset=args.reset)

    @classmethod
    def add_setup_arguments(cls, parser):
        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=500,
            help="set SPI frequency to FREQ kHz (default: %(default)s")

    async def setup(self, args):
        await self.zbs24x_iface.clock.set_frequency(args.frequency * 1000)

    @classmethod
    def add_run_arguments(cls, parser):
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)
        p_read = p_operation.add_parser("read", help="read MCU flash and infoblock contents")
        p_read.add_argument(
            "file", metavar="HEX-FILE", type=argparse.FileType("wb"),
            help="firmware file to write (in Intel HEX format)")

        p_program = p_operation.add_parser("program", help="read MCU flash and infoblock contents")
        p_program.add_argument(
            "file", metavar="HEX-FILE", type=argparse.FileType("rb"),
            help="firmware file to read (in Intel HEX format)")

        p_operation.add_parser("erase-flash", help="erase MCU flash contents")
        p_operation.add_parser("erase-infoblock", help="erase MCU infoblock contents")

    async def run(self, args):
        try:
            await self.zbs24x_iface.reset()
            if not await self.zbs24x_iface.check_presence():
                raise ProgramZBS24xError("MCU is not present")
            else:
                self.logger.info("detected MCU")

            if args.operation == "read":
                chunks = []
                for area in memory_areas:
                    self.logger.info(f"reading %s memory", area.name)
                    await self.zbs24x_iface.select_flash_bank(area.bank)
                    chunk = await self.zbs24x_iface.read_flash_range(0, area.size)
                    chunks.append((area.bank << 16, chunk))
                output_data(args.file, chunks, fmt="ihex")

            if args.operation == "program":
                if args.frequency > 500:
                    # Not sure if it's the test wiring or an actual limitation
                    # of the hardware.
                    self.logger.warning("flashing with clock over 500KHz is unstable!")

                for chunk_mem_addr, chunk_data in sorted(input_data(args.file, fmt="ihex"),
                                                         key=lambda c: c[0]):
                    bank = chunk_mem_addr >> 16
                    addr = chunk_mem_addr & 0xffff
                    chunk_len = len(chunk_data)

                    if chunk_len == 0:
                        continue

                    matching = [area for area in memory_areas if area.bank == bank]
                    if not matching:
                        self.logger.error(f"unknown bank %x, refusing to flash", bank)
                        return
                    area = matching[0]
                    if addr + chunk_len > area.size:
                        self.logger.error(
                            f"can't write %#06x bytes at %#06x in %s memory: too long",
                            chunk_len, addr, area.name)
                        return
                    self.logger.info(f"writing %#06x bytes at %#06x in %s memory",
                                     chunk_len, addr, area.name)
                    await self.zbs24x_iface.select_flash_bank(area.bank)
                    await self.zbs24x_iface.write_flash(chunk_mem_addr & 0xffff, chunk_data)

            if args.operation == "erase-flash":
                self.logger.info("erasing flash memory")
                await self.zbs24x_iface.erase_flash()

            if args.operation == "erase-infoblock":
                self.logger.info("erasing infoblock memory")
                await self.zbs24x_iface.erase_infoblock()

        finally:
            # Let the chip run again.
            await self.zbs24x_iface.reset(False)
