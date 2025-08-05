# Ref: https://developer.sensirion.com/fileadmin/user_upload/customers/sensirion/Dokumente/15_Environmental_Sensor_Node/Datasheets/Sensirion_Environmental_Sensor_Node_SEN5x_Datasheet.pdf
# Accession: G00083

from typing import Optional
from dataclasses import asdict, dataclass
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


__all__ = ["SEN5xError", "SEN5xMeasurement", "SEN5xI2CInterface"]


class SEN5xError(GlasgowAppletError):
    pass


class SEN5xCommand(enum.Enum):
    START_MEASURE = 0x0021
    STOP_MEASURE  = 0x0104
    DATA_READY    = 0x0202
    READ_MEASURE  = 0x03C4
    PRODUCT_NAME  = 0xD014
    SERIAL_NUM    = 0xD033
    FIRMWARE_VER  = 0xD100
    SOFT_RESET    = 0xD304


@dataclass
class SEN5xMeasurement:
    pm1_0: float
    pm2_5: float
    pm4_0: float
    pm10: float
    rh_pct: float
    temp_degC: float
    voc_index: float
    nox_index: float


class SEN5xI2CInterface:
    _i2c_address = 0x69

    def __init__(self, logger: logging.Logger, i2c_iface: I2CControllerInterface):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        self._i2c_iface = i2c_iface

    def _log(self, message, *args):
        self._logger.log(self._level, "SEN5x: " + message, *args)

    _crc = staticmethod(CRC8_NRSC_5(data_width=8).compute)

    async def _read_raw(self, address: int, length: int = 0,
                        delay_seconds: Optional[float] = None) -> bytearray:
        assert length % 2 == 0
        await self._i2c_iface.write(self._i2c_address, struct.pack(">H", address))
        if delay_seconds is not None:
            await asyncio.sleep(delay_seconds)
        crc_data = await self._i2c_iface.read(self._i2c_address, length // 2 * 3)
        self._log("addr=%#06x data=<%s>", address, dump_hex(crc_data))
        data = bytearray()
        for index, (chunk, crc) in enumerate(struct.iter_unpack(">2sB", crc_data)):
            if self._crc(chunk) != crc:
                raise SEN5xError(f"CRC failed on word {index}")
            data += chunk
        return data

    async def _write_raw(self, address: int, data: bytes = b""):
        assert len(data) % 2 == 0
        crc_data = bytearray()
        for chunk, in struct.iter_unpack(">2s", data):
            crc_data += chunk
            crc_data.append(self._crc(chunk))
        self._log("cmd=%#06x args=<%s>", address, dump_hex(crc_data))
        await self._i2c_iface.write(self._i2c_address, struct.pack(">H", address) + crc_data)

    async def _read(self, cmd: SEN5xCommand, format: str, delay_seconds: Optional[float] = None):
        return struct.unpack(format,
            await self._read_raw(cmd.value, struct.calcsize(format), delay_seconds))

    async def _write(self, cmd: SEN5xCommand, format: str = "", *args):
        await self._write_raw(cmd.value, struct.pack(format, *args))

    async def soft_reset(self):
        self._log("soft reset")
        await self._write(SEN5xCommand.SOFT_RESET)

    async def product_name(self) -> str:
        name, = await self._read(SEN5xCommand.PRODUCT_NAME, ">32s", delay_seconds=20e-3)
        self._log("product name=%s", name)
        return name.rstrip(b"\x00").decode("ascii")

    async def serial_number(self) -> str:
        serial, = await self._read(SEN5xCommand.SERIAL_NUM, ">32s", delay_seconds=20e-3)
        self._log("serial number=%s", serial)
        return serial.rstrip(b"\x00").decode("ascii")

    async def firmware_version(self) -> int:
        version, reserved = await self._read(SEN5xCommand.FIRMWARE_VER, ">BB", delay_seconds=20e-3)
        self._log("firmware version=%d reserved=%d", version, reserved)
        return version

    async def is_data_ready(self) -> bool:
        ready, = await self._read(SEN5xCommand.DATA_READY, ">H", delay_seconds=20e-3)
        self._log("data ready=%d", ready)
        return bool(ready)

    async def start_measurement(self):
        self._log("start measurement")
        await self._write(SEN5xCommand.START_MEASURE)

    async def stop_measurement(self):
        self._log("stop measurement")
        await self._write(SEN5xCommand.STOP_MEASURE)

    async def read_measurement(self):
        measurements = await self._read(SEN5xCommand.READ_MEASURE, ">HHHHhhhh", delay_seconds=20e-3)
        scale_factors = [10, 10, 10, 10, 100, 200, 10, 10]
        measurements = [a / float(b) for a, b in zip(measurements, scale_factors)]
        (pm1_0, pm2_5, pm4_0, pm10, rh_pct, temp_degC, voc_index, nox_index) = measurements
        self._log("measured PM1.0=%.1f [µg/m³] PM2.5=%.1f [µg/m³] PM4.0%.1f [µg/m³] "
                  "PM10=%.1f [µg/m³] RH=%.2f [%%] T=%.2f [°C] VOC=%.1f NOx=%.1f",
                  pm1_0, pm2_5, pm4_0, pm10, rh_pct, temp_degC, voc_index, nox_index)
        return SEN5xMeasurement(pm1_0, pm2_5, pm4_0, pm10, rh_pct, temp_degC, voc_index, nox_index)


class SensorSEN5xApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "measure PM, NOx, VOC, humidity, and temperature with Sensirion SEN5x sensors"
    description = """
    Measure PM, NOx, VOC, humidity, and temperature using Sensirion SEN5x sensors connected over
    the I²C interface.

    NOTE: The SEL pin must be connected to ground before startup for the SEN5x to enable the I2C
    interface.
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
            self.sen5x_iface = SEN5xI2CInterface(self.logger, self.i2c_iface)

    async def setup(self, args):
        await self.i2c_iface.clock.set_frequency(100e3)

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

        p_start = p_operation.add_parser(
            "start", help="start measurement")

        p_stop = p_operation.add_parser(
            "stop", help="stop measurement")

        p_measure = p_operation.add_parser(
            "measure", help="read measured values (must start first)")

        p_log = p_operation.add_parser(
            "log", help="log measured values (must start first)")
        DataLogger.add_subparsers(p_log)

    async def run(self, args):
        product_name = await self.sen5x_iface.product_name()
        serial = await self.sen5x_iface.serial_number()
        version = await self.sen5x_iface.firmware_version()
        self.logger.info("SEN5x: %s serial %s firmware v%d", product_name, serial, version)

        if args.operation == "start":
            await self.sen5x_iface.start_measurement()

        if args.operation == "stop":
            await self.sen5x_iface.stop_measurement()

        if args.operation == "measure":
            while not await self.sen5x_iface.is_data_ready():
                await asyncio.sleep(1.0)

            sample = await self.sen5x_iface.read_measurement()
            print(f"PM1.0 concentration : {sample.pm1_0:.1f} µg/m³")
            print(f"PM2.5 concentration : {sample.pm2_5:.1f} µg/m³")
            print(f"PM4.0 concentration : {sample.pm4_0:.1f} µg/m³")
            print(f"PM10  concentration : {sample.pm10:.1f} µg/m³")
            print(f"relative humidity   : {sample.rh_pct:.2f} %")
            print(f"temperature         : {sample.temp_degC:.2f} °C")
            print(f"VOC index           : {sample.voc_index:.1f}")
            print(f"NOx index           : {sample.nox_index:.1f}")

        if args.operation == "log":
            field_names = dict(
                pm1_0="PM1.0(µg/m³)",
                pm2_5="PM2.5(µg/m³)",
                pm4_0="PM4.0(µg/m³)",
                pm10="PM10(µg/m³)",
                rh_pct="RH(%)",
                temp_degC="T(°C)",
                voc_index="VOC",
                nox_index="NOx"
            )
            data_logger = await DataLogger(self.logger, args, field_names=field_names)
            meas_interval = 1.0
            while True:
                async def report():
                    while not await self.sen5x_iface.is_data_ready():
                        await asyncio.sleep(meas_interval / 2)

                    sample = await self.sen5x_iface.read_measurement()
                    fields = asdict(sample)
                    await data_logger.report_data(fields)
                try:
                    await asyncio.wait_for(report(), meas_interval * 3)
                except SEN5xError as error:
                    await data_logger.report_error(str(error), exception=error)
                    await self.sen5x_iface.lower.reset()
                    await asyncio.sleep(meas_interval)
                except asyncio.TimeoutError as error:
                    await data_logger.report_error("timeout", exception=error)
                    await self.sen5x_iface.lower.reset()

    @classmethod
    def tests(cls):
        from . import test
        return test.SensorSEN5xAppletTestCase
