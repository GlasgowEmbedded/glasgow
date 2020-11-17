# Ref: https://static.docs.arm.com/ihi0031/c/IHI0031C_debug_interface_as.pdf
# Document Number: IHI0031C
# Accession: G00027

from enum import IntEnum

from ....support.bitstruct import *


__all__ = [
    "AP_IDR_addr", "AP_IDR", "AP_IDR_CLASS",
]


# IDR AP register layout

AP_IDR_addr = 0xFC

AP_IDR = bitstruct("AP_IDR", 32, [
    ("TYPE",        4),
    ("VARIANT",     4),
    (None,          5),
    ("CLASS",       4),
    ("DESIGNER",   11),
    ("REVISION",    4),
])


class AP_IDR_CLASS(IntEnum):
    NONE    = 0b0000
    COM_AP  = 0b0001
    MEM_AP  = 0b1000

    def __str__(self):
        if self == self.NONE:
            return "none"
        if self == self.COM_AP:
            return "COM-AP"
        if self == self.MEM_AP:
            return "MEM-AP"
        assert False
