# Ref: https://media.digikey.com/pdf/Data%20Sheets/Sensirion%20PDFs/CD_AN_SCD30_Interface_Description_D1.pdf
# Accession: G00034

from dataclasses import dataclass
import argparse
import logging
import asyncio
import struct
import enum

from amaranth.lib.crc.catalog import CRC8_NRSC_5

from glasgow.support.logging import dump_hex
from glasgow.support.data_logger import DataLogger
from glasgow.applet.interface.i2c_controller import I2CControllerInterface
from glasgow.applet import GlasgowAppletError, GlasgowAppletV2


__all__ = ["SCD30Error", "SCD30Measurement", "SCD30I2CInterface"]


class SCD30Error(GlasgowAppletError):
    pass


class SCD30Command(enum.Enum):
    START_MEASURE = 0x0010
    STOP_MEASURE  = 0x0104
    INTERVAL      = 0x4600
    DATA_READY    = 0x0202
    READ_MEASURE  = 0x0300
    AUTO_SELF_CAL = 0x5306
    FORCE_RECAL   = 0x5204
    TEMP_OFFSET   = 0x5403
    ALTITUDE_COMP = 0x5102
    FIRMWARE_VER  = 0xD100
    SOFT_RESET    = 0xD304


@dataclass
class SCD30Measurement:
    co2_ppm: float
    temp_degC: float
    rh_pct: float


