# Ref: IEEE Std 802.3-2018 §22.2.2.14, §22.3.4, §45
# Accession: G00098

from amaranth.lib import enum

from ..support.bitstruct import bitstruct


__all__ = [
    "REG_BASIC_CONTROL_addr", "REG_BASIC_CONTROL", "REG_BASIC_STATUS_addr", "REG_BASIC_STATUS",
    "REG_PHY_ID1_addr", "REG_PHY_ID1", "REG_PHY_ID2_addr", "REG_PHY_ID2",
    "MMD_FNCTN", "MMD_DEVAD", "REG_MMDCTRL_addr", "REG_MMDCTRL", "REG_MMDAD_addr"
]


REG_BASIC_CONTROL_addr  = 0x00
class REG_BASIC_CONTROL(bitstruct, width=16):
    _0: int        = 6
    SPD_SEL_1: int = 1
    COLTST: int    = 1
    DUPLEXMD: int  = 1
    REAUTONEG: int = 1
    ISOLATE: int   = 1
    PD: int        = 1
    AUTONEGEN: int = 1
    SPD_SEL_0: int = 1
    LOOPBACK: int  = 1
    SW_RESET: int  = 1


REG_BASIC_STATUS_addr   = 0x01
class REG_BASIC_STATUS(bitstruct, width=16):
    EXTCAPA: int       = 1
    JABDET: int        = 1
    LNKSTS: int        = 1
    AUTONEGA: int      = 1
    RMTFLTD: int       = 1
    AUTONEGC: int      = 1
    MFPRESUPA: int     = 1
    _0: int            = 1
    EXTSTS: int        = 1
    cap_100BT2HDA: int = 1
    cap_100BT2FDA: int = 1
    cap_10BTHDA: int   = 1
    cap_10BTFDA: int   = 1
    cap_100BTXHDA: int = 1
    cap_100BTXFDA: int = 1
    cap_100BT4A: int   = 1


REG_PHY_ID1_addr = 0x02
class REG_PHY_ID1(bitstruct, width=16):
    OUI_2_17: int = 16


REG_PHY_ID2_addr = 0x03
class REG_PHY_ID2(bitstruct, width=16):
    REV: int       = 4
    MODEL: int     = 6
    OUI_18_23: int = 6


class MMD_FNCTN(enum.Enum, shape=2):
    Address      = 0b00
    Data_NoInc   = 0b01
    Data_RdWrInc = 0b10
    Data_WrInc   = 0b11


class MMD_DEVAD(enum.Enum, shape=5):
    PMA_PMD      = 0b00001
    PCS          = 0b00011
    # ...
    Clause22_Ext = 0b11101
    Vendor_1     = 0b11110
    Vendor_2     = 0b11111


REG_MMDCTRL_addr = 0x0D
class REG_MMDCTRL(bitstruct, width=16):
    DEVAD: int = 5
    _0: int    = 9
    FNCTN: int = 2


REG_MMDAD_addr   = 0x0E
