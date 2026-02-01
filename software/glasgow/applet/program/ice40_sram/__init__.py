# Ref: iCE40 Programming and Configuration Technical Note
# Document Number: FPGA-TN-02001-3.2
# Accession: G00073

import argparse
import asyncio
import logging

from glasgow.abstract import AbstractAssembly, GlasgowPin, ClockDivisor
from glasgow.applet.interface.spi_controller import SPIControllerInterface
from glasgow.applet.control.gpio import GPIOInterface
from glasgow.applet import GlasgowAppletError, GlasgowAppletV2


__all__ = ["ICE40SRAMInterface"]


class ICE40SRAMError(GlasgowAppletError):
    pass


class ICE40SRAMInterface:
    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
                 cs: GlasgowPin, sck: GlasgowPin, copi: GlasgowPin,
                 reset: GlasgowPin, done: GlasgowPin | None = None):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        self._spi_iface = SPIControllerInterface(logger, assembly,
            cs=cs, sck=sck, copi=copi, mode=3)
        self._reset_iface = GPIOInterface(logger, assembly,
            pins=(~reset,), name="reset")
        if done is not None:
            self._done_iface = GPIOInterface(logger, assembly,
                pins=(done,), name="done")
        else:
            self._done_iface = None

    def _log(self, message: str, *args):
        self._logger.log(self._level, "iCE40: " + message, *args)

    @property
    def clock(self) -> ClockDivisor:
        """SCK clock divisor."""
        return self._spi_iface.clock

    async def load(self, bitstream: bytes | bytearray | memoryview) -> bool:
        """Load :py:`bitstream` into configuration SRAM.

        Raises
        ------
        ICE40SRAMError
            If the CDONE pin is present and was not asserted within 100 ms after the bitstream
            has been shifted in.
        """

        # Assert CS# low as RESET# is deasserted to prevent FPGA from attempting to configure
        # from flash using the same SPI interface.
        self._log("resetting")
        await self._spi_iface.synchronize()
        await self._reset_iface.output(0, True)

        async with self._spi_iface.select():
            # Shift a dummy byte to ensure CS# is actually asserted. (This is a property of
            # the Glasgow SPI controller as of 2026-02-01).
            await self._spi_iface.dummy(1)
            await self._spi_iface.synchronize()

            await self._reset_iface.output(0, False)
            await self._spi_iface.synchronize()

            # Wait at least 1.2ms (spec for 8k devices)
            await self._spi_iface.delay_us(1200)

            self._log("programming")

            # Write bitstream
            await self._spi_iface.write(bitstream)

            # Specs says at least 49 dummy bits. Send 128.
            await self._spi_iface.dummy(128)

        if self._done_iface is not None:
            self._log("waiting for CDONE")
            for _ in range(10):    # Wait up to 100 ms
                await asyncio.sleep(0.010)  # Poll every 10 ms
                if await self._done_iface.get(0):
                    return

            raise ICE40SRAMError("FPGA failed to configure")

        else:
            self._log("waiting for CDONE (absent)")


class ProgramICE40SRAMApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "program SRAM of iCE40 FPGAs"
    description = """
    Program the volatile bitstream memory of iCE40 FPGAs.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "cs",    default=True, required=True)
        access.add_pins_argument(parser, "sck",   default=True, required=True)
        access.add_pins_argument(parser, "copi",  default=True, required=True)
        access.add_pins_argument(parser, "reset", default=True, required=True)
        access.add_pins_argument(parser, "done",  default=True)

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.ice40_iface = ICE40SRAMInterface(self.logger, self.assembly,
                cs=args.cs, sck=args.sck, copi=args.copi,
                reset=args.reset, done=args.done)

    @classmethod
    def add_setup_arguments(cls, parser):
        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=12000,
            help="set SCK frequency to FREQ kHz (default: %(default)s)")

    async def setup(self, args):
        await self.ice40_iface.clock.set_frequency(args.frequency * 1000)

    @classmethod
    def add_run_arguments(cls, parser):
        parser.add_argument(
            "bitstream", metavar="BITSTREAM", type=argparse.FileType("rb"),
            help="bitstream file")

    async def run(self, args):
        await self.ice40_iface.load(args.bitstream.read())
        self.logger.info("FPGA successfully configured")

    @classmethod
    def tests(cls):
        from . import test
        return test.ProgramICE40SRAMAppletTestCase
