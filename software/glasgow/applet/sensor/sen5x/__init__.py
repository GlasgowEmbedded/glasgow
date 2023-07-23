# Ref: https://developer.sensirion.com/fileadmin/user_upload/customers/sensirion/Dokumente/15_Environmental_Sensor_Node/Datasheets/Sensirion_Environmental_Sensor_Node_SEN5x_Datasheet.pdf
# Accession: G00083

from collections import namedtuple
import argparse
import logging
import asyncio
import struct
from amaranth.lib.crc.catalog import CRC8_NRSC_5

from ....support.logging import dump_hex
from ....support.data_logger import DataLogger
from ...interface.i2c_initiator import I2CInitiatorApplet
from ... import *


CMD_START_MEASURE = 0x0021
CMD_STOP_MEASURE  = 0x0104
CMD_DATA_READY    = 0x0202
CMD_READ_MEASURE  = 0x03C4
CMD_PRODUCT_NAME  = 0xD014
CMD_SERIAL_NUM    = 0xD033
CMD_FIRMWARE_VER  = 0xD100
CMD_SOFT_RESET    = 0xD304


class SEN5xError(GlasgowAppletError):
    pass


SEN5xMeasurement = namedtuple("SEN5xMeasurement", ("pm1_0", "pm2_5", "pm4_0", "pm10", "rh_pct", "temp_degC", "voc_index", "nox_index"))


