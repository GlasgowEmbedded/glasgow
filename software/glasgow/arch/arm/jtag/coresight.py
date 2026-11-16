# Ref: https://static.docs.arm.com/ihi0031/c/IHI0031C_debug_interface_as.pdf
# Document Number: IHI0031C
# Accession: G00027

from enum import IntEnum

from glasgow.support.bits import bits
from glasgow.support.bitstruct import bitstruct


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

class DR_xPACC_capture(bitstruct, width=35):
    ACK: int        = 3
    ReadResult: int = 32

class DR_xPACC_update(bitstruct, width=35):
    RnW: int    = 1
    A: int      = 2
    DATAIN: int = 32


class DR_xPACC_ACK(IntEnum):
    OK_FAULT = 0b010
    WAIT     = 0b001


# ABORT DR layout

class DR_ABORT(bitstruct, width=35):
    RnW: int   = 1
    A: int     = 2
    ABORT: int = 32
