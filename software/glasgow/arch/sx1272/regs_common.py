# Ref: SX1272 Datasheet
# Accession: G00051

import enum

from ...support.bitstruct import *


__all__ = [
    # Command opcodes
    "OP_R_REGISTER", "OP_W_REGISTER",
    # Register addresses
    "ADDR_FIFO", "ADDR_F_RF_MSB", "ADDR_F_RF_MID",
    "ADDR_F_RF_LSB", "ADDR_PA_CONFIG", "ADDR_PA_RAMP", "ADDR_OCP",
    "ADDR_LNA", "ADDR_DIO_MAPPING_1", "ADDR_DIO_MAPPING_2", "ADDR_VERSION",
    "ADDR_AGC_REF", "ADDR_AGC_THRESH_1", "ADDR_AGC_THRESH_2",
    "ADDR_AGC_THRESH_3", "ADDR_PLL_HOP", "ADDR_TCXO", "ADDR_PA_DAC",
    "ADDR_PLL", "ADDR_PLL_LOW_PN", "ADDR_PA_MANUAL", "ADDR_FORMER_TEMP",
    "ADDR_BIT_RATE_FRAC",
    # Registers
    "REG_PA_CONFIG", "REG_PA_RAMP", "REG_OCP", "REG_LNA",
    "REG_DIO_MAPPING_1", "REG_DIO_MAPPING_2", "REG_VERSION", "REG_AGC_REF",
    "REG_AGC_THRESH_1", "REG_AGC_THRESH_2", "REG_AGC_THRESH_3",
    "REG_PLL_HOP", "REG_TCXO", "REG_PA_DAC", "REG_PLL", "REG_PLL_LOW_PN",
    "REG_PA_MANUAL", "REG_BIT_RATE_FRAC",
    # Enumerations
    "PASELECT", "LOWPLLTX", "PARAMP", "LNAGAIN", "LNABOOST",
    "MAPPREAMBLEDETECT", "FASTHOP", "TCXOINPUT", "PADAC", "PLLBW"
]

# Command opcodes

OP_R_REGISTER           = 0b0_0000000
OP_W_REGISTER           = 0b1_0000000

# Register addresses

ADDR_FIFO                    = 0x00
ADDR_F_RF_MSB                = 0x06
ADDR_F_RF_MID                = 0x07
ADDR_F_RF_LSB                = 0x08
ADDR_PA_CONFIG               = 0x09
ADDR_PA_RAMP                 = 0x0A
ADDR_OCP                     = 0x0B
ADDR_LNA                     = 0x0C
ADDR_DIO_MAPPING_1           = 0x40
ADDR_DIO_MAPPING_2           = 0x41
ADDR_VERSION                 = 0x42
ADDR_AGC_REF                 = 0x43
ADDR_AGC_THRESH_1            = 0x44
ADDR_AGC_THRESH_2            = 0x45
ADDR_AGC_THRESH_3            = 0x46
ADDR_PLL_HOP                 = 0x4B
ADDR_TCXO                    = 0x58
ADDR_PA_DAC                  = 0x5A
ADDR_PLL                     = 0x5C
ADDR_PLL_LOW_PN              = 0x5E
ADDR_PA_MANUAL               = 0x63
ADDR_FORMER_TEMP             = 0x6C
ADDR_BIT_RATE_FRAC           = 0x70

class PASELECT(enum.IntEnum):
    _RFO = 0b0
    _PA_BOOST = 0b1

REG_PA_CONFIG = bitstruct("REG_PA_CONFIG", 8, [
    ("OUT_POWER", 4),
    (None, 3),
    ("PA_SELECT", 1)
])

class LOWPLLTX(enum.IntEnum):
    _LOW_TX_STD_RX = 0b0
    _STD_TX_RX = 0b1

class PARAMP(enum.IntEnum):
    _3400_us = 0b0000
    _2000_us = 0b0001
    _1000_us = 0b0010
    _500_us = 0b0011
    _250_us = 0b0100
    _125_us = 0b0101
    _100_us = 0b0110
    _62_us = 0b0111
    _50_us = 0b1000
    _42_us = 0b1001
    _31_us = 0b1010
    _25_us = 0b1011
    _20_us = 0b1100
    _15_us = 0b1101
    _12_us = 0b1110
    _10_us = 0b1111

