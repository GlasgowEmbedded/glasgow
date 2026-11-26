# Ref: https://sensirion.com/media/documents/33FD6951/6A7C10A0/HT_DS_Datasheet_SHT4x_V7.3.pdf
# Accession: G00137

from dataclasses import asdict, dataclass
import argparse
import asyncio
import enum
import math
import struct

from amaranth.lib.crc.catalog import CRC8_NRSC_5

from glasgow.support import logging
from glasgow.support.data_logger import DataLogger
from glasgow.support.logging import dump_hex
from glasgow.applet import GlasgowAppletError, GlasgowAppletV2
from glasgow.applet.interface.i2c_controller import I2CControllerInterface, I2CControllerPorts


__all__ = ["SHT4xError", "SHT4xMeasurement", "SHT4xI2CInterface"]


class SHT4xError(GlasgowAppletError):
    """An invalid sensor response."""


@dataclass(frozen=True)
class SHT4xMeasurement:
    """Temperature in degrees Celsius and relative humidity in percent."""

    temp_degC: float
    rh_pct: float


class SHT4xCommand(enum.Enum):
    # Each command is paired with the time to wait before reading or sending another command.
    MEASURE_HIGH   = (0xFD, 8.3e-3)
    MEASURE_MEDIUM = (0xF6, 4.5e-3)
    MEASURE_LOW    = (0xE0, 1.6e-3)
    SERIAL_NUMBER  = (0x89, 1e-3)
    SOFT_RESET     = (0x94, 1e-3)

    # Allow for the maximum heater duration followed by a high-repeatability conversion.
    HEAT_20MW_SHORT  = (0x15, 0.110 + 8.3e-3)
    HEAT_20MW_LONG   = (0x1E, 1.100 + 8.3e-3)
    HEAT_110MW_SHORT = (0x24, 0.110 + 8.3e-3)
    HEAT_110MW_LONG  = (0x2F, 1.100 + 8.3e-3)
    HEAT_200MW_SHORT = (0x32, 0.110 + 8.3e-3)
    HEAT_200MW_LONG  = (0x39, 1.100 + 8.3e-3)


class SHT4xI2CInterface:
    """An I²C interface to a Sensirion SHT4x temperature and humidity sensor.

    The underlying controller is available as :attr:`i2c_iface`. Do not issue commands to the
    same sensor concurrently or begin a controller transaction around a sensor operation.
    """

    i2c_iface: I2CControllerInterface
    """The underlying I²C controller, which may be shared with other targets."""

    _crc = staticmethod(CRC8_NRSC_5(data_width=8).compute)
    _measure_commands = {
        "high":   SHT4xCommand.MEASURE_HIGH,
        "medium": SHT4xCommand.MEASURE_MEDIUM,
        "low":    SHT4xCommand.MEASURE_LOW,
    }
    _heat_commands = {
        (20, 0.1):  SHT4xCommand.HEAT_20MW_SHORT,
        (20, 1.0):  SHT4xCommand.HEAT_20MW_LONG,
        (110, 0.1): SHT4xCommand.HEAT_110MW_SHORT,
        (110, 1.0): SHT4xCommand.HEAT_110MW_LONG,
        (200, 0.1): SHT4xCommand.HEAT_200MW_SHORT,
        (200, 1.0): SHT4xCommand.HEAT_200MW_LONG,
    }

    def __init__(self, logger: logging.Logger, i2c_iface: I2CControllerInterface,
                 i2c_address: int = 0x44):
        self._logger      = logger
        self._level       = logging.DEBUG if logger.name == __name__ else logging.TRACE
        self.i2c_iface    = i2c_iface
        self._i2c_address = i2c_address

    async def _send_command(self, command: SHT4xCommand):
        opcode, delay_seconds = command.value
        # The sensor requires a STOP after the command and NACKs reads while busy.
        await self.i2c_iface.write(self._i2c_address, bytes([opcode]))
        await asyncio.sleep(delay_seconds)

    async def _read_data(self, command: SHT4xCommand) -> bytes:
        await self._send_command(command)
        response = await self.i2c_iface.read(self._i2c_address, 6)
        self._logger.log(self._level, "SHT4x: %s data=<%s>", command.name, dump_hex(response))

        words = []
        for index, (data, crc) in enumerate(struct.iter_unpack(">2sB", response)):
            if self._crc(data) != crc:
                raise SHT4xError(f"CRC failed on word {index}")
            words.append(data)
        return b"".join(words)

    async def serial_number(self) -> str:
        """Read the sensor's serial number as eight lowercase hexadecimal digits."""
        return (await self._read_data(SHT4xCommand.SERIAL_NUMBER)).hex()

    async def soft_reset(self):
        """Reset only the sensor at the configured I²C address and wait for it to become idle."""
        await self._send_command(SHT4xCommand.SOFT_RESET)

    async def _read_measurement(self, command: SHT4xCommand) -> SHT4xMeasurement:
        temp_raw, rh_raw = struct.unpack(">HH", await self._read_data(command))
        return SHT4xMeasurement(
            temp_degC=-45 + 175 * temp_raw / 65535,
            rh_pct=min(100.0, max(0.0, -6 + 125 * rh_raw / 65535)),
        )

    async def measure(self, repeatability: str = "high") -> SHT4xMeasurement:
        """Take one unheated measurement at high, medium, or low repeatability.

        Relative humidity is clipped to the physical range of 0 to 100 percent.
        """
        if repeatability not in self._measure_commands:
            raise ValueError(f"invalid SHT4x repeatability {repeatability!r}")
        return await self._read_measurement(self._measure_commands[repeatability])

    async def heat(self, power_mw: int = 20, duration_s: float = 0.1) -> SHT4xMeasurement:
        """Pulse the heater once and return the measurement taken while heating.

        Choose 20, 110, or 200 mW (nominal at 3.3 V) and a duration of 0.1 or 1 second.
        Use below 65°C ambient and keep the heater duty cycle below 10% when invoking this
        method repeatedly. The heated reading is not an ambient reading.
        """
        command = self._heat_commands.get((power_mw, duration_s))
        if command is None:
            raise ValueError(f"invalid SHT4x heater setting: {power_mw!r} mW for {duration_s!r} s")
        return await self._read_measurement(command)


