# Ref: https://www.skyworksinc.com/-/media/Skyworks/SL/documents/public/data-sheets/Si5351-B.pdf
# Accession: G00102

# Ref: https://www.skyworksinc.com/-/media/Skyworks/SL/documents/public/application-notes/AN619.pdf
# Document Number: AN619
# Accession: G00103

from typing import Optional, TextIO
import re
import csv
import logging
import argparse

from glasgow.applet.interface.i2c_controller import I2CNotAcknowledged, I2CControllerInterface
from glasgow.applet import GlasgowAppletError, GlasgowAppletV2


__all__ = ["Si535xError", "Si535xInterface", "I2CNotAcknowledged"]


class Si535xError(GlasgowAppletError):
    pass


class Si535xInterface:
    def __init__(self, logger: logging.Logger, i2c_iface: I2CControllerInterface,
                 i2c_address: int = 0x60):
        self._logger   = logger
        self._level    = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        self._i2c_iface   = i2c_iface
        self._i2c_address = i2c_address

    def _log(self, message, *args):
        self._logger.log(self._level, "Si535x: " + message, *args)

    async def read(self, address: int, count: Optional[int] = None) -> int | bytes:
        """Read a register or several consecutive registers starting at :py:`address`.

        Returns an :class:`int` if :py:`count is None`, and :class:`bytes` otherwise.

        Raises
        ------
        I2CNotAcknowledged
            If communication fails.
        """
        async with self._i2c_iface.transaction():
            await self._i2c_iface.write(self._i2c_address, [address])
            values = await self._i2c_iface.read(self._i2c_address, 1 if count is None else count)
        self._log("read reg=%#04x values=<%s>", address, values.hex())
        return values[0] if count is None else values

    async def write(self, address: int, *values: int):
        """Write a register or several consecutive registers starting at :py:`address`.

        Raises
        ------
        I2CNotAcknowledged
            If communication fails.
        """
        values = bytes(values)
        self._log("write reg=%#04x values=<%s>", address, values.hex())
        await self._i2c_iface.write(self._i2c_address, [address, *values])

    @staticmethod
    def parse_file(file: TextIO) -> list[tuple[int, int]]:
        """Parse a ClockBuilder Pro CSV register file.

        Returns a list of 2-tuples :py:`(register, value)`.

        Raises
        ------
        Si535xError
            If the file contains invalid data.
        """
        sequence = []
        for index, row in enumerate(csv.reader(file)):
            if row[0].startswith("#"):
                continue
            elif (len(row) == 2 and
                    re.match(r"^[0-9]+$", row[0]) and
                    re.match(r"^[0-9A-Fa-f]{2}h$", row[1])):
                sequence.append((int(row[0]), int(row[1][:-1], 16)))
            else:
                raise Si535xError(f"failed to parse register map at line {index}: {','.join(row)}")
        return sequence

    async def configure_si5351(self, sequence: list[tuple[int, int]], enable: Optional[int] = None):
        """Configure a Si5351A/B/C device.

        Accepts a list of 2-tuples :py:`(register, value)` (as returned by :meth:`parse_file`) and
        a bit mask :py:`enable` where a 1 in a position `n` enables `n`-th output.

        Raises
        ------
        I2CNotAcknowledged
            If communication fails.
        """
        # Disable Outputs: Set CLKx_DIS high; Reg. 3 = 0xFF
        await self.write(3, 0xFF)
        # Powerdown all output drivers: Reg. 16, 17, 18, 19, 20, 21, 22, 23 = 0x80
        for address in [16, 17, 18, 19, 20, 21, 22, 23]:
            await self.write(address, 0x80)
        # (Skipped) Set interrupt masks
        # Write new configuration to device using the contents of the register map
        for address, value in sequence:
            await self.write(address, value)
        # Apply PLLA and PLLB soft reset: Reg. 177 = 0xAC
        await self.write(177, 0xAC)
        if enable is not None:
            # Enable desired outputs: Reg. 3, clear bits for these outputs
            clkx_dis = await self.read(3)
            await self.write(3, clkx_dis & ~enable)


class ControlSi535xApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "configure Si535x programmable clock generators"
    description = """
    Access registers of Skyworks Si535x programmable clock generators.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "scl", default=True, required=True)
        access.add_pins_argument(parser, "sda", default=True, required=True)

        def i2c_address(arg):
            return int(arg, 0)
        parser.add_argument(
            "--i2c-address", type=i2c_address, metavar="ADDR", default=0x60,
            help="I2C address of the controller (default: %(default)#04x)")

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.i2c_iface = I2CControllerInterface(self.logger, self.assembly,
                scl=args.scl, sda=args.sda)
            self.si535x_iface = Si535xInterface(self.logger, self.i2c_iface, args.i2c_address)

    async def setup(self, args):
        await self.i2c_iface.clock.set_frequency(400e3)

    @classmethod
    def add_run_arguments(cls, parser):
        def register(arg):
            return int(arg, 0)
        def hex_bytes(arg):
            return bytes.fromhex(arg)
        def outputs(arg):
            return sum(1 << int(index) for index in arg.split(","))

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

        p_read = p_operation.add_parser(
            "read", help="read register(s)")
        p_read.add_argument(
            "address", metavar="ADDRESS", type=register,
            help="register address")
        p_read.add_argument(
            "count", metavar="COUNT", nargs="?", type=int, default=1,
            help="number of registers to read")

        p_write = p_operation.add_parser(
            "write", help="write register(s)")
        p_write.add_argument(
            "address", metavar="ADDRESS", type=register,
            help="register address")
        p_write.add_argument(
            "data", metavar="DATA", type=hex_bytes,
            help="data to write, as hex bytes")

        p_configure_si5351 = p_operation.add_parser(
            "configure-si5351", help="configure Si5351A/B/C device with ClockBuilder register map")
        p_configure_si5351.add_argument(
            "file", metavar="FILE", type=argparse.FileType("rt"),
            help="ClockBuilder Pro CSV configuration to configure")
        p_configure_si5351.add_argument(
            "--enable", metavar="OUTPUTS", type=outputs,
            help="comma-separated list of outputs to enable after configuration "
                 '(for "Powered-up with Output Disabled" mode)')

    async def run(self, args):
        if args.operation == "read":
            print((await self.si535x_iface.read(args.address, args.count)).hex())

        if args.operation == "write":
            await self.si535x_iface.write(args.address, *args.data)

        if args.operation == "configure-si5351":
            await self.si535x_iface.configure_si5351(
                self.si535x_iface.parse_file(args.file),
                enable=args.enable)
            self.logger.info("configuration done")

    @classmethod
    def tests(cls):
        from . import test
        return test.ControlSi535xAppletTestCase
