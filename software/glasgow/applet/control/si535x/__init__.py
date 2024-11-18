import re
import csv
import logging
import argparse

from ...interface.i2c_initiator import I2CInitiatorApplet
from ... import *


class Si535xError(GlasgowAppletError):
    pass


class Si535xInterface:
    def __init__(self, interface, logger, i2c_address):
        self.lower     = interface
        self._i2c_addr = i2c_address
        self._logger   = logger
        self._level    = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

    @staticmethod
    def _check(result):
        if result is None:
            raise Si535xError("Si535x did not acknowledge command")
        return result

    async def read(self, reg_addr, count=None):
        self._check(await self.lower.write(self._i2c_addr, [reg_addr]))
        values = self._check(await self.lower.read(self._i2c_addr, 1 if count is None else count, stop=True))
        self._logger.log(self._level, "Si535x: read reg=%#04x values=<%s>",
                         reg_addr, values.hex())
        if count is None:
            return values[0]
        else:
            return values

    async def write(self, reg_addr, *values):
        values = bytes(values)
        self._logger.log(self._level, "Si535x: write reg=%#04x values=<%s>",
                         reg_addr, values.hex())
        self._check(await self.lower.write(self._i2c_addr, [reg_addr, *values], stop=True))


class ControlSi535xApplet(I2CInitiatorApplet):
    logger = logging.getLogger(__name__)
    help = "configure Si535x programmable clock generators"
    description = """
    Access registers of Skyworks Si535x programmable clock generators.
    """

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)

        def i2c_address(arg):
            return int(arg, 0)
        parser.add_argument(
            "--i2c-address", type=i2c_address, metavar="ADDR", default=0b1100000,
            help="I2C address of the controller (default: %(default)#07b)")

    async def run(self, device, args):
        i2c_iface = await super().run(device, args)
        return Si535xInterface(i2c_iface, self.logger, args.i2c_address)

    @classmethod
    def add_interact_arguments(cls, parser):
        def register(arg):
            return int(arg, 0)
        def hex_bytes(arg):
            return bytes.fromhex(arg)
        def outputs(arg):
            return sum([1 << int(index) for index in arg.split(",")])

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

        p_program_si5351 = p_operation.add_parser(
            "program-si5351", help="program Si5351A/B/C device with ClockBuilder register map")
        p_program_si5351.add_argument(
            "file", metavar="FILE", type=argparse.FileType("rt"),
            help="ClockBuilder configuration to program")
        p_program_si5351.add_argument(
            "--enable", metavar="OUTPUTS", type=outputs, default=0,
            help="outputs to enable after programming (for \"Powered-up with Output Disabled\")")

    async def interact(self, device, args, si535x_iface):
        if args.operation == "read":
            print((await si535x_iface.read(args.address, args.count)).hex())

        if args.operation == "write":
            await si535x_iface.write(args.address, *args.data)

        if args.operation == "program-si5351":
            reg_map = []
            for index, row in enumerate(csv.reader(args.file)):
                if row[0].startswith("#"):
                    continue
                elif (len(row) == 2 and
                        re.match(r"^[0-9]+$", row[0]) and
                        re.match(r"^[0-9A-Fa-f]{2}h$", row[1])):
                    reg_map.append((int(row[0]), int(row[1][:-1], 16)))
                else:
                    raise Si535xError(f"failed to parse register map at line {index}: {','.join(row)}")

            # Disable Outputs: Set CLKx_DIS high; Reg. 3 = 0xFF
            await si535x_iface.write(3, 0xFF)
            # Powerdown all output drivers: Reg. 16, 17, 18, 19, 20, 21, 22, 23 = 0x80
            for addr in [16, 17, 18, 19, 20, 21, 22, 23]:
                await si535x_iface.write(addr, 0x80)
            # (Skipped) Set interrupt masks
            # Write new configuration to device using the contents of the register map
            for addr, value in reg_map:
                await si535x_iface.write(addr, value)
            # Apply PLLA and PLLB soft reset: Reg. 177 = 0xAC
            await si535x_iface.write(177, 0xAC)
            # Enable desired outputs: Reg. 3, clear bits for these outputs
            enabled = await si535x_iface.read(3)
            await si535x_iface.write(3, enabled & ~args.enable)

            self.logger.info("programming done")
