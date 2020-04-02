# Ref: https://ae-bst.resource.bosch.com/media/_tech/media/datasheets/BST-BMP280-DS001.pdf
# Accession: G00028
# Ref: https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme280-ds002.pdf
# Accession: G00050

import logging
import asyncio

from ....support.data_logger import DataLogger
from ... import *
from ...interface.i2c_initiator import I2CInitiatorApplet


REG_CAL_T1      = 0x88 # 16-bit unsigned
REG_CAL_T2      = 0x8A # 16-bit signed
REG_CAL_T3      = 0x8C # 16-bit signed
REG_CAL_P1      = 0x8E # 16-bit unsigned
REG_CAL_P2      = 0x90 # 16-bit signed
REG_CAL_P3      = 0x92 # 16-bit signed
REG_CAL_P4      = 0x94 # 16-bit signed
REG_CAL_P5      = 0x96 # 16-bit signed
REG_CAL_P6      = 0x98 # 16-bit signed
REG_CAL_P7      = 0x9A # 16-bit signed
REG_CAL_P8      = 0x9C # 16-bit signed
REG_CAL_P9      = 0x9E # 16-bit signed
REG_CAL_H1      = 0xA1 # 8-bit unsigned
REG_CAL_H2      = 0xE1 # 16-bit signed
REG_CAL_H3      = 0xE3 # 8-bit unsigned
REG_CAL_H4_H5   = 0xE4 # see datasheet
REG_CAL_H6      = 0xE7 # 8-bit signed

REG_ID          = 0xD0 # 8-bit
BIT_ID_BMP280   = 0x58
BIT_ID_BME280   = 0x60

REG_RESET       = 0xE0 # 8-bit
BIT_RESET       = 0xB6

REG_CTRL_HUM    = 0xF2 # 8-bit
BIT_OSRS_H_S    = 0b00000_000
BIT_OSRS_H_1    = 0b00000_001
BIT_OSRS_H_2    = 0b00000_010
BIT_OSRS_H_4    = 0b00000_011
BIT_OSRS_H_8    = 0b00000_100
BIT_OSRS_H_16   = 0b00000_101

bit_osrs_hum = {
    0:  BIT_OSRS_H_S,
    1:  BIT_OSRS_H_1,
    2:  BIT_OSRS_H_2,
    4:  BIT_OSRS_H_4,
    8:  BIT_OSRS_H_8,
    16: BIT_OSRS_H_16,
}

REG_STATUS      = 0xF3 # 8-bit
BIT_IM_UPDATE   = 0b00000001
BIT_MEAS        = 0b00001000

REG_CTRL_MEAS   = 0xF4 # 8-bit
MASK_OSRS       = 0b111111_00
MASK_OSRS_P     = 0b111_00000
BIT_OSRS_P_S    = 0b000_00000
BIT_OSRS_P_1    = 0b001_00000
BIT_OSRS_P_2    = 0b010_00000
BIT_OSRS_P_4    = 0b011_00000
BIT_OSRS_P_8    = 0b100_00000
BIT_OSRS_P_16   = 0b101_00000
MASK_OSRS_T     =    0b111_00
BIT_OSRS_T_S    =    0b000_00
BIT_OSRS_T_1    =    0b001_00
BIT_OSRS_T_2    =    0b010_00
BIT_OSRS_T_4    =    0b011_00
BIT_OSRS_T_8    =    0b100_00
BIT_OSRS_T_16   =    0b101_00
MASK_MODE       =        0b11
BIT_MODE_SLEEP  =        0b00
BIT_MODE_FORCE  =        0b01
BIT_MODE_NORMAL =        0b11

bit_osrs_press = {
    0:  BIT_OSRS_P_S,
    1:  BIT_OSRS_P_1,
    2:  BIT_OSRS_P_2,
    4:  BIT_OSRS_P_4,
    8:  BIT_OSRS_P_8,
    16: BIT_OSRS_P_16,
}

