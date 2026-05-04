# Ref: QMC5883P Datasheet - Triple Axis Magnetometer
# Accession: G00XXX

import logging
import asyncio
import struct
import enum

from glasgow.support.bitstruct import bitstruct
from glasgow.support.data_logger import DataLogger
from glasgow.applet.interface.i2c_controller import I2CControllerInterface
from glasgow.applet import GlasgowAppletError, GlasgowAppletV2


# I2C Address
_DEFAULT_ADDR = 0x2C

# Registers
_CHIPID = 0x00
_XOUT_LSB = 0x01
_XOUT_MSB = 0x02
_YOUT_LSB = 0x03
_YOUT_MSB = 0x04
_ZOUT_LSB = 0x05
_ZOUT_MSB = 0x06
_STATUS = 0x09
_CONTROL1 = 0x0A
_CONTROL2 = 0x0B


class OperatingMode(enum.Enum):
    """Operating modes for QMC5883P."""

    Suspend    = "suspend"
    Normal     = "normal"
    Single     = "single"
    Continuous = "continuous"

    def __str__(self):
        return self.value

    def to_device(self):
        match self:
            case self.Suspend:    return 0
            case self.Normal:     return 1
            case self.Single:     return 2
            case self.Continuous: return 3


class OutputDataRate(enum.Enum):
    """Output data rates (Hz)."""

    ODR_10Hz  = 10
    ODR_50Hz  = 50
    ODR_100Hz = 100
    ODR_200Hz = 200

    def __str__(self):
        return str(self.value)

    def to_device(self):
        match self:
            case self.ODR_10Hz:  return 0
            case self.ODR_50Hz:  return 1
            case self.ODR_100Hz: return 2
            case self.ODR_200Hz: return 3


class OversampleRatio(enum.Enum):
    """Oversample ratios."""

    OSR_8 = 8
    OSR_4 = 4
    OSR_2 = 2
    OSR_1 = 1

    def __str__(self):
        return str(self.value)

    def to_device(self):
        match self:
            case self.OSR_8: return 0
            case self.OSR_4: return 1
            case self.OSR_2: return 2
            case self.OSR_1: return 3


class DownsampleRatio(enum.Enum):
    """Downsample ratios."""

    DSR_1 = 1
    DSR_2 = 2
    DSR_4 = 4
    DSR_8 = 8

    def __str__(self):
        return str(self.value)

    def to_device(self):
        match self:
            case self.DSR_1: return 0
            case self.DSR_2: return 1
            case self.DSR_4: return 2
            case self.DSR_8: return 3


class FieldRange(enum.Enum):
    """Field ranges (Gauss)."""

    Range_30G = 30
    Range_12G = 12
    Range_8G  = 8
    Range_2G  = 2

    def __str__(self):
        return str(self.value)

    def to_device(self):
        match self:
            case self.Range_30G: return 0
            case self.Range_12G: return 1
            case self.Range_8G:  return 2
            case self.Range_2G:  return 3


class SetResetMode(enum.Enum):
    """Set/Reset modes."""

    On      = "on"
    SetOnly = "set-only"
    Off     = "off"

    def __str__(self):
        return self.value

    def to_device(self):
        match self:
            case self.On:      return 0
            case self.SetOnly: return 1
            case self.Off:     return 2


# Register layouts

REG_STATUS = bitstruct("REG_STATUS", 8, [
    ("DRDY",    1),  # Data ready
    ("OVL",     1),  # Overflow
    (None,      6),
])

REG_CONTROL1 = bitstruct("REG_CONTROL1", 8, [
    ("MODE",    2),  # Operating mode
    ("ODR",     2),  # Output data rate
    ("OSR",     2),  # Oversample ratio
    ("DSR",     2),  # Downsample ratio
])

REG_CONTROL2 = bitstruct("REG_CONTROL2", 8, [
    ("SR",      2),  # Set/reset mode
    ("RNG",     2),  # Field range
    (None,      3),
    ("SRST",    1),  # Soft reset
])


# LSB per Gauss for each range
_LSB_PER_GAUSS = {
    FieldRange.Range_30G: 1000.0,
    FieldRange.Range_12G: 2500.0,
    FieldRange.Range_8G:  3750.0,
    FieldRange.Range_2G:  15000.0,
}


class QMC5883PError(GlasgowAppletError):
    pass


