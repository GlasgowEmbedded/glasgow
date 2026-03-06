# Ref: QMC5883P Datasheet - Triple Axis Magnetometer
# Accession: G00XXX

import logging
import asyncio
import struct

from ....support.data_logger import DataLogger
from ... import *
from ...interface.i2c_initiator import I2CInitiatorApplet


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

# Operating modes
MODE_SUSPEND = 0x00
MODE_NORMAL = 0x01
MODE_SINGLE = 0x02
MODE_CONTINUOUS = 0x03

# Output data rates
ODR_10HZ = 0x00
ODR_50HZ = 0x01
ODR_100HZ = 0x02
ODR_200HZ = 0x03

# Over sample ratios
OSR_8 = 0x00
OSR_4 = 0x01
OSR_2 = 0x02
OSR_1 = 0x03

# Downsample ratios
DSR_1 = 0x00
DSR_2 = 0x01
DSR_4 = 0x02
DSR_8 = 0x03

# Field ranges
RANGE_30G = 0x00
RANGE_12G = 0x01
RANGE_8G = 0x02
RANGE_2G = 0x03

# Set/Reset modes
SETRESET_ON = 0x00
SETRESET_SETONLY = 0x01
SETRESET_OFF = 0x02

# LSB per Gauss for each range
_LSB_PER_GAUSS = {
    RANGE_30G: 1000.0,
    RANGE_12G: 2500.0,
    RANGE_8G: 3750.0,
    RANGE_2G: 15000.0,
}

# Mode names for user interface
mode_names = {
    "suspend": MODE_SUSPEND,
    "normal": MODE_NORMAL,
    "single": MODE_SINGLE,
    "continuous": MODE_CONTINUOUS,
}

# Data rate names for user interface
data_rate_names = {
    10: ODR_10HZ,
    50: ODR_50HZ,
    100: ODR_100HZ,
    200: ODR_200HZ,
}

# Oversample ratio names for user interface
oversample_ratio_names = {
    8: OSR_8,
    4: OSR_4,
    2: OSR_2,
    1: OSR_1,
}

# Downsample ratio names for user interface
downsample_ratio_names = {
    1: DSR_1,
    2: DSR_2,
    4: DSR_4,
    8: DSR_8,
}

# Range names for user interface
range_names = {
    30: RANGE_30G,
    12: RANGE_12G,
    8: RANGE_8G,
    2: RANGE_2G,
}


class QMC5883PError(GlasgowAppletError):
    pass


