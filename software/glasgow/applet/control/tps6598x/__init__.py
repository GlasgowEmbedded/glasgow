import logging
import asyncio

from ...interface.i2c_initiator import I2CInitiatorApplet
from ... import *


class TPS6598xError(GlasgowAppletError):
    pass


class TPS6598xInterface:
    def __init__(self, interface, logger, i2c_address):
        self.lower     = interface
        self._i2c_addr = i2c_address
        self._logger   = logger
        self._level    = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

    @staticmethod
    def _check(result):
        if result is None:
            raise TPS6598xError("TPS6598x did not acknowledge command")
        return result

    async def read_reg(self, address):
        self._check(await self.lower.write(self._i2c_addr, [address]))
        size, = self._check(await self.lower.read(self._i2c_addr, 1, stop=True))
        self._logger.log(self._level, "TPS6598x: reg=%#04x size=%#04x",
                         address, size)

        self._check(await self.lower.write(self._i2c_addr, [address]))
        data = self._check(await self.lower.read(self._i2c_addr, 1 + size, stop=True))[1:]
        self._logger.log(self._level, "TPS6598x: read=<%s>", data.hex())

        return data

    async def write_reg(self, address, data):
        data = bytes(data)
        self._logger.log(self._level, "TPS6598x: reg=%#04x write=<%s>",
                         address, data.hex())
        self._check(await self.lower.write(self._i2c_addr, [address, len(data), *data], stop=True))


class ControlTPS6598xApplet(I2CInitiatorApplet, name="control-tps6598x"):
    logger = logging.getLogger(__name__)
    help = "configure TPS6598x USB PD controllers"
    description = """
    Read and write TI TPS6598x USB PD controller registers.
    """

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)

        def i2c_address(arg):
            return int(arg, 0)
        parser.add_argument(
            "--i2c-address", type=i2c_address, metavar="ADDR", default=0b111000,
            help="I2C address of the controller (default: %(default)#02x)")

    async def run(self, device, args):
        i2c_iface = await super().run(device, args)
        return TPS6598xInterface(i2c_iface, self.logger, args.i2c_address)

    @classmethod
    def add_interact_arguments(cls, parser):
        def register(arg):
            return int(arg, 0)
        def hex_bytes(arg):
            return bytes.fromhex(arg)

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

        p_read_reg = p_operation.add_parser(
            "read-reg", help="read register")
        p_read_reg.add_argument(
            "address", metavar="ADDRESS", type=register,
            help="register address")

        p_read_all = p_operation.add_parser(
            "read-all", help="read all registers")

        p_write_reg = p_operation.add_parser(
            "write-reg", help="write register")
        p_write_reg.add_argument(
            "address", metavar="ADDRESS", type=register,
            help="register address")
        p_write_reg.add_argument(
            "data", metavar="DATA", type=hex_bytes,
            help="data to write, as hex bytes")

    async def interact(self, device, args, tps6598x_iface):
        if args.operation == "read-reg":
            print((await tps6598x_iface.read_reg(args.address)).hex())

        if args.operation == "read-all":
            for address in range(0x80):
                print("{:02x}: {}"
                      .format(address, (await tps6598x_iface.read_reg(address)).hex()))

        if args.operation == "write-reg":
            await tps6598x_iface.write_reg(args.address, args.data)