class QMC5883PInterface:
    """Interface to QMC5883P magnetometer sensor."""

    def __init__(self, logger: logging.Logger, i2c_iface: I2CControllerInterface,
                 i2c_address: int = _DEFAULT_ADDR) -> None:
        self._i2c_iface = i2c_iface
        self._i2c_address = i2c_address
        self._logger = logger
        self._level = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._range = FieldRange.Range_8G

    def _log(self, message: str, *args) -> None:
        self._logger.log(self._level, "QMC5883P: " + message, *args)

    async def _read_reg8u(self, reg: int) -> int:
        async with self._i2c_iface.transaction():
            await self._i2c_iface.write(self._i2c_address, [reg])
            result = await self._i2c_iface.read(self._i2c_address, 1)
        if result is None:
            raise QMC5883PError(
                f"QMC5883P did not acknowledge I2C read at address {self._i2c_address:#04x}"
            )
        (byte,) = result
        self._log("reg=%#04x read=%#04x", reg, byte)
        return byte

    async def _write_reg8u(self, reg: int, byte: int) -> None:
        await self._i2c_iface.write(self._i2c_address, [reg, byte])
        self._log("reg=%#04x write=%#04x", reg, byte)

    async def _read_regs(self, reg: int, size: int) -> list[int]:
        async with self._i2c_iface.transaction():
            await self._i2c_iface.write(self._i2c_address, [reg])
            result = await self._i2c_iface.read(self._i2c_address, size)
        if result is None:
            raise QMC5883PError(
                f"QMC5883P did not acknowledge I2C read at address {self._i2c_address:#04x}"
            )
        return list(result)

    async def reset(self) -> None:
        pass

    async def identify(self) -> int:
        """Read and verify chip ID.

        Returns
        -------
        int
            Chip ID (should be 0x80).

        Raises
        ------
        QMC5883PError
            If chip ID does not match expected value 0x80.
        """
        chip_id = await self._read_reg8u(_CHIPID)
        self._log("Chip ID=%#04x", chip_id)
        if chip_id != 0x80:
            raise QMC5883PError(f"QMC5883P: wrong chip ID={chip_id:#04x}, expected 0x80")
        return chip_id

    async def soft_reset(self) -> None:
        """Perform soft reset via CONTROL2 register.

        Waits 50ms for reset to complete and verifies chip ID.

        Raises
        ------
        QMC5883PError
            If chip ID is invalid after reset.
        """
        await self._write_reg8u(_CONTROL2, REG_CONTROL2(SRST=1).to_int())
        await asyncio.sleep(0.05)  # Wait 50ms for reset to complete

        # Verify chip ID after reset
        chip_id = await self._read_reg8u(_CHIPID)
        if chip_id != 0x80:
            raise QMC5883PError(f"Chip ID invalid after reset: {chip_id:#04x}")

    async def set_mode(self, mode: OperatingMode) -> None:
        """Set operating mode.

        Parameters
        ----------
        mode : OperatingMode
            Operating mode.

        Raises
        ------
        QMC5883PError
            If mode is invalid.
        """
        if not isinstance(mode, OperatingMode):
            mode = OperatingMode(mode)
        ctrl1 = REG_CONTROL1.from_int(await self._read_reg8u(_CONTROL1))
        ctrl1.MODE = mode.to_device()
        await self._write_reg8u(_CONTROL1, ctrl1.to_int())

    async def set_data_rate(self, odr: OutputDataRate) -> None:
        """Set output data rate.

        Parameters
        ----------
        odr : OutputDataRate
            Output data rate.

        Raises
        ------
        QMC5883PError
            If data rate is invalid.
        """
        if not isinstance(odr, OutputDataRate):
            odr = OutputDataRate(odr)
        ctrl1 = REG_CONTROL1.from_int(await self._read_reg8u(_CONTROL1))
        ctrl1.ODR = odr.to_device()
        await self._write_reg8u(_CONTROL1, ctrl1.to_int())

    async def set_oversample_ratio(self, osr: OversampleRatio) -> None:
        """Set oversample ratio.

        Parameters
        ----------
        osr : OversampleRatio
            Oversample ratio.

        Raises
        ------
        QMC5883PError
            If oversample ratio is invalid.
        """
        if not isinstance(osr, OversampleRatio):
            osr = OversampleRatio(osr)
        ctrl1 = REG_CONTROL1.from_int(await self._read_reg8u(_CONTROL1))
        ctrl1.OSR = osr.to_device()
        await self._write_reg8u(_CONTROL1, ctrl1.to_int())

    async def set_downsample_ratio(self, dsr: DownsampleRatio) -> None:
        """Set downsample ratio.

        Parameters
        ----------
        dsr : DownsampleRatio
            Downsample ratio.

        Raises
        ------
        QMC5883PError
            If downsample ratio is invalid.
        """
        if not isinstance(dsr, DownsampleRatio):
            dsr = DownsampleRatio(dsr)
        ctrl1 = REG_CONTROL1.from_int(await self._read_reg8u(_CONTROL1))
        ctrl1.DSR = dsr.to_device()
        await self._write_reg8u(_CONTROL1, ctrl1.to_int())

    async def set_range(self, field_range: FieldRange) -> None:
        """Set field range.

        Parameters
        ----------
        field_range : FieldRange
            Field range.

        Raises
        ------
        QMC5883PError
            If field range is invalid.
        """
        if not isinstance(field_range, FieldRange):
            field_range = FieldRange(field_range)
        self._range = field_range
        ctrl2 = REG_CONTROL2.from_int(await self._read_reg8u(_CONTROL2))
        ctrl2.RNG = field_range.to_device()
        await self._write_reg8u(_CONTROL2, ctrl2.to_int())

    async def get_range(self) -> FieldRange:
        """Get current field range setting.

        Returns
        -------
        FieldRange
            Current field range.
        """
        ctrl2 = REG_CONTROL2.from_int(await self._read_reg8u(_CONTROL2))
        device_to_range = {fr.to_device(): fr for fr in FieldRange}
        return device_to_range[ctrl2.RNG]

    async def set_setreset_mode(self, setreset: SetResetMode) -> None:
        """Set set/reset mode for eliminating sensor offset.

        Parameters
        ----------
        setreset : SetResetMode
            Set/reset mode: :py:`SetResetMode.ON`, :py:`SetResetMode.SETONLY`,
            or :py:`SetResetMode.OFF`.

        Raises
        ------
        QMC5883PError
            If set/reset mode is invalid.
        """
        if not isinstance(setreset, SetResetMode):
            setreset = SetResetMode(setreset)
        ctrl2 = REG_CONTROL2.from_int(await self._read_reg8u(_CONTROL2))
        ctrl2.SR = setreset.to_device()
        await self._write_reg8u(_CONTROL2, ctrl2.to_int())

    async def data_ready(self) -> bool:
        """Check if new measurement data is available.

        Returns
        -------
        bool
            True if data is ready to be read.
        """
        return bool(REG_STATUS.from_int(await self._read_reg8u(_STATUS)).DRDY)

    async def overflow(self) -> bool:
        """Check if sensor measurement has overflowed.

        Returns
        -------
        bool
            True if overflow occurred.
        """
        return bool(REG_STATUS.from_int(await self._read_reg8u(_STATUS)).OVL)

    async def get_magnetic_raw(self) -> tuple[int, int, int]:
        """Read raw magnetic field values.

        Waits for data ready, then reads all three axes.

        Returns
        -------
        tuple[int, int, int]
            Raw 16-bit signed values (x, y, z).

        Raises
        ------
        QMC5883PError
            If timeout waiting for data ready.
        """
        # Wait for data ready
        timeout = 100  # 100 iterations
        while not await self.data_ready():
            await asyncio.sleep(0.001)
            timeout -= 1
            if timeout == 0:
                raise QMC5883PError("Timeout waiting for data ready")

        # Read all 6 bytes at once
        data = await self._read_regs(_XOUT_LSB, 6)

        # Unpack as signed 16-bit integers (little-endian)
        raw_x, raw_y, raw_z = struct.unpack("<hhh", bytes(data))

        self._log("raw: x=%d y=%d z=%d", raw_x, raw_y, raw_z)
        return (raw_x, raw_y, raw_z)

    async def get_magnetic(self) -> tuple[float, float, float]:
        """Read magnetic field in Gauss.

        Reads raw values and converts to Gauss based on current range setting.

        Returns
        -------
        tuple[float, float, float]
            Magnetic field values in Gauss (x, y, z).

        Raises
        ------
        QMC5883PError
            If timeout waiting for data ready.
        """
        raw_x, raw_y, raw_z = await self.get_magnetic_raw()

        # Get conversion factor based on current range
        lsb_per_gauss = _LSB_PER_GAUSS[self._range]

        # Convert to Gauss
        x = raw_x / lsb_per_gauss
        y = raw_y / lsb_per_gauss
        z = raw_z / lsb_per_gauss

        self._log("magnetic: x=%.3f y=%.3f z=%.3f G", x, y, z)
        return (x, y, z)


