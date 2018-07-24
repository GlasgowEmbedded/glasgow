# BMP280 reference: https://ae-bst.resource.bosch.com/media/_tech/media/datasheets/BST-BMP280-DS001-19.pdf

import logging
import time

from .. import *
from ..i2c_master import I2CMasterApplet


logger = logging.getLogger(__name__)


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

REG_ID          = 0xD0 # 8-bit
BIT_ID          = 0x58

REG_RESET       = 0xE0 # 8-bit
BIT_RESET       = 0xB6

REG_STATUS      = 0xF3 # 8-bit
BIT_IM_UPDATE   = 0b00000001
BIT_MEAS        = 0b00001000

REG_CTRL_MEAS   = 0xF4 # 8-bit
BIT_OSRS_P_S    = 0b000_00000
BIT_OSRS_P_1    = 0b001_00000
BIT_OSRS_P_2    = 0b010_00000
BIT_OSRS_P_4    = 0b011_00000
BIT_OSRS_P_8    = 0b100_00000
BIT_OSRS_P_16   = 0b101_00000
BIT_OSRS_T_S    =    0b000_00
BIT_OSRS_T_1    =    0b001_00
BIT_OSRS_T_2    =    0b010_00
BIT_OSRS_T_4    =    0b011_00
BIT_OSRS_T_8    =    0b100_00
BIT_OSRS_T_16   =    0b101_00
BIT_MODE_SLEEP  =        0b00
BIT_MODE_FORCE  =        0b01
BIT_MODE_NORMAL =        0b11

bit_osrs_press = {
    1:  BIT_OSRS_P_1,
    2:  BIT_OSRS_P_2,
    4:  BIT_OSRS_P_4,
    8:  BIT_OSRS_P_8,
    16: BIT_OSRS_P_16,
}

bit_osrs_temp = {
    1:  BIT_OSRS_T_1,
    2:  BIT_OSRS_T_2,
    4:  BIT_OSRS_T_4,
    8:  BIT_OSRS_T_8,
    16: BIT_OSRS_T_16,
}

REG_CONFIG    = 0xF5 # 8-bit
BIT_T_SB      = 0b111_00000
BIT_T_SB_0_5  = 0b000_00000
BIT_T_SB_62_5 = 0b001_00000
BIT_T_SB_125  = 0b010_00000
BIT_T_SB_250  = 0b011_00000
BIT_T_SB_500  = 0b100_00000
BIT_T_SB_1000 = 0b101_00000
BIT_T_SB_2000 = 0b110_00000
BIT_T_SB_4000 = 0b111_00000
BIT_IIR       =   0b111_000
BIT_IIR_OFF   =   0b000_000
BIT_IIR_2     =   0b001_000
BIT_IIR_4     =   0b010_000
BIT_IIR_8     =   0b011_000
BIT_IIR_16    =   0b100_000

bit_iir = {
    0:  BIT_IIR_OFF,
    2:  BIT_IIR_2,
    4:  BIT_IIR_4,
    8:  BIT_IIR_8,
    16: BIT_IIR_16,
}

REG_PRESS     = 0xF7 # 20-bit unsigned
REG_TEMP      = 0xFA # 20-bit unsigned


class BMP280:
    def __init__(self, interface, logger):
        self._iface   = interface
        self._logger  = logger
        self._level   = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._has_cal = False

    def _read_reg8(self, reg):
        byte, = self._iface.read(reg, 1)
        self._logger.log(self._level, "BMP280: reg=%#02x read=%#02x",
                         reg, byte)
        return byte

    def _write_reg8(self, reg, byte):
        self._iface.write(reg, [byte])
        self._logger.log(self._level, "BMP280: reg=%#02x write=%#02x",
                         reg, byte)

    def _read_reg16u(self, reg):
        lsb, msb = self._iface.read(reg, 2)
        raw = (msb << 8) | lsb
        value = raw
        self._logger.log(self._level, "BMP280: reg=%#02x raw=%#04x read=%d", reg, raw, value)
        return value

    def _read_reg16s(self, reg):
        lsb, msb = self._iface.read(reg, 2)
        raw = (msb << 8) | lsb
        if raw & (1 << 15):
            value = -((1 << 16) - raw)
        else:
            value = raw
        self._logger.log(self._level, "BMP280: reg=%#02x raw=%#04x read=%+d", reg, raw, value)
        return value

    def _read_reg24(self, reg):
        msb, lsb, xlsb = self._iface.read(reg, 3)
        raw = ((msb << 16) | (lsb << 8) | xlsb)
        value = raw >> 4
        self._logger.log(self._level, "BMP280: reg=%#02x raw=%#06x read=%d", reg, raw, value)
        return value

    def identify(self):
        id = self._read_reg8(REG_ID)
        if id != BIT_ID:
            raise GlasgowAppletError("BMP280: wrong ID=%#02x", id)

    def _read_cal(self):
        if self._has_cal: return
        self._t1 = self._read_reg16u(REG_CAL_T1)
        self._t2 = self._read_reg16s(REG_CAL_T2)
        self._t3 = self._read_reg16s(REG_CAL_T3)
        self._p1 = self._read_reg16u(REG_CAL_P1)
        self._p2 = self._read_reg16s(REG_CAL_P2)
        self._p3 = self._read_reg16s(REG_CAL_P3)
        self._p4 = self._read_reg16s(REG_CAL_P4)
        self._p5 = self._read_reg16s(REG_CAL_P5)
        self._p6 = self._read_reg16s(REG_CAL_P6)
        self._p7 = self._read_reg16s(REG_CAL_P7)
        self._p8 = self._read_reg16s(REG_CAL_P8)
        self._p9 = self._read_reg16s(REG_CAL_P9)
        self._has_cal = True

    def set_iir_coefficient(self, coeff):
        config = self._read_reg8(REG_CONFIG)
        config = (config & ~BIT_IIR) | bit_iir[coeff]
        self._write_reg8(REG_CONFIG, config)

    def measure(self, ovs_t=2, ovs_p=16, one_shot=True):
        if one_shot:
            mode = BIT_MODE_FORCE
        else:
            mode = BIT_MODE_NORMAL
        self._write_reg8(REG_CTRL_MEAS,
            bit_osrs_temp[ovs_t] |
            bit_osrs_press[ovs_p]   |
            mode)
        time.sleep(0.050) # worst case

    def _get_temp_fine(self):
        self._read_cal()
        ut = self._read_reg24(REG_TEMP)
        x1 = (ut / 16384.0  - self._t1 / 1024.0) * self._t2
        x2 = (ut / 131072.0 - self._t1 / 8192.0) ** 2 * self._t3
        tf = x1 + x2
        return tf

    def get_temperature(self):
        tf = self._get_temp_fine()
        t  = tf / 5120.0
        return t # in °C

    def get_pressure(self):
        self._read_cal()
        tf = self._get_temp_fine()
        up = self._read_reg24(REG_PRESS)
        x1 = tf / 2.0 - 64000.0
        x2 = x1 * x1 * self._p6 / 32768.0
        x2 = x2 + x1 * self._p5 * 2
        x2 = x2 / 4.0 + self._p4 * 65536.0
        x1 = (self._p3 * x1 * x1 / 524288.0 + self._p2 * x1) / 524288.0
        x1 = (1.0 + x1 / 32768.0) * self._p1
        p  = 1048576.0 - up
        p  = (p - x2 / 4096.0) * 6250.0 / x1
        x1 = self._p9 * p * p / 2147483648.0
        x2 = p * self._p8 / 32768.0
        p  = p + (x1 + x2 + self._p7) / 16.0
        return p # in Pa

    def get_altitude(self, p0=101325):
        p  = self.get_pressure()
        h  = 44330 * (1 - (p / p0) ** (1 / 5.255))
        return h # in m