REG_PA_RAMP = bitstruct("REG_PA_RAMP", 8, [
    ("PA_RAMP", 4),
    ("LOW_PN_TX_PLL_OFF", 1),
    (None, 3)
])

REG_OCP = bitstruct("REG_OCP", 8, [
    ("OCP_TRIM", 5),
    ("OCP_ON", 1),
    (None, 2)
])

class LNAGAIN(enum.IntEnum):
    _G1 = 0b001
    _G2 = 0b010
    _G3 = 0b011
    _G4 = 0b100
    _G5 = 0b101
    _G6 = 0b110

class LNABOOST(enum.IntEnum):
    _DEFAULT = 0b00
    _IMPROVED = 0b11

REG_LNA = bitstruct("REG_LNA", 8, [
    ("LNA_BOOST", 2),
    (None, 3),
    ("LNA_GAIN", 3)
])

REG_DIO_MAPPING_1 = bitstruct("REG_DIO_MAPPING_1", 8, [
    ("DIO_3_MAPPING", 2),
    ("DIO_2_MAPPING", 2),
    ("DIO_1_MAPPING", 2),
    ("DIO_0_MAPPING", 2)
])

class MAPPREAMBLEDETECT(enum.IntEnum):
    _RSSI_INT = 0b0
    _PREAMBLE_INT = 0b1

REG_DIO_MAPPING_2 = bitstruct("REG_DIO_MAPPING_2", 8, [
    ("MAP_PREAMBLE_DETECT", 1),
    (None, 3),
    ("DIO_5_MAPPING", 2),
    ("DIO_4_MAPPING", 2)
])

REG_VERSION = bitstruct("REG_VERSION", 8, [
    ("METAL_MASK_REVISION", 4),
    ("FULL_REVISION", 4)
])

REG_AGC_REF = bitstruct("REG_AGC_REF", 8, [
    ("AGC_REF_LEVEL", 6),
    (None, 2)
])

REG_AGC_THRESH_1 = bitstruct("REG_AGC_THRESH_1", 8, [
    ("AGC_STEP_1", 5),
    (None, 3)
])

REG_AGC_THRESH_2 = bitstruct("REG_AGC_THRESH_2", 8, [
    ("AGC_STEP_3", 4),
    ("AGC_STEP_2", 4)
])

REG_AGC_THRESH_3 = bitstruct("REG_AGC_THRESH_3", 8, [
    ("AGC_STEP_5", 4),
    ("AGC_STEP_4", 4)
])

class FASTHOP(enum.IntEnum):
    _FSTX_FSRX = 0b0
    _FRF_LSB = 0b1

REG_PLL_HOP = bitstruct("REG_PLL_HOP", 8, [
    ("PA_MANUAL_DUTY_CYCLE", 4),
    (None, 3),
    ("FAST_HOP_ON", 1)
])

class TCXOINPUT(enum.IntEnum):
    _EXT_XTAL = 0b0
    _EXT_SINE = 0b1

REG_TCXO = bitstruct("REG_TCXO", 8, [
    (None, 4),
    ("TCXO_INPUT_ON", 1),
    (None, 3)
])

class PADAC(enum.IntEnum):
    _DEFAULT = 0x04
    _20_dBm = 0x07

REG_PA_DAC = bitstruct("REG_PA_DAC", 8, [
    ("PA_DAC", 3),
    (None, 5)
])

class PLLBW(enum.IntEnum):
    _75_kHz = 0b00
    _150_kHz = 0b01
    _225_kHz = 0b10
    _300_kHz = 0b11

REG_PLL = bitstruct("REG_PLL", 8, [
    (None, 6),
    ("PLL_BANDWIDTH", 2)
])

REG_PLL_LOW_PN = bitstruct("REG_PLL_LOW_PN", 8, [
    (None, 6),
    ("PLL_BANDWIDTH", 2)
])

REG_PA_MANUAL = bitstruct("REG_PA_MANUAL", 8, [
    (None, 4),
    ("MANUAL_PA_CONTROL", 1),
    (None, 3)
])

REG_BIT_RATE_FRAC = bitstruct("REG_BIT_RATE_FRAC", 8, [
    ("BIT_RATE_FRAC", 4),
    (None, 4)
])