class SCD30I2CInterface:
    _i2c_address = 0x61

    def __init__(self, logger: logging.Logger, i2c_iface: I2CControllerInterface):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        self._i2c_iface = i2c_iface

    def _log(self, message, *args):
        self._logger.log(self._level, "SCD30: " + message, *args)

    _crc = staticmethod(CRC8_NRSC_5(data_width=8).compute)

    async def _read_raw(self, address: int, length: int = 0) -> bytearray:
        assert length % 2 == 0
        await self._i2c_iface.write(self._i2c_address, struct.pack(">H", address))
        crc_data = await self._i2c_iface.read(self._i2c_address, length // 2 * 3)
        self._log("read addr=%#06x data=<%s>", address, dump_hex(crc_data))
        data = bytearray()
        for index, (chunk, crc) in enumerate(struct.iter_unpack(">2sB", crc_data)):
            if self._crc(chunk) != crc:
                raise SCD30Error(f"CRC failed on word {index}")
            data += chunk
        return data

    async def _write_raw(self, address: int, data: bytes = b""):
        assert len(data) % 2 == 0
        crc_data = bytearray()
        for chunk, in struct.iter_unpack(">2s", data):
            crc_data += chunk
            crc_data.append(self._crc(chunk))
        self._log("write addr=%#06x args=<%s>", address, dump_hex(crc_data))
        await self._i2c_iface.write(self._i2c_address,
            struct.pack(">H", address) + crc_data)

    async def _read(self, cmd: SCD30Command, format: str):
        return struct.unpack(format, await self._read_raw(cmd.value, struct.calcsize(format)))

    async def _write(self, cmd: SCD30Command, format: str = "", *args):
        await self._write_raw(cmd.value, struct.pack(format, *args))

    async def soft_reset(self):
        self._log("soft reset")
        await self._write(SCD30Command.SOFT_RESET)

    async def firmware_version(self) -> tuple[int, int]:
        major, minor = await self._read(SCD30Command.FIRMWARE_VER, ">BB")
        self._log("firmware major=%d minor=%d", major, minor)
        return major, minor

    async def is_data_ready(self) -> bool:
        ready, = await self._read(SCD30Command.DATA_READY, ">H")
        self._log("data ready=%d", ready)
        return bool(ready)

    async def start_measurement(self, pressure_mbar: int | None = None):
        assert pressure_mbar is None or pressure_mbar in range(700, 1200)
        if pressure_mbar is None:
            self._log("start measurement")
        else:
            self._log("start measurement pressure=%d [mbar]",
                             pressure_mbar)
        await self._write(SCD30Command.START_MEASURE, ">H", pressure_mbar or 0)

    async def stop_measurement(self):
        self._log("stop measurement")
        await self._write(SCD30Command.STOP_MEASURE)

    async def read_measurement(self) -> SCD30Measurement:
        co2_ppm, temp_degC, rh_pct = \
            await self._read(SCD30Command.READ_MEASURE, ">fff")
        self._log("measured CO₂=%.2f [ppm] T=%.2f [°C] RH=%.2f [%%]", co2_ppm, temp_degC, rh_pct)
        return SCD30Measurement(co2_ppm, temp_degC, rh_pct)

    async def get_measurement_interval(self) -> int:
        interval_s, = await self._read(SCD30Command.INTERVAL, ">H")
        self._log("measurement interval get=%d [s]", interval_s)
        return interval_s

    async def set_measurement_interval(self, interval_s: int):
        assert 2 <= interval_s <= 1800
        self._log("measurement interval set=%d [s]", interval_s)
        await self._write(SCD30Command.INTERVAL, ">H", interval_s)

    async def get_auto_self_calibration(self) -> bool:
        enabled, = await self._read(SCD30Command.AUTO_SELF_CAL, ">H")
        self._log("auto calibration status=%d", enabled)
        return bool(enabled)

    async def set_auto_self_calibration(self, enabled: bool):
        self._log("auto calibration %s", "enable" if enabled else "disable")
        await self._write(SCD30Command.AUTO_SELF_CAL, ">H", bool(enabled))

    async def get_forced_calibration(self) -> int:
        co2_ppm, = await self._read(SCD30Command.FORCE_RECAL, ">H")
        self._log("forced calibration get=%d [ppm]", co2_ppm)
        return co2_ppm

    async def set_forced_calibration(self, co2_ppm: int):
        assert 400 <= co2_ppm <= 2000
        self._log("forced calibration set=%d [ppm]", co2_ppm)
        await self._write(SCD30Command.FORCE_RECAL, ">H", co2_ppm)

    async def get_temperature_offset(self) -> float:
        temp_degC_100ths, = await self._read(SCD30Command.TEMP_OFFSET, ">H")
        temp_degC = temp_degC_100ths / 100
        self._log("temperature offset get=%.2f [°C]", temp_degC)
        return temp_degC

    async def set_temperature_offset(self, temp_degC: float):
        assert 0.0 <= temp_degC
        self._log("temperature offset set=%.2f [°C]", temp_degC)
        temp_degC_100ths = int(temp_degC * 100)
        await self._write(SCD30Command.TEMP_OFFSET, ">H", temp_degC_100ths)

    async def get_altitude_compensation(self) -> int:
        altitude_m, = await self._read(SCD30Command.ALTITUDE_COMP, ">H")
        self._log("altitude compensation get=%d [m]", altitude_m)
        return altitude_m

    async def set_altitude_compensation(self, altitude_m: int):
        self._log("altitude compensation set=%d [m]", altitude_m)
        await self._write(SCD30Command.ALTITUDE_COMP, ">H", altitude_m)


class SensorSCD30Applet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "measure CO₂, humidity, and temperature with Sensirion SCD30 sensors"
    description = """
    Measure CO₂ concentration, humidity, and temperature using Sensirion SCD30 sensors connected
    over the I²C interface.

    NOTE: The SCD30 takes some time to start up. Run `glasgow voltage AB 3.3` or similar before
    attempting to interact with it.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "scl", default=True, required=True)
        access.add_pins_argument(parser, "sda", default=True, required=True)

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.i2c_iface = I2CControllerInterface(self.logger, self.assembly,
                scl=args.scl, sda=args.sda)
            self.scd30_iface = SCD30I2CInterface(self.logger, self.i2c_iface)

    async def setup(self, args):
        # §1.1 I2C Protocol
        # Maximal I2C speed is 100 kHz and the master has to support clock stretching.
        # Sensirion recommends to operate the SCD30 at a baud rate of 50 kHz or smaller.
        await self.i2c_iface.clock.set_frequency(50e3)

    @classmethod
    def add_run_arguments(cls, parser):
        def arg_conv_range(conv, low, high):
            def arg(value):
                value = conv(value)
                if not (low <= value <= high):
                    raise argparse.ArgumentTypeError(
                        f"{value} is not between {low} and {high}")
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

    async def run(self, args):
        major, minor = await self.scd30_iface.firmware_version()
        self.logger.info("SCD30 firmware v%d.%d", major, minor)

        if args.operation == "calibrate":
            if args.auto_calibration is not None:
                await self.scd30_iface.set_auto_self_calibration(args.auto_calibration)
            if args.force_calibration is not None:
                await self.scd30_iface.set_forced_calibration(args.force_calibration)
            if args.temperature_offset is not None:
                await self.scd30_iface.set_temperature_offset(args.temperature_offset)
            if args.altitude_compensation is not None:
                await self.scd30_iface.set_altitude_compensation(args.altitude_compensation)
            if args.measurement_interval is not None:
                await self.scd30_iface.set_measurement_interval(args.measurement_interval)

            auto_calibration      = await self.scd30_iface.get_auto_self_calibration()
            force_calibration     = await self.scd30_iface.get_forced_calibration()
            temperature_offset    = await self.scd30_iface.get_temperature_offset()
            altitude_compensation = await self.scd30_iface.get_altitude_compensation()
            measurement_interval  = await self.scd30_iface.get_measurement_interval()
            print(f"auto-calibration      : {'on' if auto_calibration else 'off'}")
            print(f"forced calibration    : {force_calibration} ppm (last)")
            print(f"temperature offset    : {temperature_offset} °C")
            print(f"altitude compensation : {altitude_compensation} m")
            print(f"measurement interval  : {measurement_interval} s")

        if args.operation == "start":
            await self.scd30_iface.start_measurement(args.pressure_mbar)

        if args.operation == "stop":
            await self.scd30_iface.stop_measurement()

        if args.operation == "measure":
            while not await self.scd30_iface.is_data_ready():
                await asyncio.sleep(1.0)

            sample = await self.scd30_iface.read_measurement()
            print(f"CO₂ concentration : {sample.co2_ppm:.0f} ppm")
            print(f"temperature       : {sample.temp_degC:.2f} °C")
            print(f"relative humidity : {sample.rh_pct:.0f} %")

        if args.operation == "log":
            field_names = dict(co2="CO₂(ppm)", t="T(°C)", rh="RH(%)")
            data_logger = await DataLogger(self.logger, args, field_names=field_names)
            meas_interval = await self.scd30_iface.get_measurement_interval()
            while True:
                async def report():
                    while not await self.scd30_iface.is_data_ready():
                        await asyncio.sleep(meas_interval / 2)

                    sample = await self.scd30_iface.read_measurement()
                    fields = dict(co2=sample.co2_ppm, t=sample.temp_degC, rh=sample.rh_pct)
                    await data_logger.report_data(fields)
                try:
                    await asyncio.wait_for(report(), meas_interval * 3)
                except SCD30Error as error:
                    await data_logger.report_error(str(error), exception=error)
                    await self.scd30_iface.lower.reset()
                    await asyncio.sleep(meas_interval)
                except TimeoutError as error:
                    await data_logger.report_error("timeout", exception=error)
                    await self.scd30_iface.lower.reset()

    @classmethod
    def tests(cls):
        from . import test
        return test.SensorSCD30AppletTestCase
