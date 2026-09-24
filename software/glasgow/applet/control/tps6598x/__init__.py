from glasgow.support import logging
from glasgow.applet.interface.i2c_controller import I2CNotAcknowledged, I2CControllerInterface
from glasgow.applet import GlasgowAppletV2


__all__ = ["TPS6598xInterface", "I2CNotAcknowledged"]


class TPS6598xInterface:
    def __init__(self, logger: logging.Logger, i2c_iface: I2CControllerInterface,
                 i2c_address: int = 0x38):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        self._i2c_iface   = i2c_iface
        self._i2c_address = i2c_address

    def _log(self, message, *args):
        self._logger.log(self._level, "TPS6598x: " + message, *args)

    async def read_reg(self, address: int) -> bytes:
        async with self._i2c_iface.transaction():
            await self._i2c_iface.write(self._i2c_address, [address])
            size, = await self._i2c_iface.read(self._i2c_address, 1)
        self._log("reg=%#04x size=%#04x", address, size)

        async with self._i2c_iface.transaction():
            await self._i2c_iface.write(self._i2c_address, [address])
            data = (await self._i2c_iface.read(self._i2c_address, 1 + size))[1:]
        self._log("read=<%s>", data.hex())

        return data

    async def write_reg(self, address: int, data: bytes):
        data = bytes(data)
        self._log("reg=%#04x write=<%s>", address, data.hex())
        await self._i2c_iface.write(self._i2c_address, [address, len(data), *data])


class ControlTPS6598xApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "configure TPS6598x USB PD controllers"
    description = """
    Read and write TI TPS6598x USB PD controller registers.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "scl", default=True, required=True)
        access.add_pins_argument(parser, "sda", default=True, required=True)

        def i2c_address(arg):
            return int(arg, 0)
        parser.add_argument(
            "--i2c-address", type=i2c_address, metavar="ADDR", default=0x38,
            help="I2C address of the controller (default: %(default)#02x)")

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.i2c_iface = I2CControllerInterface(self.logger, self.assembly,
                scl=args.scl, sda=args.sda)
            self.tps6598x_iface = TPS6598xInterface(self.logger, self.i2c_iface, args.i2c_address)

    async def setup(self, args):
        await self.i2c_iface.clock.set_frequency(100e3)

    @classmethod
    def add_run_arguments(cls, parser):
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

    async def run(self, args):
        if args.operation == "read-reg":
            print((await self.tps6598x_iface.read_reg(args.address)).hex())

        if args.operation == "read-all":
            for address in range(0x80):
                print(f"{address:02x}: {(await self.tps6598x_iface.read_reg(address)).hex()}")

        if args.operation == "write-reg":
            await self.tps6598x_iface.write_reg(args.address, args.data)

    @classmethod
    def tests(cls):
        from . import test
        return test.ControlTPS6598xAppletTestCase