class SEN5xI2CInterface:
    i2c_addr = 0x69

    def __init__(self, interface, logger):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

    def _log(self, message, *args):
        self._logger.log(self._level, "SEN5x: " + message, *args)

    _crc = staticmethod(CRC8_NRSC_5(data_width=8).compute)

    async def _read_raw(self, addr, length=0, delay_seconds=None):
        assert length % 2 == 0
        acked = await self.lower.write(self.i2c_addr, struct.pack(">H", addr), stop=True)
        if acked is False:
            raise SEN5xError("SEN5x did not acknowledge address write")
        if delay_seconds is not None:
            await asyncio.sleep(delay_seconds)
        crc_data = await self.lower.read(self.i2c_addr, length // 2 * 3, stop=True)
        if crc_data is None:
            raise SEN5xError("SEN5x did not acknowledge data read")
        self._log("addr=%#06x data=<%s>", addr, dump_hex(crc_data))
        data = bytearray()
        for index, (chunk, crc) in enumerate(struct.iter_unpack(">2sB", crc_data)):
            if self._crc(chunk) != crc:
                raise SEN5xError("CRC failed on word {}".format(index))
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
            raise SEN5xError("SEN5x did not acknowledge command write")

    async def _read(self, addr, format, delay_seconds=None):
        return struct.unpack(format, await self._read_raw(addr, struct.calcsize(format), delay_seconds))

    async def _write(self, cmd, format="", *args):
        await self._write_raw(cmd, struct.pack(format, *args))

    async def soft_reset(self):
        self._log("soft reset")
        await self._write(CMD_SOFT_RESET)

    async def product_name(self):
        name, = await self._read(CMD_PRODUCT_NAME, ">32s")
        self._log("product name=%s", name)
        return name.rstrip(b'\x00').decode('ascii')

    async def serial_number(self):
        serial, = await self._read(CMD_SERIAL_NUM, ">32s")
        self._log("serial number=%s", serial)
        return serial.rstrip(b'\x00').decode('ascii')

    async def firmware_version(self):
        version, reserved = await self._read(CMD_FIRMWARE_VER, ">BB")
        self._log("firmware version=%d reserved=%d", version, reserved)
        return version

    async def is_data_ready(self):
        ready, = await self._read(CMD_DATA_READY, ">H")
        self._log("data ready=%d", ready)
        return bool(ready)

    async def start_measurement(self):
        self._log("start measurement")
        await self._write(CMD_START_MEASURE)

    async def stop_measurement(self):
        self._log("stop measurement")
        await self._write(CMD_STOP_MEASURE)

    async def read_measurement(self):
        measurements = await self._read(CMD_READ_MEASURE, ">HHHHhhhh", delay_seconds=10e-3)
        scale_factors = [10, 10, 10, 10, 100, 200, 10, 10]
        measurements = [a / float(b) for a,b in zip(measurements, scale_factors)]
        (pm1_0, pm2_5, pm4_0, pm10, rh_pct, temp_degC, voc_index, nox_index) = measurements
        self._log("measured PM1.0=%.1f [µg/m³] PM2.5=%.1f [µg/m³] PM4.0%.1f [µg/m³] PM10=%.1f [µg/m³] RH=%.2f [%%] T=%.2f [°C] VOC=%.1f NOx=%.1f",
                    pm1_0, pm2_5, pm4_0, pm10, rh_pct, temp_degC, voc_index, nox_index)
        return SEN5xMeasurement(pm1_0, pm2_5, pm4_0, pm10, rh_pct, temp_degC, voc_index, nox_index)


class SensorSEN5xApplet(I2CInitiatorApplet):
    logger = logging.getLogger(__name__)
    help = "measure PM, NOx, VOC, humidity, and temperature with Sensirion SEN5x sensors"
    description = """
    Measure PM, NOx, VOC, humidity, and temperature using Sensirion SEN5x sensors
    connected over the I²C interface.

    NOTE: The SEL pin must be connected to ground before startup, for the SEN5x to enable the I2C interface.
    """

    async def run(self, device, args):
        i2c_iface = await self.run_lower(SensorSEN5xApplet, device, args)
        return SEN5xI2CInterface(i2c_iface, self.logger)

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

        p_start = p_operation.add_parser(
            "start", help="start measurement")

        p_stop = p_operation.add_parser(
            "stop", help="stop measurement")

        p_measure = p_operation.add_parser(
            "measure", help="read measured values (must start first)")

        p_log = p_operation.add_parser(
            "log", help="log measured values (must start first)")
        DataLogger.add_subparsers(p_log)

    async def interact(self, device, args, sen5x):
        product_name = await sen5x.product_name()
        serial = await sen5x.serial_number()
        version = await sen5x.firmware_version()
        self.logger.info("SEN5x: %s serial %s firmware v%d", product_name, serial, version)


        if args.operation == "start":
            await sen5x.start_measurement()

        if args.operation == "stop":
            await sen5x.stop_measurement()

        if args.operation == "measure":
            while not await sen5x.is_data_ready():
                await asyncio.sleep(1.0)

            sample = await sen5x.read_measurement()
            print("PM1.0 concentration : {:.1f} µg/m³".format(sample.pm1_0))
            print("PM2.5 concentration : {:.1f} µg/m³".format(sample.pm2_5))
            print("PM4.0 concentration : {:.1f} µg/m³".format(sample.pm4_0))
            print("PM10  concentration : {:.1f} µg/m³".format(sample.pm10))
            print("relative humidity   : {:.2f} %".format(sample.rh_pct))
            print("temperature         : {:.2f} °C".format(sample.temp_degC))
            print("VOC index           : {:.1f}".format(sample.voc_index))
            print("NOx index           : {:.1f}".format(sample.nox_index))

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
                    while not await sen5x.is_data_ready():
                        await asyncio.sleep(meas_interval / 2)

                    sample = await sen5x.read_measurement()
                    fields = sample._asdict()
                    await data_logger.report_data(fields)
                try:
                    await asyncio.wait_for(report(), meas_interval * 3)
                except SEN5xError as error:
                    await data_logger.report_error(str(error), exception=error)
                    await sen5x.lower.reset()
                    await asyncio.sleep(meas_interval)
                except asyncio.TimeoutError as error:
                    await data_logger.report_error("timeout", exception=error)
                    await sen5x.lower.reset()
