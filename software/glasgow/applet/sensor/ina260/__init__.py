# Ref: http://www.ti.com/lit/ds/symlink/ina260.pdf
# Accession: G00043

import logging
import asyncio

from ....support.data_logger import DataLogger
from ... import *
from ...interface.i2c_initiator import I2CInitiatorApplet


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


class INA260I2CInterface:
    def __init__(self, interface, logger, i2c_address):
        self.lower     = interface
        self._i2c_addr = i2c_address
        self._logger   = logger
        self._level    = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

    async def _read_reg16u(self, reg):
        await self.lower.write(self._i2c_addr, [reg])
        result = await self.lower.read(self._i2c_addr, 2)
        if result is None:
            raise INA260Error("INA260 did not acknowledge I2C read at address {:#07b}"
                              .format(self._i2c_addr))
        msb, lsb = result
        raw = (msb << 8) | lsb
        self._logger.log(self._level, "INA260: read reg=%#04x raw=%#06x", reg, raw)
        return raw

    async def _read_reg16s(self, reg):
        await self.lower.write(self._i2c_addr, [reg])
        result = await self.lower.read(self._i2c_addr, 2)
        if result is None:
            raise INA260Error("INA260 did not acknowledge I2C read at address {:#07b}"
                              .format(self._i2c_addr))
        msb, lsb = result
        raw = (msb << 8) | lsb
        if raw & (1 << 15):
            value = -((1 << 16) - raw)
        else:
            value = raw
        self._logger.log(self._level, "INA260: read reg=%#04x raw=%#06x read=%+d", reg, raw, value)
        return value

    async def identify(self):
        vendor = await self._read_reg16u(REG_VENDOR_ID)
        if vendor != REG_VALUE_VENDOR_ID:
            raise INA260Error("INA260: wrong vendor ID=%#04x" % vendor)
        product = await self._read_reg16u(REG_PRODUCT_ID)
        if product != REG_VALUE_PRODUCT_ID:
            raise INA260Error("INA260: wrong product ID=%#04x" % product)

    async def get_voltage(self):
        raw = await self._read_reg16u(REG_VOLTAGE)
        volts = raw * VOLTS_FACTOR
        self._logger.log(self._level, "INA260: voltage raw=%d volts=%f", raw, volts)
        return volts

    async def get_current(self):
        raw = await self._read_reg16s(REG_CURRENT)
        amps = raw * AMPERE_FACTOR
        self._logger.log(self._level, "INA260: current raw=%d amps=%+f", raw, amps)
        return amps

    async def get_power(self):
        raw = await self._read_reg16u(REG_POWER)
        watts = raw * WATTS_FACTOR
        self._logger.log(self._level, "INA260: power raw=%d watts=%f", raw, watts)
        return watts


class SensorINA260Applet(I2CInitiatorApplet, name="sensor-ina260"):
    logger = logging.getLogger(__name__)
    help = "measure voltage, current and power with TI INA260 sensors"
    description = """
    Measure voltage, current and power with TI INA260 sensors.

    Only readout is supported. Configuration cannot be changed, and alerts cannot be enabled.
    """

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)

        def i2c_address(arg):
            return int(arg, 0)
        parser.add_argument(
            "--i2c-address", type=i2c_address, metavar="ADDR", default=0x40,
            help="I2C address of the sensor (0x40 to 0x4F, default: %(default)#02x)")

    async def run(self, device, args):
        i2c_iface = await self.run_lower(SensorINA260Applet, device, args)
        return INA260I2CInterface(i2c_iface, self.logger, args.i2c_address)

    @classmethod
    def add_interact_arguments(cls, parser):
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

        p_measure = p_operation.add_parser(
            "measure", help="read measured values")

        p_log = p_operation.add_parser(
            "log", help="log measured values")
        p_log.add_argument(
            "-i", "--interval", metavar="TIME", type=float, required=True,
            help="sample each TIME seconds")
        DataLogger.add_subparsers(p_log)

    async def interact(self, device, args, ina260):
        await ina260.identify()

        if args.operation == "measure":
            volts = await ina260.get_voltage()
            amps  = await ina260.get_current()
            watts = await ina260.get_power()
            print("bus voltage : {:7.03f} V".format(volts))
            print("current     : {:+7.03f} A".format(amps))
            print("power       : {:7.03f} W".format(watts))

        if args.operation == "log":
            field_names = dict(u="u(V)", i="i(A)", p="p(W)")
            data_logger = await DataLogger(self.logger, args, field_names=field_names)
            while True:
                async def report():
                    fields = dict(u=await ina260.get_voltage(),
                                  i=await ina260.get_current(),
                                  p=await ina260.get_power())
                    await data_logger.report_data(fields)
                try:
                    await asyncio.wait_for(report(), args.interval * 2)
                except INA260Error as error:
                    await data_logger.report_error(str(error), exception=error)
                    await ina260.lower.reset()
                except asyncio.TimeoutError as error:
                    await data_logger.report_error("timeout", exception=error)
                    await ina260.lower.reset()
                await asyncio.sleep(args.interval)