class SensorSHT4xApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "measure temperature and humidity with Sensirion SHT4x sensors"
    description = """
    Measure temperature and relative humidity with Sensirion SHT40, SHT41, SHT43, and SHT45
    sensors connected over I²C.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_ports_arguments(parser, I2CControllerPorts)
        def i2c_address(arg):
            return int(arg, 0)

        parser.add_argument(
            "--i2c-address", type=i2c_address, metavar="ADDR",
            choices=[0x44, 0x45, 0x46], default=0x44,
            help="I²C address of the sensor (one of: 0x44 0x45 0x46, default: %(default)#04x)")

    def build(self, args):
        with self.assembly.add_applet(self):
            ports = self.assembly.add_ports(I2CControllerPorts, args)
            self.i2c_iface = I2CControllerInterface(self.logger, self.assembly, ports)
            self.sht4x_iface = SHT4xI2CInterface(self.logger, self.i2c_iface, args.i2c_address)

    async def setup(self, args):
        await self.i2c_iface.clock.set_frequency(100e3)

    @classmethod
    def add_run_arguments(cls, parser):
        parser.add_argument(
            "--repeatability", choices=["high", "medium", "low"], default="high",
            help="measurement repeatability (one of: high medium low, default: %(default)s)")
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)
        p_operation.add_parser("serial-number", help="read the sensor serial number")
        p_operation.add_parser("measure", help="take one temperature and humidity measurement")
        p_heat = p_operation.add_parser(
            "heat", help="pulse the heater once and read a heated sample")
        p_heat.add_argument(
            "--power", type=int, choices=[20, 110, 200], default=20, metavar="HEATER-POWER",
            help="nominal heater power at 3.3 V (one of: 20 110 200 mW, default: %(default)s mW)")
        p_heat.add_argument(
            "--duration", type=float, choices=[0.1, 1.0], default=0.1, metavar="PULSE-DURATION",
            help="heater pulse duration (one of: 0.1 1 seconds, default: %(default)s s)")

        def log_interval(arg):
            interval = float(arg)
            if not math.isfinite(interval) or interval <= 0:
                raise argparse.ArgumentTypeError("logging interval must be finite and positive")
            return interval

        p_log = p_operation.add_parser("log", help="log temperature and humidity")
        p_log.add_argument(
            "-i", "--interval", type=log_interval, default=1.0, metavar="TIME",
            help="delay between samples in seconds (default: %(default)s s)")
        DataLogger.add_subparsers(p_log)

    async def run(self, args):
        await self.sht4x_iface.soft_reset()

        if args.operation == "serial-number":
            print(await self.sht4x_iface.serial_number())

        if args.operation == "heat":
            sample = await self.sht4x_iface.heat(args.power, args.duration)
            print(f"heated temperature       : {sample.temp_degC:.2f} °C")
            print(f"heated relative humidity : {sample.rh_pct:.2f} %")

        if args.operation == "measure":
            sample = await self.sht4x_iface.measure(args.repeatability)
            print(f"temperature       : {sample.temp_degC:.2f} °C")
            print(f"relative humidity : {sample.rh_pct:.2f} %")

        if args.operation == "log":
            data_logger = await DataLogger(self.logger, args, field_names=dict(
                temp_degC="T(°C)", rh_pct="RH(%)"))
            while True:
                sample = await self.sht4x_iface.measure(args.repeatability)
                await data_logger.report_data(asdict(sample))
                await asyncio.sleep(args.interval)

    @classmethod
    def tests(cls):
        from . import test
        return test.SensorSHT4xAppletTestCase
