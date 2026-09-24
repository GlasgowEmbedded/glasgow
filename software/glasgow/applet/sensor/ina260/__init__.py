# Ref: http://www.ti.com/lit/ds/symlink/ina260.pdf
# Accession: G00043

import asyncio

from glasgow.support import logging
from glasgow.support.data_logger import DataLogger
from glasgow.applet.interface.i2c_controller import I2CNotAcknowledged, I2CControllerInterface
from glasgow.applet import GlasgowAppletError, GlasgowAppletV2


__all__ = ["INA260Error", "INA260Interface", "I2CNotAcknowledged"]


REG_CONFIG      = 0x00 # 16-bit rw
REG_CURRENT     = 0x01 # 16-bit signed ro
REG_VOLTAGE     = 0x02 # 16-bit unsigned ro
REG_POWER       = 0x03 # 16-bit unsigned ro
REG_ALERT_MASK  = 0x06 # 16-bit rw
REG_ALERT_LIMIT = 0x07 # 16-bit rw
REG_VENDOR_ID   = 0xFE # 16-bit ro
REG_PRODUCT_ID  = 0xFF # 16-bit ro

REG_VALUE_VENDOR_ID  = 0x5449
REG_VALUE_PRODUCT_ID = 0x2270

VOLTS_FACTOR  = 0.00125
AMPERE_FACTOR = 0.00125
WATTS_FACTOR  = 0.01


class INA260Error(GlasgowAppletError):
    pass


class INA260Interface:
    def __init__(self, logger: logging.Logger, i2c_iface: I2CControllerInterface,
                 i2c_address: int = 0x40):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        self._i2c_iface   = i2c_iface
        self._i2c_address = i2c_address

    def _log(self, message, *args):
        self._logger.log(self._level, "INA260: " + message, *args)

    async def _read_reg16u(self, reg: int) -> int:
        async with self._i2c_iface.transaction():
            await self._i2c_iface.write(self._i2c_address, [reg])
            msb, lsb = await self._i2c_iface.read(self._i2c_address, 2)
        raw = (msb << 8) | lsb
        self._log("read reg=%#04x raw=%#06x", reg, raw)
        return raw

    async def _read_reg16s(self, reg: int) -> int:
        async with self._i2c_iface.transaction():
            await self._i2c_iface.write(self._i2c_address, [reg])
            msb, lsb = await self._i2c_iface.read(self._i2c_address, 2)
        raw = (msb << 8) | lsb
        if raw & (1 << 15):
            value = -((1 << 16) - raw)
        else:
            value = raw
        self._log("read reg=%#04x raw=%#06x read=%+d", reg, raw, value)
        return value

    async def identify(self):
        vendor = await self._read_reg16u(REG_VENDOR_ID)
        if vendor != REG_VALUE_VENDOR_ID:
            raise INA260Error(f"INA260: wrong vendor ID={vendor:#06x}")
        product = await self._read_reg16u(REG_PRODUCT_ID)
        if product != REG_VALUE_PRODUCT_ID:
            raise INA260Error(f"INA260: wrong product ID={product:#06x}")

    async def get_voltage(self) -> float:
        raw = await self._read_reg16u(REG_VOLTAGE)
        volts = raw * VOLTS_FACTOR
        self._log("voltage raw=%d volts=%f", raw, volts)
        return volts

    async def get_current(self) -> float:
        raw = await self._read_reg16s(REG_CURRENT)
        amps = raw * AMPERE_FACTOR
        self._log("current raw=%d amps=%+f", raw, amps)
        return amps

    async def get_power(self) -> float:
        raw = await self._read_reg16u(REG_POWER)
        watts = raw * WATTS_FACTOR
        self._log("power raw=%d watts=%f", raw, watts)
        return watts


class SensorINA260Applet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "measure voltage, current and power with TI INA260 sensors"
    description = """
    Measure voltage, current and power with TI INA260 sensors.

    Only readout is supported. Configuration cannot be changed, and alerts cannot be enabled.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "scl", default=True, required=True)
        access.add_pins_argument(parser, "sda", default=True, required=True)

        def i2c_address(arg):
            return int(arg, 0)
        parser.add_argument(
            "--i2c-address", type=i2c_address, metavar="ADDR", default=0x40,
            help="I2C address of the sensor (0x40 to 0x4F, default: %(default)#02x)")

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.i2c_iface = I2CControllerInterface(self.logger, self.assembly,
                scl=args.scl, sda=args.sda)
            self.ina260_iface = INA260Interface(self.logger, self.i2c_iface, args.i2c_address)

    async def setup(self, args):
        await self.i2c_iface.clock.set_frequency(100e3)

    @classmethod
    def add_run_arguments(cls, parser):
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

        p_measure = p_operation.add_parser(
            "measure", help="read measured values")

        p_log = p_operation.add_parser(
            "log", help="log measured values")
        p_log.add_argument(
            "-i", "--interval", metavar="TIME", type=float, required=True,
            help="sample each TIME seconds")
        DataLogger.add_subparsers(p_log)

    async def run(self, args):
        await self.ina260_iface.identify()

        if args.operation == "measure":
            volts = await self.ina260_iface.get_voltage()
            amps  = await self.ina260_iface.get_current()
            watts = await self.ina260_iface.get_power()
            print(f"bus voltage : {volts:7.03f} V")
            print(f"current     : {amps:+7.03f} A")
            print(f"power       : {watts:7.03f} W")

        if args.operation == "log":
            field_names = dict(u="u(V)", i="i(A)", p="p(W)")
            data_logger = await DataLogger(self.logger, args, field_names=field_names)
            while True:
                async def report():
                    fields = dict(u=await self.ina260_iface.get_voltage(),
                                  i=await self.ina260_iface.get_current(),
                                  p=await self.ina260_iface.get_power())
                    await data_logger.report_data(fields)
                try:
                    await asyncio.wait_for(report(), args.interval * 2)
                except (INA260Error, I2CNotAcknowledged) as error:
                    await data_logger.report_error(str(error), exception=error)
                except TimeoutError as error:
                    await data_logger.report_error("timeout", exception=error)
                await asyncio.sleep(args.interval)

    @classmethod
    def tests(cls):
        from . import test
        return test.SensorINA260AppletTestCase
