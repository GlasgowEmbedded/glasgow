# Ref: Plantower PMS5003 series data manual
# Accession: G00053
# Ref: Plantower PMS7003 series data manual (Chinese)
# Accession: G00054

import struct
from collections import namedtuple

from glasgow.support import logging
from glasgow.support.data_logger import DataLogger
from glasgow.applet.interface.uart import UARTInterface
from glasgow.applet import GlasgowAppletError, GlasgowAppletV2


__all__ = ["PMSx003Error", "PMSx003Measurement", "PMSx003Interface"]


class PMSx003Error(GlasgowAppletError):
    pass


PMSx003Measurement = namedtuple("PMSx003Measurement", (
    "pm1_0_ug_m3", "pm2_5_ug_m3", "pm10_ug_m3",
    "p0_3_n_dL", "p0_5_n_dL", "p1_0_n_dL", "p2_5_n_dL", "p5_0_n_dL", "p10_n_dL",
))


class PMSx003Interface:
    def __init__(self, logger: logging.Logger, uart_iface: UARTInterface):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        self._uart_iface = uart_iface

    def _log(self, message, *args):
        self._logger.log(self._level, "PMSx003: " + message, *args)

    async def read_measurement(self) -> PMSx003Measurement:
        start_bytes = b"BM"
        while (await self._uart_iface.read(1)) != b"B": pass
        while (await self._uart_iface.read(1)) != b"M": pass

        length_bytes = bytes(await self._uart_iface.read(2))
        length, = struct.unpack(">H", length_bytes)
        assert length > 2

        data_bytes  = bytes(await self._uart_iface.read(length - 2))
        data = struct.unpack(">13H", data_bytes)

        check_bytes = await self._uart_iface.read(2)
        check, = struct.unpack(">H", check_bytes)
        if sum(start_bytes + length_bytes + data_bytes) != check:
            raise PMSx003Error("PMSx003 checksum incorrect")

        sample = PMSx003Measurement(*data[3:12])
        self._log("measured PM1.0=%d [ug/m³] PM2.5=%d [ug/m³] PM10=%d [ug/m³] "
                  "P0.3=%d [n/dL] P0.5=%d [n/dL] P1.0=%d [n/dL] "
                  "P2.5=%d [n/dL] P5.0=%d [n/dL] P10=%d [n/dL]",
                  *sample)
        return sample


class SensorPMSx003Applet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "measure air quality with Plantower PMx003 sensors"
    description = """
    Measure PM2.5 air quality with Plantower PMx003 family sensors.

    This applet has been tested with PMS5003 and PMS7003.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "rx", default=True, required=True)
        access.add_pins_argument(parser, "tx", default=True)

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.uart_iface = UARTInterface(self.logger, self.assembly,
                rx=args.rx, tx=args.tx)
            self.pmsx003_iface = PMSx003Interface(self.logger, self.uart_iface)

    async def setup(self, args):
        await self.uart_iface.set_baud(9600)

    @classmethod
    def add_run_arguments(cls, parser):
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

        p_measure = p_operation.add_parser(
            "measure", help="read measured values")

        p_log = p_operation.add_parser(
            "log", help="log measured values")
        DataLogger.add_subparsers(p_log)

    async def run(self, args):
        if args.operation == "measure":
            sample = await self.pmsx003_iface.read_measurement()
            print(f"PM1.0 air quality : {sample.pm1_0_ug_m3:d} µg/m³")
            print(f"PM2.5 air quality : {sample.pm2_5_ug_m3:d} µg/m³")
            print(f"PM10 air quality  : {sample.pm10_ug_m3:d} µg/m³")
            print(f"0.3 µm particles  : {sample.p0_3_n_dL:d} n/dL")
            print(f"0.5 µm particles  : {sample.p0_5_n_dL:d} n/dL")
            print(f"1.0 µm particles  : {sample.p1_0_n_dL:d} n/dL")
            print(f"2.5 µm particles  : {sample.p2_5_n_dL:d} n/dL")
            print(f"5.0 µm particles  : {sample.p5_0_n_dL:d} n/dL")
            print(f"10 µm particles   : {sample.p10_n_dL:d} n/dL")

        if args.operation == "log":
            field_names = dict(
                pm1_0="PM1.0(µg/m³)",
                pm2_5="PM2.5(µg/m³)",
                pm10="PM10(µg/m³)",
                p0_3="P0.3(n/dL)",
                p0_5="P0.5(n/dL)",
                p1_0="P1.0(n/dL)",
                p2_5="P2.5(n/dL)",
                p5_0="P5.0(n/dL)",
                p10="P10(n/dL)",
            )
            data_logger = await DataLogger(self.logger, args, field_names=field_names)
            while True:
                try:
                    sample = await self.pmsx003_iface.read_measurement()
                    fields = dict(
                        pm1_0=sample.pm1_0_ug_m3, pm2_5=sample.pm2_5_ug_m3, pm10=sample.pm10_ug_m3,
                        p0_3=sample.p0_3_n_dL, p0_5=sample.p0_5_n_dL, p1_0=sample.p1_0_n_dL,
                        p2_5=sample.p2_5_n_dL, p5_0=sample.p5_0_n_dL, p10=sample.p10_n_dL,
                    )
                    await data_logger.report_data(fields)
                except PMSx003Error as error:
                    await data_logger.report_error(str(error), exception=error)

    @classmethod
    def tests(cls):
        from . import test
        return test.SensorPMSx003AppletTestCase
