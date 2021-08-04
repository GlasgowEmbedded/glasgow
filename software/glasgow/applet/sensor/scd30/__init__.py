# Ref: https://media.digikey.com/pdf/Data%20Sheets/Sensirion%20PDFs/CD_AN_SCD30_Interface_Description_D1.pdf
# Accession: G00034

from collections import namedtuple
import argparse
import logging
import asyncio
import aiohttp
import yarl
import struct
import crcmod

from ....support.logging import dump_hex
from ....support.data_logger import DataLogger
from ...interface.i2c_initiator import I2CInitiatorApplet
from ... import *


CMD_START_MEASURE = 0x0010
CMD_STOP_MEASURE  = 0x0104
CMD_INTERVAL      = 0x4600
CMD_DATA_READY    = 0x0202
CMD_READ_MEASURE  = 0x0300
CMD_AUTO_SELF_CAL = 0x5306
CMD_FORCE_RECAL   = 0x5204
CMD_TEMP_OFFSET   = 0x5403
CMD_ALTITUDE_COMP = 0x5102
CMD_FIRMWARE_VER  = 0xD100
CMD_SOFT_RESET    = 0xD304


class SCD30Error(GlasgowAppletError):
    pass


SCD30Measurement = namedtuple("SCD30Measurement", ("co2_ppm", "temp_degC", "rh_pct"))