bit_osrs_temp = {
    0:  BIT_OSRS_T_S,
    1:  BIT_OSRS_T_1,
    2:  BIT_OSRS_T_2,
    4:  BIT_OSRS_T_4,
    8:  BIT_OSRS_T_8,
    16: BIT_OSRS_T_16,
}

bit_mode = {
    "sleep":  BIT_MODE_SLEEP,
    "force":  BIT_MODE_FORCE,
    "normal": BIT_MODE_NORMAL,
}

REG_CONFIG    = 0xF5 # 8-bit
MASK_T_SB     = 0b111_00000
BIT_T_SB_0_5  = 0b000_00000
BIT_T_SB_62_5 = 0b001_00000
BIT_T_SB_125  = 0b010_00000
BIT_T_SB_250  = 0b011_00000
BIT_T_SB_500  = 0b100_00000
BIT_T_SB_1000 = 0b101_00000
BIT_T_SB_2000 = 0b110_00000
BIT_T_SB_4000 = 0b111_00000
MASK_IIR      =   0b111_000
BIT_IIR_OFF   =   0b000_000
BIT_IIR_2     =   0b001_000
BIT_IIR_4     =   0b010_000
BIT_IIR_8     =   0b011_000
BIT_IIR_16    =   0b100_000

bit_t_sb = {
    0.0005: BIT_T_SB_0_5,
    0.0625: BIT_T_SB_62_5,
    0.125:  BIT_T_SB_125,
    0.250:  BIT_T_SB_250,
    0.500:  BIT_T_SB_500,
    1.000:  BIT_T_SB_1000,
    2.000:  BIT_T_SB_2000,
    4.000:  BIT_T_SB_4000,
}

bit_iir = {
    0:  BIT_IIR_OFF,
    2:  BIT_IIR_2,
    4:  BIT_IIR_4,
    8:  BIT_IIR_8,
    16: BIT_IIR_16,
}

REG_PRESS     = 0xF7 # 20-bit unsigned
REG_TEMP      = 0xFA # 20-bit unsigned
REG_HUM       = 0xFD # 16-bit unsigned


class BMx280Error(GlasgowAppletError):
    pass


