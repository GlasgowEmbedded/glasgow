# Ref: https://static.docs.arm.com/ihi0031/c/IHI0031C_debug_interface_as.pdf
# Document Number: IHI0031C
# Accession: G00027

from enum import Enum

from ....support.bitstruct import *


__all__ = [
    "AP_IDR_addr", "AP_IDR", "AP_IDR_CLASS",
    "MEM_AP_CSW_addr", "MEM_AP_CSW", "MEM_AP_TAR_addr", "MEM_AP_DRW_addr", "MEM_AP_BD_addr",
    "MEM_AP_CFG_addr", "MEM_AP_CFG", "MEM_AP_CFG1_addr", "MEM_AP_CFG1",
    "MEM_AP_BASE_addr", "MEM_AP_BASE",
]


# Generic AP register layout

AP_IDR_addr = 0xFC

class AP_IDR(bitstruct, width=32):
    TYPE: int     = 4
    VARIANT: int  = 4
    _0: int       = 5
    CLASS: int    = 4
    DESIGNER: int = 11
    REVISION: int = 4


class AP_IDR_CLASS(Enum):
    NONE    = 0b0000
    COM_AP  = 0b0001
    MEM_AP  = 0b1000

    def __str__(self):
        match self:
            case self.NONE:
                return "none"
            case self.COM_AP:
                return "COM-AP"
            case self.MEM_AP:
                return "MEM-AP"
            case _:
                return f"{self.value:#06b}"


# MEM-AP register layout

MEM_AP_CSW_addr = 0x00

class MEM_AP_CSW(bitstruct, width=32):
    Size: int        = 3
    _0: int          = 1
    AddrInc: int     = 2
    DeviceEn: int    = 1
    TrInProg: int    = 1
    Mode: int        = 4
    Type: int        = 3
    MTE: int         = 1
    _1: int          = 7
    SPIDEN: int      = 1
    Prot: int        = 7
    DbgSwEnable: int = 1

MEM_AP_TAR_addr = 0x04

MEM_AP_DRW_addr = 0x0C

def MEM_AP_BD_addr(index: int):
    assert index in range(4)
    return 0x10 + (index << 2)

MEM_AP_CFG_addr = 0xF4

class MEM_AP_CFG(bitstruct, width=32):
    BE: int = 1
    LA: int = 1
    LD: int = 1
    _0: int = 29

MEM_AP_CFG1_addr = 0xE0

class MEM_AP_CFG1(bitstruct, width=32):
    TAG0SIZE: int = 4
    TAG0GRAN: int = 4
    _0: int       = 24

MEM_AP_BASE_addr = 0xF8

class MEM_AP_BASE(bitstruct, width=32):
    P: int        = 1
    Format: int   = 1
    _0: int       = 14
    BASEADDR: int = 16
