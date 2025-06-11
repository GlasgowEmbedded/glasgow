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

AP_IDR = bitstruct("AP_IDR", 32, [
    ("TYPE",        4),
    ("VARIANT",     4),
    (None,          5),
    ("CLASS",       4),
    ("DESIGNER",   11),
    ("REVISION",    4),
])


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

MEM_AP_CSW = bitstruct("MEM_AP_CSW", 32, [
    ("Size",        3),
    (None,          1),
    ("AddrInc",     2),
    ("DeviceEn",    1),
    ("TrInProg",    1),
    ("Mode",        4),
    ("Type",        3),
    ("MTE",         1),
    (None,          7),
    ("SPIDEN",      1),
    (None,          7),
    ("DbgSwEnable", 1),
])

MEM_AP_TAR_addr = 0x04

MEM_AP_DRW_addr = 0x0C

def MEM_AP_BD_addr(index: int):
    assert index in range(4)
    return 0x10 + (index << 2)

MEM_AP_CFG_addr = 0xF4

MEM_AP_CFG = bitstruct("MEM_AP_CFG", 32, [
    ("BE",          1),
    ("LA",          1),
    ("LD",          1),
    (None,          29),
])

MEM_AP_CFG1_addr = 0xE0

MEM_AP_CFG1 = bitstruct("MEM_AP_CFG1", 32, [
    ("TAG0SIZE",    4),
    ("TAG0GRAN",    4),
    (None,          24),
])

MEM_AP_BASE_addr = 0xF8

MEM_AP_BASE = bitstruct("MEM_AP_BASE", 32, [
    ("P",           1),
    ("Format",      1),
    (None,          14),
    ("BASEADDR",    16),
])
