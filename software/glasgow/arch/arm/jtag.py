# Ref: https://static.docs.arm.com/ihi0031/c/IHI0031C_debug_interface_as.pdf
# Document Number: IHI0031C
# Accession: G00027

from enum import IntEnum

from ...support.bits import *
from ...support.bitstruct import *


__all__ = [
    # IR
    "IR_ABORT", "IR_DPACC", "IR_APACC", "IR_IDCODE", "IR_BYPASS",
    # DR
    "DR_xPACC_capture", "DR_xPACC_update", "DR_xPACC_ACK", "DR_ABORT",
]


# IR values

IR_ABORT    = bits("1000") # DR[35]
IR_DPACC    = bits("1010") # DR[35]
IR_APACC    = bits("1011") # DR[35]
IR_IDCODE   = bits("1110") # DR[32]
IR_BYPASS   = bits("1111") # DR[1]


# DPACC/APACC DR layout

DR_xPACC_capture = bitstruct("DR_xPACC", 35, [
    ("ACK",         3),
    ("ReadResult", 32),
])

DR_xPACC_update = bitstruct("DR_xPACC", 35, [
    ("RnW",         1),
    ("A",           2),
    ("DATAIN",     32),
])


class DR_xPACC_ACK(IntEnum):
    OK_FAULT = 0b010
    WAIT     = 0b001


# ABORT DR layout

DR_ABORT = bitstruct("DR_ABORT", 35, [
    ("RnW",         1),
    ("A",           2),
    ("ABORT",      32),
])