class BMP280I2CInterface:
    def __init__(self, interface, logger, i2c_address):
        self.lower     = interface
        self._i2c_addr = i2c_address

    def read(self, addr, size):
        self.lower.write(self._i2c_addr, [addr])
        result = self.lower.read(self._i2c_addr, size)
        if result is None:
            raise GlasgowAppletError("BMP280 did not acknowledge I2C read at address {:#07b}"
                                     .format(self._i2c_addr))
        return list(result)

    def write(self, addr, data):
        result = self.lower.write(self._i2c_addr, [addr, *data])
        if not result:
            raise GlasgowAppletError("BMP280 did not acknowledge I2C write at address {:#07b}"
                                     .format(self._i2c_addr))


class I2CBMP280Applet(I2CMasterApplet, name="i2c-bmp280"):
    logger = logger
    help = "measure temperature and pressure with BMP280"
    description = """
    Measure temperature and pressure using Bosch BMP280 sensor.
    """

    @classmethod
    def add_run_arguments(self, parser, access):
        super().add_run_arguments(parser, access)

        def i2c_address(arg):
            return int(arg, 0)
        parser.add_argument(
            "--i2c-address", type=i2c_address, metavar="ADDR", choices=[0x76, 0x77], default=0x76,
            help="I2C address of the sensor (one of: 0x76 0x77, default: %(default)#02x)")

        parser.add_argument(
            "-T", "--oversample-temperature", type=int, metavar="FACTOR",
            choices=bit_osrs_temp.keys(), default=2,
            help="oversample temperature measurements by FACTOR (default: %(default)d)")
        parser.add_argument(
            "-P", "--oversample-pressure", type=int, metavar="FACTOR",
            choices=bit_osrs_press.keys(), default=16,
            help="oversample pressure measurements by FACTOR (default: %(default)d)")
        parser.add_argument(
            "-I", "--iir-filter", type=int, metavar="COEFF",
            choices=bit_iir.keys(), default=0,
            help="use IIR filter with coefficient COEFF (default: %(default)d)")

        parser.add_argument(
            "-p", "--sea-level-pressure", type=float, metavar="P", default=101325,
            help="calculate absolute altitude using sea level pressure P Pa"
            " (default: %(default)f)")

        parser.add_argument(
            "-c", "--continuous", action="store_true",
            help="measure and output pressure and temperature continuously")

    def run(self, device, args):
        i2c_iface = super().run(device, args, interactive=False)
        bmp280_iface = BMP280I2CInterface(i2c_iface, self.logger, args.i2c_address)
        bmp280 = BMP280(bmp280_iface, self.logger)

        bmp280.identify()

        bmp280.set_iir_coefficient(args.iir_filter)
        bmp280.measure(ovs_p=args.oversample_pressure,
                       ovs_t=args.oversample_temperature,
                       one_shot=not args.continuous)

        if args.continuous:
            while True:
                print("T={:.2f} °C p={:.1f} Pa h={:f} m"
                      .format(bmp280.get_temperature(), bmp280.get_pressure(),
                              bmp280.get_altitude(p0=args.sea_level_pressure)))
                time.sleep(1)
        else:
            logger.info("T=%.2f °C", bmp280.get_temperature())
            logger.info("p=%.1f Pa", bmp280.get_pressure())
            logger.info("h=%f m",    bmp280.get_altitude(p0=args.sea_level_pressure))