class QMC5883PInterface:
    def __init__(self, interface, logger):
        self._iface = interface
        self._logger = logger
        self._level = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._range = RANGE_8G

    def _log(self, message, *args):
        self._logger.log(self._level, "QMC5883P: " + message, *args)

    async def _read_reg8u(self, reg):
        (byte,) = await self._iface.read(reg, 1)
        self._log("reg=%#04x read=%#04x", reg, byte)
        return byte

    async def _write_reg8u(self, reg, byte):
        await self._iface.write(reg, [byte])
        self._log("reg=%#04x write=%#04x", reg, byte)

    async def reset(self):
        await self._iface.reset()

    async def identify(self):
        chip_id = await self._read_reg8u(_CHIPID)
        self._log("Chip ID=%#04x", chip_id)
        if chip_id != 0x80:
            raise QMC5883PError(
                f"QMC5883P: wrong chip ID={chip_id:#04x}, expected 0x80"
            )
        return chip_id

    async def soft_reset(self):
        # Soft reset by setting bit 7 of CONTROL2
        await self._write_reg8u(_CONTROL2, 0x80)
        await asyncio.sleep(0.05)  # Wait 50ms for reset to complete

        # Verify chip ID after reset
        chip_id = await self._read_reg8u(_CHIPID)
        if chip_id != 0x80:
            raise QMC5883PError(f"Chip ID invalid after reset: {chip_id:#04x}")

    async def set_mode(self, mode):
        # Accept both user-facing names and register values
        if isinstance(mode, str):
            if mode not in mode_names:
                raise QMC5883PError(
                    f"Invalid mode: {mode} (choose from: {', '.join(mode_names.keys())})"
                )
            mode = mode_names[mode]
        elif mode not in mode_names.values():
            raise QMC5883PError(f"Invalid mode: {mode}")

        ctrl1 = await self._read_reg8u(_CONTROL1)
        ctrl1 = (ctrl1 & ~0x03) | mode
        await self._write_reg8u(_CONTROL1, ctrl1)

    async def set_data_rate(self, odr):
        # Accept both user-facing values (Hz) and register values
        if odr in data_rate_names:
            odr = data_rate_names[odr]
        elif odr not in data_rate_names.values():
            raise QMC5883PError(
                f"Invalid output data rate: {odr} (choose from: {', '.join(map(str, data_rate_names.keys()))} Hz)"
            )

        ctrl1 = await self._read_reg8u(_CONTROL1)
        ctrl1 = (ctrl1 & ~0x0C) | (odr << 2)
        await self._write_reg8u(_CONTROL1, ctrl1)

    async def set_oversample_ratio(self, osr):
        # Accept both user-facing values and register values
        if osr in oversample_ratio_names:
            osr = oversample_ratio_names[osr]
        elif osr not in oversample_ratio_names.values():
            raise QMC5883PError(
                f"Invalid oversample ratio: {osr} (choose from: {', '.join(map(str, oversample_ratio_names.keys()))})"
            )

        ctrl1 = await self._read_reg8u(_CONTROL1)
        ctrl1 = (ctrl1 & ~0x30) | (osr << 4)
        await self._write_reg8u(_CONTROL1, ctrl1)

    async def set_downsample_ratio(self, dsr):
        # Accept both user-facing values and register values
        if dsr in downsample_ratio_names:
            dsr = downsample_ratio_names[dsr]
        elif dsr not in downsample_ratio_names.values():
            raise QMC5883PError(
                f"Invalid downsample ratio: {dsr} (choose from: {', '.join(map(str, downsample_ratio_names.keys()))})"
            )

        ctrl1 = await self._read_reg8u(_CONTROL1)
        ctrl1 = (ctrl1 & ~0xC0) | (dsr << 6)
        await self._write_reg8u(_CONTROL1, ctrl1)

    async def set_range(self, field_range):
        # Accept both user-facing values (Gauss) and register values
        if field_range in range_names:
            field_range = range_names[field_range]
        elif field_range not in range_names.values():
            raise QMC5883PError(
                f"Invalid range: {field_range} (choose from: {', '.join(map(str, range_names.keys()))} G)"
            )

        self._range = field_range
        ctrl2 = await self._read_reg8u(_CONTROL2)
        ctrl2 = (ctrl2 & ~0x0C) | (field_range << 2)
        await self._write_reg8u(_CONTROL2, ctrl2)

    async def get_range(self):
        """Get the current field range setting in Gauss.

        Returns one of: 30, 12, 8, or 2 (Gauss)
        """
        ctrl2 = await self._read_reg8u(_CONTROL2)
        range_bits = (ctrl2 >> 2) & 0x03

        # Map range bits back to Gauss values
        range_map = {
            RANGE_30G: 30,
            RANGE_12G: 12,
            RANGE_8G: 8,
            RANGE_2G: 2,
        }
        return range_map.get(range_bits, 8)  # Default to 8G if unknown

    async def set_setreset_mode(self, setreset):
        if setreset not in [SETRESET_ON, SETRESET_SETONLY, SETRESET_OFF]:
            raise QMC5883PError(f"Invalid set/reset mode: {setreset}")

        ctrl2 = await self._read_reg8u(_CONTROL2)
        ctrl2 = (ctrl2 & ~0x03) | setreset
        await self._write_reg8u(_CONTROL2, ctrl2)

    async def data_ready(self):
        status = await self._read_reg8u(_STATUS)
        return bool(status & 0x01)

    async def overflow(self):
        status = await self._read_reg8u(_STATUS)
        return bool(status & 0x02)

    async def get_magnetic_raw(self):
        # Wait for data ready
        timeout = 100  # 100 iterations
        while not await self.data_ready():
            await asyncio.sleep(0.001)
            timeout -= 1
            if timeout == 0:
                raise QMC5883PError("Timeout waiting for data ready")

        # Read all 6 bytes at once
        data = await self._iface.read(_XOUT_LSB, 6)

        # Unpack as signed 16-bit integers (little-endian)
        raw_x, raw_y, raw_z = struct.unpack("<hhh", bytes(data))

        self._log("raw: x=%d y=%d z=%d", raw_x, raw_y, raw_z)
        return (raw_x, raw_y, raw_z)

    async def get_magnetic(self):
        raw_x, raw_y, raw_z = await self.get_magnetic_raw()

        # Get conversion factor based on current range
        lsb_per_gauss = _LSB_PER_GAUSS[self._range]

        # Convert to Gauss
        x = raw_x / lsb_per_gauss
        y = raw_y / lsb_per_gauss
        z = raw_z / lsb_per_gauss

        self._log("magnetic: x=%.3f y=%.3f z=%.3f G", x, y, z)
        return (x, y, z)