class SCD30I2CInterface:
    i2c_addr = 0x61

    def __init__(self, interface, logger):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

    def _log(self, message, *args):
        self._logger.log(self._level, "SCD30: " + message, *args)

    _crc = staticmethod(crcmod.mkCrcFun(0x131, initCrc=0xff, rev=False))

    async def _read_raw(self, addr, length=0):
        assert length % 2 == 0
        acked = await self.lower.write(self.i2c_addr, struct.pack(">H", addr), stop=True)
        if acked is False:
            raise SCD30Error("SCD30 did not acknowledge address write")
        crc_data = await self.lower.read(self.i2c_addr, length // 2 * 3, stop=True)
        if crc_data is None:
            raise SCD30Error("SCD30 did not acknowledge data read")
        self._log("addr=%#06x data=<%s>", addr, dump_hex(crc_data))
        data = bytearray()
        for index, (chunk, crc) in enumerate(struct.iter_unpack(">2sB", crc_data)):
            if self._crc(chunk) != crc:
                raise SCD30Error("CRC failed on word {}".format(index))
            data += chunk
        return data

    async def _write_raw(self, cmd, data=b""):
        assert len(data) % 2 == 0
        crc_data = bytearray()
        for chunk, in struct.iter_unpack(">2s", data):
            crc_data += chunk
            crc_data.append(self._crc(chunk))
        self._log("cmd=%#06x args=<%s>", cmd, dump_hex(crc_data))
        acked = await self.lower.write(self.i2c_addr, struct.pack(">H", cmd) + crc_data,
                                        stop=True)
        if acked is False:
            raise SCD30Error("SCD30 did not acknowledge command write")

    async def _read(self, addr, format):
        return struct.unpack(format, await self._read_raw(addr, struct.calcsize(format)))

    async def _write(self, cmd, format="", *args):
        await self._write_raw(cmd, struct.pack(format, *args))

    async def soft_reset(self):
        self._log("soft reset")
        await self._write(CMD_SOFT_RESET)

    async def firmware_version(self):
        major, minor = await self._read(CMD_FIRMWARE_VER, ">BB")
        self._log("firmware major=%d minor=%d", major, minor)
        return major, minor

    async def is_data_ready(self):
        ready, = await self._read(CMD_DATA_READY, ">H")
        self._log("data ready=%d", ready)
        return bool(ready)

    async def start_measurement(self, pressure_mbar=None):
        assert pressure_mbar is None or pressure_mbar in range(700, 1200)
        if pressure_mbar is None:
            self._log("start measurement")
        else:
            self._log("start measurement pressure=%d [mbar]",
                             pressure_mbar)
        await self._write(CMD_START_MEASURE, ">H", pressure_mbar or 0)

    async def stop_measurement(self):
        self._log("stop measurement")
        await self._write(CMD_STOP_MEASURE)

    async def read_measurement(self):
        co2_ppm, temp_degC, rh_pct = \
            await self._read(CMD_READ_MEASURE, ">fff")
        self._log("measured CO₂=%.2f [ppm] T=%.2f [°C] RH=%.2f [%%]", co2_ppm, temp_degC, rh_pct)
        return SCD30Measurement(co2_ppm, temp_degC, rh_pct)

    async def get_measurement_interval(self):
        interval_s, = await self._read(CMD_INTERVAL, ">H")
        self._log("measurement interval get=%d [s]", interval_s)
        return interval_s

    async def set_measurement_interval(self, interval_s):
        assert 2 <= interval_s <= 1800
        self._log("measurement interval set=%d [s]", interval_s)
        await self._write(CMD_INTERVAL, ">H", interval_s)

    async def get_auto_self_calibration(self):
        enabled, = await self._read(CMD_AUTO_SELF_CAL, ">H")
        self._log("auto calibration status=%d", enabled)
        return bool(enabled)

    async def set_auto_self_calibration(self, enabled):
        self._log("auto calibration %s", "enable" if enabled else "disable")
        await self._write(CMD_AUTO_SELF_CAL, ">H", bool(enabled))

    async def get_forced_calibration(self):
        co2_ppm, = await self._read(CMD_FORCE_RECAL, ">H")
        self._log("forced calibration get=%d [ppm]", co2_ppm)
        return co2_ppm

    async def set_forced_calibration(self, co2_ppm):
        assert 400 <= co2_ppm <= 2000
        self._log("forced calibration set=%d [ppm]", co2_ppm)
        await self._write(CMD_FORCE_RECAL, ">H", co2_ppm)

    async def get_temperature_offset(self):
        temp_degC_100ths, = await self._read(CMD_TEMP_OFFSET, ">H")
        temp_degC = temp_degC_100ths / 100
        self._log("temperature offset get=%.2f [°C]", temp_degC)
        return temp_degC

    async def set_temperature_offset(self, temp_degC):
        assert 0.0 <= temp_degC
        self._log("temperature offset set=%.2f [°C]", temp_degC)
        temp_degC_100ths = int(temp_degC * 100)
        await self._write(CMD_TEMP_OFFSET, ">H", temp_degC_100ths)

    async def get_altitude_compensation(self):
        altitude_m, = await self._read(CMD_ALTITUDE_COMP, ">H")
        self._log("altitude compensation get=%d [m]", altitude_m)
        return altitude_m

    async def set_altitude_compensation(self, altitude_m):
        self._log("altitude compensation set=%d [m]", altitude_m)
        await self._write(CMD_ALTITUDE_COMP, ">H", altitude_m)


class SensorSCD30Applet(I2CInitiatorApplet, name="sensor-scd30"):
    logger = logging.getLogger(__name__)
    help = "measure CO₂, humidity, and temperature with Sensirion SCD30 sensors"
    description = """
    Measure CO₂ concentration, humidity, and temperature using Sensirion SCD30 sensors
    connected over the I²C interface.

    NOTE: The SCD30 takes some time to start up. Run `glasgow voltage AB 3.3 --no-alert`
    or similar before attempting to interact with it.
    """

    async def run(self, device, args):
        i2c_iface = await self.run_lower(SensorSCD30Applet, device, args)
        return SCD30I2CInterface(i2c_iface, self.logger)

    @classmethod
    def add_interact_arguments(cls, parser):
        def arg_conv_range(conv, low, high):
            def arg(value):
                value = conv(value)
                if not (low <= value <= high):
                    raise argparse.ArgumentTypeError(
                        "{} is not between {} and {}".format(value, low, high))
                return value
            return arg

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

        p_calibrate = p_operation.add_parser(
            "calibrate", help="display or change calibration parameters")
        p_calibrate.add_argument(
            "--auto-calibration", action="store_true", dest="auto_calibration", default=None,
            help="enable automatic self-calibration")
        p_calibrate.add_argument(
            "--no-auto-calibration", action="store_false", dest="auto_calibration", default=None,
            help="disable automatic self-calibration")
        p_calibrate.add_argument(
            "--force-calibration", metavar="CAL", type=arg_conv_range(int, 400, 2000),
            help="force calibration at CAL ppm of CO₂ (range: 400..2000)")
        p_calibrate.add_argument(
            "--temperature-offset", metavar="OFF", type=arg_conv_range(float, 0.0, 100.0),
            help="set temperature offset to OFF °C")
        p_calibrate.add_argument(
            "--altitude-compensation", metavar="ALT", type=arg_conv_range(int, 0, 10000),
            help="set altitude compensation to ALT m above sea level (range: 0..10000)")
        p_calibrate.add_argument(
            "--measurement-interval", metavar="INTV", type=arg_conv_range(int, 2, 1800),
            help="set measurement interval to INTV s (range: 2..1800)")

        p_start = p_operation.add_parser(
            "start", help="start measurement")
        p_start.add_argument(
            "pressure_mbar", metavar="PRESSURE", nargs="?", type=arg_conv_range(int, 700, 1200),
            help="compensate for ambient pressure of PRESSURE mbar")

        p_stop = p_operation.add_parser(
            "stop", help="stop measurement")

        p_measure = p_operation.add_parser(
            "measure", help="read measured values (must start first)")

        p_log = p_operation.add_parser(
            "log", help="log measured values (must start first)")
        DataLogger.add_subparsers(p_log)

    async def interact(self, device, args, scd30):
        major, minor = await scd30.firmware_version()
        self.logger.info("SCD30 firmware v%d.%d", major, minor)

        if args.operation == "calibrate":
            if args.auto_calibration is not None:
                await scd30.set_auto_self_calibration(args.auto_calibration)
            if args.force_calibration is not None:
                await scd30.set_forced_calibration(args.force_calibration)
            if args.temperature_offset is not None:
                await scd30.set_temperature_offset(args.temperature_offset)
            if args.altitude_compensation is not None:
                await scd30.set_altitude_compensation(args.altitude_compensation)
            if args.measurement_interval is not None:
                await scd30.set_measurement_interval(args.measurement_interval)

            auto_calibration      = await scd30.get_auto_self_calibration()
            force_calibration     = await scd30.get_forced_calibration()
            temperature_offset    = await scd30.get_temperature_offset()
            altitude_compensation = await scd30.get_altitude_compensation()
            measurement_interval  = await scd30.get_measurement_interval()
            print("auto-calibration      : {}".format("on" if auto_calibration else "off"))
            print("forced calibration    : {} ppm (last)".format(force_calibration))
            print("temperature offset    : {} °C".format(temperature_offset))
            print("altitude compensation : {} m".format(altitude_compensation))
            print("measurement interval  : {} s".format(measurement_interval))

        if args.operation == "start":
            await scd30.start_measurement(args.pressure_mbar)

        if args.operation == "stop":
            await scd30.stop_measurement()

        if args.operation == "measure":
            while not await scd30.is_data_ready():
                await asyncio.sleep(1.0)

            sample = await scd30.read_measurement()
            print("CO₂ concentration : {:.0f} ppm".format(sample.co2_ppm))
            print("temperature       : {:.2f} °C".format(sample.temp_degC))
            print("relative humidity : {:.0f} %".format(sample.rh_pct))

        if args.operation == "log":
            field_names = dict(co2="CO₂(ppm)", t="T(°C)", rh="RH(%)")
            data_logger = await DataLogger(self.logger, args, field_names=field_names)
            meas_interval = await scd30.get_measurement_interval()
            while True:
                async def report():
                    while not await scd30.is_data_ready():
                        await asyncio.sleep(meas_interval / 2)

                    sample = await scd30.read_measurement()
                    fields = dict(co2=sample.co2_ppm, t=sample.temp_degC, rh=sample.rh_pct)
                    await data_logger.report_data(fields)
                try:
                    await asyncio.wait_for(report(), meas_interval * 3)
                except SCD30Error as error:
                    await data_logger.report_error(str(error), exception=error)
                    await scd30.lower.reset()
                    await asyncio.sleep(meas_interval)
                except asyncio.TimeoutError as error:
                    await data_logger.report_error("timeout", exception=error)
                    await scd30.lower.reset()
