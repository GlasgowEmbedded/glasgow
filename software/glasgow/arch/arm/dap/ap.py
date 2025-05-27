# Ref: https://static.docs.arm.com/ihi0031/c/IHI0031C_debug_interface_as.pdf
# Document Number: IHI0031C
# Accession: G00027

from enum import Enum

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