class QMC5883PI2CInterface:
    def __init__(self, interface, logger, i2c_address):
        self.lower = interface
        self._i2c_addr = i2c_address

    async def reset(self):
        await self.lower.reset()

    async def read(self, addr, size):
        await self.lower.write(self._i2c_addr, [addr])
        result = await self.lower.read(self._i2c_addr, size, stop=True)
        if result is None:
            raise QMC5883PError(
                f"QMC5883P did not acknowledge I2C read at address {self._i2c_addr:#07b}"
            )
        return list(result)

    async def write(self, addr, data):
        result = await self.lower.write(self._i2c_addr, [addr, *data], stop=True)
        if not result:
            raise QMC5883PError(
                f"QMC5883P did not acknowledge I2C write at address {self._i2c_addr:#07b}"
            )


class SensorQMC5883PApplet(I2CInitiatorApplet):
    logger = logging.getLogger(__name__)
    help = "measure magnetic field with QMC5883P triple-axis magnetometer"
    description = """
    Measure magnetic field using the QMC5883P triple-axis magnetometer sensor.

    This applet only supports sensors connected via the I²C interface.
    """

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)

        def i2c_address(arg):
            return int(arg, 0)

        parser.add_argument(
            "--i2c-address",
            type=i2c_address,
            metavar="ADDR",
            default=0x2C,
            help="I2C address of the sensor (default: %(default)#02x)",
        )

    async def run(self, device, args):
        i2c_iface = await self.run_lower(SensorQMC5883PApplet, device, args)
        qmc5883p_iface = QMC5883PI2CInterface(i2c_iface, self.logger, args.i2c_address)
        return QMC5883PInterface(qmc5883p_iface, self.logger)

    @classmethod
    def add_interact_arguments(cls, parser):
        parser.add_argument(
            "-m",
            "--mode",
            metavar="MODE",
            choices=mode_names.keys(),
            default="normal",
            help="operating mode (one of: %(choices)s; default: %(default)s)",
        )
        parser.add_argument(
            "-r",
            "--data-rate",
            type=int,
            metavar="RATE",
            choices=data_rate_names.keys(),
            default=50,
            help="output data rate in Hz (one of: %(choices)s; default: %(default)d)",
        )
        parser.add_argument(
            "-o",
            "--oversample",
            type=int,
            metavar="RATIO",
            choices=oversample_ratio_names.keys(),
            default=4,
            help="oversample ratio (one of: %(choices)s; default: %(default)d)",
        )
        parser.add_argument(
            "-d",
            "--downsample",
            type=int,
            metavar="RATIO",
            choices=downsample_ratio_names.keys(),
            default=2,
            help="downsample ratio (one of: %(choices)s; default: %(default)d)",
        )
        parser.add_argument(
            "-R",
            "--range",
            type=int,
            metavar="GAUSS",
            choices=range_names.keys(),
            default=8,
            help="field range in Gauss (one of: %(choices)s; default: %(default)d)",
        )

        p_operation = parser.add_subparsers(
            dest="operation", metavar="OPERATION", required=True
        )

        p_measure = p_operation.add_parser("measure", help="read measured values")

        p_log = p_operation.add_parser("log", help="log measured values")
        p_log.add_argument(
            "-i",
            "--interval",
            metavar="TIME",
            type=float,
            required=True,
            help="sample each TIME seconds",
        )
        DataLogger.add_subparsers(p_log)

    async def interact(self, device, args, qmc5883p):
        await qmc5883p.reset()
        chip_id = await qmc5883p.identify()
        self.logger.info(f"QMC5883P chip ID: {chip_id:#04x}")

        # Configure the sensor
        await qmc5883p.set_mode(MODE_SUSPEND)  # Set to suspend mode before configuring
        await qmc5883p.set_data_rate(data_rate_names[args.data_rate])
        await qmc5883p.set_oversample_ratio(oversample_ratio_names[args.oversample])
        await qmc5883p.set_downsample_ratio(downsample_ratio_names[args.downsample])
        await qmc5883p.set_range(range_names[args.range])
        await qmc5883p.set_setreset_mode(SETRESET_ON)

        # Set the desired operating mode
        await qmc5883p.set_mode(mode_names[args.mode])

        if args.operation == "measure":
            if args.mode == "single":
                # In single mode, trigger a measurement
                await qmc5883p.set_mode(MODE_SINGLE)

            x, y, z = await qmc5883p.get_magnetic()
            print(f"magnetic field x: {x:.3f} G")
            print(f"magnetic field y: {y:.3f} G")
            print(f"magnetic field z: {z:.3f} G")

            # Calculate magnitude
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
                    await qmc5883p.set_mode(mode_names[args.mode])
                except asyncio.TimeoutError as error:
                    await data_logger.report_error("timeout", exception=error)
                    await qmc5883p.reset()
                    await qmc5883p.identify()
                    await qmc5883p.set_mode(mode_names[args.mode])

                await asyncio.sleep(args.interval)
