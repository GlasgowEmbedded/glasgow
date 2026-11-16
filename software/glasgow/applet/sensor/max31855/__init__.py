# Ref: MAX31855 Cold-Junction Compensated Thermocouple-to-Digital Converter
# Accession: G00132

import enum
import asyncio
from dataclasses import dataclass

from glasgow.support import logging
from glasgow.abstract import AbstractAssembly
from glasgow.applet import GlasgowAppletV2
from glasgow.applet.interface.spi_controller import SPIControllerInterface, SPIControllerApplet
from glasgow.support.data_logger import DataLogger


__all__ = ["MAX31855Fault", "MAX31855Sample", "SensorMAX31855Interface"]


class MAX31855Fault(enum.Enum):
    """Enumeration of all detectable faults."""

    Absent   = "absent"
    Open     = "open"
    ShortGND = "short-gnd"
    ShortVCC = "short-vcc"


@dataclass(kw_only=True, frozen=True)
class MAX31855Sample:
    """An individual temperature sample."""

    value: float
    """Temperature in degrees Celsius."""

    fault: MAX31855Fault
    """Type of the detected input fault."""


class SensorMAX31855Interface:
    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
                 spi_iface: SPIControllerInterface, spi_chip: int = 0):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        self._spi_iface = spi_iface
        self._spi_chip  = spi_chip

    def _log(self, message, *args):
        self._logger.log(self._level, "MAX31855: " + message, *args)

    async def sample(self) -> MAX31855Sample:
        """Read one temperature sample."""
        async with self._spi_iface.select(self._spi_chip):
            data_word = int.from_bytes(await self._spi_iface.read(4), signed=True)
            self._log("data=%08x", data_word & 0xffffffff)

        fault = MAX31855Fault.Absent
        if data_word & 0x10000:
            if data_word & 0b001:
                fault = MAX31855Fault.Open
            elif data_word & 0b010:
                fault = MAX31855Fault.ShortGND
            elif data_word & 0b100:
                fault = MAX31855Fault.ShortVCC

        return MAX31855Sample(value=(data_word >> 18) * 0.25, fault=fault)


class SensorMAX31855Applet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "measure temperature with Analog Devices MAX31855"
    description = """
    Measure temperature with Analog Devices (Maxim) MAX31855 thermocouple-to-digital converter.

    This device supports K-, J-, N-, T-, S-, R-, or E-type thermocouples. It does not have any
    runtime configuration: the thermocouple type is fixed for each part number.
    """
    required_revision = SPIControllerApplet.required_revision

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)

        access.add_pins_argument(parser, "cs",  default=True, required=True)
        access.add_pins_argument(parser, "sck", default=True, required=True)
        access.add_pins_argument(parser, "so",  default=True, required=True)

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.spi_iface = SPIControllerInterface(self.logger, self.assembly,
                cs=args.cs, sck=args.sck, cipo=args.so, mode=0)
            self.max31855_iface = SensorMAX31855Interface(self.logger, self.assembly,
                spi_iface=self.spi_iface, spi_chip=0)

    async def setup(self, args):
        await self.spi_iface.clock.set_frequency(1e6)

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
            sample = await self.max31855_iface.sample()
            print(f"value : {sample.value:+.2f} °C")
            print(f"fault : {sample.fault.value}")

        if args.operation == "log":
            data_logger = await DataLogger(self.logger, args,
                field_names=dict(t="T(°C)", fault="fault"))
            while True:
                sample = await self.max31855_iface.sample()
                await data_logger.report_data(
                    fields={"t": sample.value, "fault": sample.fault.value})
                await asyncio.sleep(1)

    @classmethod
    def tests(cls):
        from . import test
        return test.SensorMAX31855AppletTestCase
