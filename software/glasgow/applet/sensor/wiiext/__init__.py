import asyncio
import logging

from glasgow.applet import GlasgowAppletV2
from glasgow.applet.interface.i2c_controller import I2CNotAcknowledged, I2CControllerInterface

# TODO


class Device:
    """Extension device specific driver."""

    def __init__(self, wiiext_iface):
        self.iface = wiiext_iface

    async def read_report(self):
        pass


class Nunchuk(Device):
    name = "Nunchuk"

    async def read_report(self):
        data = await self.iface.read(0, 6)
        bc = (data[5] >> 1) & 1
        bz = (data[5] >> 0) & 1
        return {
                "sx": data[0],
                "sy": data[1],
                "ax": data[2] << 2 | (data[5] >> 2) & 3,
                "ay": data[3] << 2 | (data[5] >> 4) & 3,
                "az": data[4] << 2 | (data[5] >> 6) & 3,
                "bc": bc ^ 1,
                "bz": bz ^ 1,
        }


class DrawingTablet(Device):
    async def read_report(self):
        data = await self.iface.read(0, 6)
        bl = (data[5] & 0x02) >> 1
        bu = (data[5] & 0x01)
        return {
                "x": data[0] | (data[2] & 0x0f) << 8,
                "y": data[1] | (data[2] & 0xf0) << 4,
                "p": data[3] | (data[5] & 0x04) << 6,
                "bl": bl ^ 1,
                "bu": bu ^ 1,
        }


class UDraw(DrawingTablet):
    name = "uDraw tablet"


class Drawsome(DrawingTablet):
    name = "Drawsome tablet"


DEVICES = {
        "0000 A420 0000": Nunchuk,
        "FF00 A420 0112": UDraw,
        "FF00 A420 0013": Drawsome,
}


def get_device_class(idcode):
    """Given an idcode, return the appropriate device."""
    if idcode in DEVICES:
        return DEVICES[idcode]
    return None


class WiiExtInterface:
    def __init__(self, logger: logging.Logger, i2c_iface: I2CControllerInterface,
                 i2c_address: int = 0x52):
        self._logger   = logger
        self._level    = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        self._i2c_iface   = i2c_iface
        self._i2c_address = i2c_address

        self.device   = None

    def _log(self, message, *args):
        self._logger.log(self._level, "Wii Ext: " + message, *args)

    async def read(self, address: int, count: int | None = None) -> int | bytes:
        """Read a register or several consecutive registers starting at :py:`address`.

        Returns an :class:`int` if :py:`count is None`, and :class:`bytes` otherwise.

        Raises
        ------
        I2CNotAcknowledged
            If communication fails.
        """
        async with self._i2c_iface.transaction():
            await self._i2c_iface.write(self._i2c_address, [address])
            await asyncio.sleep(200e-6) # 200 µs
            values = await self._i2c_iface.read(self._i2c_address, 1 if count is None else count)
            await asyncio.sleep(200e-6) # 200 µs
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

    async def identify(self):
        """Reset and identify the connected extension."""
        await self.write(0xf0, 0x55)
        await asyncio.sleep(0.020)
        await self.write(0xfb, 0x00)
        await asyncio.sleep(0.020)

        i = (await self.read(0xfa, 6)).hex().upper()
        self.idcode = i[0:4]+" "+i[4:8]+" "+i[8:12]
        if c := get_device_class(self.idcode):
            self.device = c(self)
        else:
            self.device = None
        return self.idcode, self.device.name if self.device else "unknown"

    async def read_report(self):
        if self.device:
            return await self.device.read_report()
        return None


class SensorWiiExtApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "Get inputs from Wii extensions (Nunchuk etc.)"
    description = """
    The Wii Extension bus is located at the bottom end of a Nintendo Wii Remote
    (Wiimote). Various extensions can be connected, most notably the Nunchuk and
    the Classic Controller.

    ::

        .-----.             .-----.
        |     |             |     |
        |     2------4------6     |
        |    SCL    N/C    GND    |
        |                         |
        |    3.3V  Detect  SDA    |
        '-----1------3------5-----'

    The bus is a 400 kHz I²C bus and extensions respond to address 0x52, with the
    exception of the Wii Motion Plus adapter, which can be inserted between the
    Wiimote and another extension. The Wii Motion Plus may also respond to
    address 0x53.

    The host enumerates an extension by reading the ID code, after sending the
    initialization sequence. It can then read input reports, but their precise
    layout and meaning depends on the kind of extension.

    I²C transfers read/write registers of the extension:

      - write(0x52) <register> <value>
      - write(0x52) <register> read(0x52) <value> (up to 6 bytes)

    The protocol also supports encryption, which is optional and can be ignored.

    See also: https://wiibrew.org/wiki/Wiimote/Extension_Controllers
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "scl", default=True, required=True)
        access.add_pins_argument(parser, "sda", default=True, required=True)

        def i2c_address(arg):
            return int(arg, 0)
        parser.add_argument(
            "--i2c-address", type=i2c_address, metavar="ADDR", default=0x52,
            help="I2C address of the controller (default: %(default)#04x)")

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.i2c_iface = I2CControllerInterface(self.logger, self.assembly,
                scl=args.scl, sda=args.sda)
            self.wiiext_iface = WiiExtInterface(self.logger, self.i2c_iface, args.i2c_address)

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

        p_identify = p_operation.add_parser(
            "identify", help="identify connected extension")

        p_watch = p_operation.add_parser(
            "watch", help="watch input data")

    async def run(self, args):
        if args.operation == "identify":
            idcode, name = await self.wiiext_iface.identify()
            self.logger.info(f"Detected {idcode} ({name})")

        elif args.operation == "watch":
            while True:
                try:
                    idcode, name = await self.wiiext_iface.identify()
                    self.logger.info(f"Detected {idcode} ({name})")

                    while self.device:
                        await asyncio.sleep(0.1)
                        if report := await self.wiiext_iface.read_report():
                            self.logger.info(report)
                        else:
                            break
                except I2CNotAcknowledged as e:
                    print(e)

                await asyncio.sleep(0.5)