class BMx280Interface:
    def __init__(self, interface, logger):
        self._iface   = interface
        self._logger  = logger
        self._level   = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._has_cal = False
        self._has_hum = False
        self._ident   = "BMx280"

    def _log(self, message, *args):
        self._logger.log(self._level, self._ident + ": " + message, *args)

    async def _read_reg8u(self, reg):
        byte, = await self._iface.read(reg, 1)
        self._log("reg=%#04x read=%#04x", reg, byte)
        return byte

    async def _write_reg8u(self, reg, byte):
        await self._iface.write(reg, [byte])
        self._log("reg=%#04x write=%#04x", reg, byte)

    async def _read_reg8s(self, reg):
        raw, = await self._iface.read(reg, 1)
        if raw & (1 << 7):
            value = -((1 << 8) - raw)
        else:
            value = raw
        self._log("reg=%#04x raw=%#04x read=%d", reg, raw, value)
        return value

    async def _read_reg16ule(self, reg):
        lsb, msb = await self._iface.read(reg, 2)
        raw = (msb << 8) | lsb
        value = raw
        self._log("reg=%#04x raw=%#06x read=%d", reg, raw, value)
        return value

    async def _read_reg16sle(self, reg):
        lsb, msb = await self._iface.read(reg, 2)
        raw = (msb << 8) | lsb
        if raw & (1 << 15):
            value = -((1 << 16) - raw)
        else:
            value = raw
        self._log("reg=%#04x raw=%#06x read=%+d", reg, raw, value)
        return value

    async def _read_reg16ube(self, reg):
        msb, lsb = await self._iface.read(reg, 2)
        raw = (msb << 8) | lsb
        value = raw
        self._log("reg=%#04x raw=%#06x read=%d", reg, raw, value)
        return value

    async def _read_reg24ube(self, reg):
        msb, lsb, xlsb = await self._iface.read(reg, 3)
        raw = ((msb << 16) | (lsb << 8) | xlsb)
        value = raw >> 4
        self._log("reg=%#04x raw=%#06x read=%d", reg, raw, value)
        return value

    async def reset(self):
        await self._iface.reset()
        await self._write_reg8u(REG_RESET, BIT_RESET)

    async def identify(self):
        id = await self._read_reg8u(REG_ID)
        self._log("ID=%#04x", id)
        if id == BIT_ID_BMP280:
            self._ident = "BMP280"
        elif id == BIT_ID_BME280:
            self._ident = "BME280"
            self._has_hum = True
        else:
            raise BMx280Error("BMx280: wrong ID=%#04x" % id)
        return self._ident

    @property
    def has_humidity(self):
        return self._has_hum

    async def _read_cal(self):
        if self._has_cal: return
        self._t1 = await self._read_reg16ule(REG_CAL_T1)
        self._t2 = await self._read_reg16sle(REG_CAL_T2)
        self._t3 = await self._read_reg16sle(REG_CAL_T3)
        self._p1 = await self._read_reg16ule(REG_CAL_P1)
        self._p2 = await self._read_reg16sle(REG_CAL_P2)
        self._p3 = await self._read_reg16sle(REG_CAL_P3)
        self._p4 = await self._read_reg16sle(REG_CAL_P4)
        self._p5 = await self._read_reg16sle(REG_CAL_P5)
        self._p6 = await self._read_reg16sle(REG_CAL_P6)
        self._p7 = await self._read_reg16sle(REG_CAL_P7)
        self._p8 = await self._read_reg16sle(REG_CAL_P8)
        self._p9 = await self._read_reg16sle(REG_CAL_P9)
        if self._has_hum:
            self._h1 = await self._read_reg8u(REG_CAL_H1)
            self._h2 = await self._read_reg16sle(REG_CAL_H2)
            self._h3 = await self._read_reg8u(REG_CAL_H3)
            self._h6 = await self._read_reg8s(REG_CAL_H6)
            # what the hell happened here??
            h4_h5_1 = await self._read_reg8u(REG_CAL_H4_H5 + 0)
            h4_h5_2 = await self._read_reg8u(REG_CAL_H4_H5 + 1)
            h4_h5_3 = await self._read_reg8u(REG_CAL_H4_H5 + 2)
            _12u_to_12s = lambda raw: -((1 << 12) - raw) if raw & (1 << 11) else raw
            self._h4 = _12u_to_12s((h4_h5_1 << 4) | (h4_h5_2 & 0xf))
            self._h5 = _12u_to_12s((h4_h5_3 << 4) | (h4_h5_2 >> 4))
        self._has_cal = True

    async def set_iir_coefficient(self, coeff):
        config = await self._read_reg8u(REG_CONFIG)
        config = (config & ~MASK_IIR) | bit_iir[coeff]
        await self._write_reg8u(REG_CONFIG, config)

    async def set_standby_time(self, t_sb):
        config = await self._read_reg8u(REG_CONFIG)
        config = (config & ~MASK_T_SB) | bit_t_sb[t_sb]
        await self._write_reg8u(REG_CONFIG, config)

    async def set_oversample(self, ovs_t=None, ovs_p=None, ovs_h=None):
        if ovs_h is not None and not self._has_hum:
            raise BMx280Error("%s: sensor does not measure humidity" % self._ident)

        if ovs_h is not None:
            await self._write_reg8u(REG_CTRL_HUM, bit_osrs_hum[ovs_h])
        config = await self._read_reg8u(REG_CTRL_MEAS)
        if ovs_t is not None:
            config = (config & ~MASK_OSRS_T) | bit_osrs_temp[ovs_t]
        if ovs_p is not None:
            config = (config & ~MASK_OSRS_P) | bit_osrs_press[ovs_p]
        await self._write_reg8u(REG_CTRL_MEAS, config)

    async def set_mode(self, mode):
        config = await self._read_reg8u(REG_CTRL_MEAS)
        config = (config & ~MASK_MODE) | bit_mode[mode]
        await self._write_reg8u(REG_CTRL_MEAS, config)
        if mode == "force":
            await asyncio.sleep(0.050) # worst case

    async def _get_temp_fine(self):
        await self._read_cal()
        ut = await self._read_reg24ube(REG_TEMP)
        x1 = (ut / 16384.0  - self._t1 / 1024.0) * self._t2
        x2 = (ut / 131072.0 - self._t1 / 8192.0) ** 2 * self._t3
        tf = x1 + x2
        return tf

    async def get_temperature(self):
        tf = await self._get_temp_fine()
        t  = tf / 5120.0
        return t # in °C

    async def get_pressure(self):
        await self._read_cal()
        tf = await self._get_temp_fine()
        up = await self._read_reg24ube(REG_PRESS)
        x1 = tf / 2.0 - 64000.0
        x2 = x1 * x1 * self._p6 / 32768.0
        x2 = x2 + x1 * self._p5 * 2.0
        x2 = x2 / 4.0 + self._p4 * 65536.0
        x1 = (self._p3 * x1 * x1 / 524288.0 + self._p2 * x1) / 524288.0
        x1 = (1.0 + x1 / 32768.0) * self._p1
        p  = 1048576.0 - up
        p  = (p - x2 / 4096.0) * 6250.0 / x1
        x1 = self._p9 * p * p / 2147483648.0
        x2 = p * self._p8 / 32768.0
        p  = p + (x1 + x2 + self._p7) / 16.0
        return p # in Pa

    async def get_altitude(self, p0=101325):
        p  = await self.get_pressure()
        h  = 44330 * (1 - (p / p0) ** (1 / 5.255))
        return h # in m

    async def get_humidity(self):
        if not self._has_hum:
            raise BMx280Error("%s: sensor does not measure humidity" % self._ident)

        await self._read_cal()
        tf = await self._get_temp_fine()
        uh = await self._read_reg16ube(REG_HUM)
        x1 = tf - 76800.0
        x2 = ((uh - (self._h4 * 64.0 + self._h5 / 16384.0 * x1)) *
              (self._h2 / 65536.0 * (1.0 + self._h6 / 67108864.0 * x1 *
                                       (1.0 + self._h3 / 67108864.0 * x1))))
        rh = x2 * (1.0 - self._h1 * x2 / 524288.0)
        if rh > 100.0:
            return 100.0
        if rh < 0.0:
            return 0.0
        return rh