class SensorQMC5883PApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "measure magnetic field with QMC5883P triple-axis magnetometer"
    description = """
    Measure magnetic field using the QMC5883P triple-axis magnetometer sensor.

    This applet only supports sensors connected via the I²C interface.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "scl", default=True, required=True)
        access.add_pins_argument(parser, "sda", default=True, required=True)

        def i2c_address(arg):
            return int(arg, 0)
        parser.add_argument(
            "--i2c-address", type=i2c_address, metavar="ADDR", default=0x2C,
            help="I2C address of the sensor (default: %(default)#02x)")

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self._i2c_iface = I2CControllerInterface(self.logger, self.assembly,
                scl=args.scl, sda=args.sda)
            self.qmc5883p_iface = QMC5883PInterface(self.logger, self._i2c_iface,
                args.i2c_address)

    async def setup(self, args):
        await self._i2c_iface.clock.set_frequency(100e3)

    @classmethod
    def add_run_arguments(cls, parser):
        parser.add_argument(
            "-m", "--mode", metavar="MODE", type=OperatingMode, default=OperatingMode.Normal,
            choices=list(OperatingMode),
            help="operating mode (default: %(default)s)")
        parser.add_argument(
            "-r", "--data-rate", metavar="RATE", type=lambda x: OutputDataRate(int(x)),
            default=OutputDataRate.ODR_50Hz, choices=list(OutputDataRate),
            help="output data rate in Hz (default: %(default)s)")
        parser.add_argument(
            "-o", "--oversample", metavar="RATIO", type=lambda x: OversampleRatio(int(x)),
            default=OversampleRatio.OSR_4, choices=list(OversampleRatio),
            help="oversample ratio (default: %(default)s)")
        parser.add_argument(
            "-d", "--downsample", metavar="RATIO", type=lambda x: DownsampleRatio(int(x)),
            default=DownsampleRatio.DSR_2, choices=list(DownsampleRatio),
            help="downsample ratio (default: %(default)s)")
        parser.add_argument(
            "-R", "--range", metavar="GAUSS", type=lambda x: FieldRange(int(x)),
            default=FieldRange.Range_8G, choices=list(FieldRange),
            help="field range in Gauss (default: %(default)s)")

        p_operation = parser.add_subparsers(
            dest="operation", metavar="OPERATION", required=True)

        p_measure = p_operation.add_parser("measure", help="read measured values")

        p_log = p_operation.add_parser("log", help="log measured values")
        p_log.add_argument(
            "-i", "--interval", metavar="TIME", type=float, required=True,
            help="sample each TIME seconds")
        DataLogger.add_subparsers(p_log)

    async def run(self, args):
        qmc5883p = self.qmc5883p_iface

        await qmc5883p.reset()
        chip_id = await qmc5883p.identify()
        self.logger.info("QMC5883P chip ID: %#04x", chip_id)

        # Configure the sensor
        await qmc5883p.set_mode(OperatingMode.Suspend)
        await qmc5883p.set_data_rate(args.data_rate)
        await qmc5883p.set_oversample_ratio(args.oversample)
        await qmc5883p.set_downsample_ratio(args.downsample)
        await qmc5883p.set_range(args.range)
        await qmc5883p.set_setreset_mode(SetResetMode.On)

        # Set the desired operating mode
        await qmc5883p.set_mode(args.mode)

        if args.operation == "measure":
            x, y, z = await qmc5883p.get_magnetic()
            print(f"magnetic field x: {x:.3f} G")
            print(f"magnetic field y: {y:.3f} G")
            print(f"magnetic field z: {z:.3f} G")

            magnitude = (x**2 + y**2 + z**2) ** 0.5
            print(f"magnitude      : {magnitude:.3f} G")

        if args.operation == "log":
            field_names = dict(x="x(G)", y="y(G)", z="z(G)", mag="mag(G)")
            data_logger = await DataLogger(self.logger, args, field_names=field_names)

            while True:
                async def report():
                    x, y, z = await qmc5883p.get_magnetic()
                    magnitude = (x**2 + y**2 + z**2) ** 0.5
                    fields = dict(x=x, y=y, z=z, mag=magnitude)
                    await data_logger.report_data(fields)

                try:
                    await asyncio.wait_for(report(), args.interval * 2)
                except QMC5883PError as error:
                    await data_logger.report_error(str(error), exception=error)
                    await qmc5883p.reset()
                    await qmc5883p.identify()
                    await qmc5883p.set_mode(args.mode)
                except TimeoutError as error:
                    await data_logger.report_error("timeout", exception=error)
                    await qmc5883p.reset()
                    await qmc5883p.identify()
                    await qmc5883p.set_mode(args.mode)

                await asyncio.sleep(args.interval)