class BMx280I2CInterface:
    def __init__(self, interface, logger, i2c_address):
        self.lower     = interface
        self._i2c_addr = i2c_address

    async def reset(self):
        await self.lower.reset()

    async def read(self, addr, size):
        await self.lower.write(self._i2c_addr, [addr])
        result = await self.lower.read(self._i2c_addr, size)
        if result is None:
            raise BMx280Error("BMx280 did not acknowledge I2C read at address {:#07b}"
                              .format(self._i2c_addr))
        return list(result)

    async def write(self, addr, data):
        result = await self.lower.write(self._i2c_addr, [addr, *data])
        if not result:
            raise BMx280Error("BMx280 did not acknowledge I2C write at address {:#07b}"
                              .format(self._i2c_addr))


class SensorBMx280Applet(I2CInitiatorApplet, name="sensor-bmx280"):
    logger = logging.getLogger(__name__)
    help = "measure temperature, pressure, and humidity with Bosch BMx280 sensors"
    description = """
    Measure temperature and pressure using Bosch BMP280 sensors, or temperature, pressure,
    and humidity using Bosch BME280 sensors.

    This applet only supports sensors connected via the I²C interface.
    """

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)

        def i2c_address(arg):
            return int(arg, 0)
        parser.add_argument(
            "--i2c-address", type=i2c_address, metavar="ADDR", choices=[0x76, 0x77], default=0x76,
            help="I2C address of the sensor (one of: 0x76 0x77, default: %(default)#02x)")

    async def run(self, device, args):
        i2c_iface = await self.run_lower(SensorBMx280Applet, device, args)
        bmx280_iface = BMx280I2CInterface(i2c_iface, self.logger, args.i2c_address)
        return BMx280Interface(bmx280_iface, self.logger)

    @classmethod
    def add_interact_arguments(cls, parser):
        parser.add_argument(
            "-T", "--oversample-temperature", type=int, metavar="FACTOR",
            choices=bit_osrs_temp.keys(), default=1,
            help="oversample temperature measurements by FACTOR (default: %(default)d)")
        parser.add_argument(
            "-P", "--oversample-pressure", type=int, metavar="FACTOR",
            choices=bit_osrs_press.keys(), default=1,
            help="oversample pressure measurements by FACTOR (default: %(default)d)")
        parser.add_argument(
            "-H", "--oversample-humidity", type=int, metavar="FACTOR",
            choices=bit_osrs_hum.keys(), default=1,
            help="oversample humidity measurements by FACTOR (default: %(default)d)")
        parser.add_argument(
            "-I", "--iir-filter", type=int, metavar="COEFF",
            choices=bit_iir.keys(), default=0,
            help="use IIR filter with coefficient COEFF (default: %(default)d)")

        parser.add_argument(
            "-a", "--altitude", default=False, action="store_true", dest="report_altitude",
            help="report calculated altitude")
        parser.add_argument(
            "--sea-level-pressure", type=float, metavar="PRESSURE", default=101325,
            help="use PRESSURE Pa as sea level pressure (default: %(default)f)")

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

        p_measure = p_operation.add_parser(
            "measure", help="read measured values")

        p_log = p_operation.add_parser(
            "log", help="log measured values")
        p_log.add_argument(
            "-i", "--interval", metavar="TIME", type=float, choices=bit_t_sb.keys(), required=True,
            help="sample each TIME seconds")
        DataLogger.add_subparsers(p_log)

    async def interact(self, device, args, bmx280):
        await bmx280.reset()
        ident = await bmx280.identify()

        await bmx280.set_mode("sleep")
        await bmx280.set_iir_coefficient(args.iir_filter)
        await bmx280.set_oversample(
            ovs_t=args.oversample_temperature,
            ovs_p=args.oversample_pressure,
            ovs_h=args.oversample_humidity if bmx280.has_humidity else None)

        if args.operation == "measure":
            await bmx280.set_mode("force")

            temp_degC = await bmx280.get_temperature()
            press_Pa  = await bmx280.get_pressure()
            print("temperature : {:.0f} °C".format(temp_degC))
            print("pressure    : {:.0f} Pa".format(press_Pa))
            if args.report_altitude:
                altitude_m = await bmx280.get_altitude(p0=args.sea_level_pressure)
                print("altitude    : {:.0f} m".format(altitude_m))
            if bmx280.has_humidity:
                humidity_pct = await bmx280.get_humidity()
                print("humidity    : {:.0f}%".format(humidity_pct))

        if args.operation == "log":
            await bmx280.set_mode("normal")

            field_names = dict(t="T(°C)", p="p(Pa)")
            if args.report_altitude:
                field_names.update(h="h(m)")
            if bmx280.has_humidity:
                field_names.update(rh="RH(%)")
            data_logger = await DataLogger(self.logger, args, field_names=field_names)
            while True:
                async def report():
                    fields = dict(t=await bmx280.get_temperature(),
                                  p=await bmx280.get_pressure())
                    if args.report_altitude:
                        fields.update(h=await bmx280.get_altitude(p0=args.sea_level_pressure))
                    if bmx280.has_humidity:
                        fields.update(rh=await bmx280.get_humidity())
                    await data_logger.report_data(fields)
                try:
                    await asyncio.wait_for(report(), args.interval * 2)
                except BMx280Error as error:
                    await data_logger.report_error(str(error), exception=error)
                    await bmx280.reset()
                except asyncio.TimeoutError as error:
                    await data_logger.report_error("timeout", exception=error)
                    await bmx280.reset()
                await asyncio.sleep(args.interval)
