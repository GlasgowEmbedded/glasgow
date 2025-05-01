# Ref: ARM7TDMI-S Revision: r4p3 Technical Reference Manual
# Document Number: DDI 0234B
# Accession: G00093

import enum

from ....support.bits import *
from ....support.bitstruct import *


__all__ = [
    # IR values
    "IR_SCAN_N", "IR_RESTART", "IR_INTEST", "IR_IDCODE", "IR_BYPASS",

    # EICE registers
    "EICE_Reg", "EICE_DBGCTL", "EICE_DBGSTA", "EICE_DCCCTL", "EICE_Wx_CTRL",
]


# IR values

IR_SCAN_N  = bits("0010")
IR_RESTART = bits("0100")
IR_INTEST  = bits("1100")
IR_IDCODE  = bits("1110")
IR_BYPASS  = bits("1111")


# EICE registers

class EICE_Reg(enum.IntEnum):
    DBGCTL = 0
    DBGSTA = 1

    DCCCTL = 4
    DCCDATA = 5

    W0_ADDR_VAL = 8
    W0_ADDR_MSK = 9
    W0_DATA_VAL = 10
    W0_DATA_MSK = 11
    W0_CTRL_VAL = 12
    W0_CTRL_MSK = 13

    W1_ADDR_VAL = 16
    W1_ADDR_MSK = 17
    W1_DATA_VAL = 18
    W1_DATA_MSK = 19
    W1_CTRL_VAL = 20
    W1_CTRL_MSK = 21

    @classmethod
    def Wx_ADDR_VAL(cls, n):
        return [cls.W0_ADDR_VAL, cls.W1_ADDR_VAL][n]

    @classmethod
    def Wx_ADDR_MSK(cls, n):
        return [cls.W0_ADDR_MSK, cls.W1_ADDR_MSK][n]

    @classmethod
    def Wx_DATA_VAL(cls, n):
        return [cls.W0_DATA_VAL, cls.W1_DATA_VAL][n]

    @classmethod
    def Wx_DATA_MSK(cls, n):
        return [cls.W0_DATA_MSK, cls.W1_DATA_MSK][n]

    @classmethod
    def Wx_CTRL_VAL(cls, n):
        return [cls.W0_CTRL_VAL, cls.W1_CTRL_VAL][n]

    @classmethod
    def Wx_CTRL_MSK(cls, n):
        return [cls.W0_CTRL_MSK, cls.W1_CTRL_MSK][n]


EICE_DBGCTL = bitstruct("EICE_DBGCTL", 32, [
    ("DBGACK",      1),
    ("DBGRQ",       1),
    ("INTDIS",      1),
    (None,          1),
    ("Monitor_En",  1),
    ("EICE_Dis",    1),
    (None,          26),
])


EICE_DBGSTA = bitstruct("EICE_DBGSTA", 32, [
    ("DBGACK",      1),
    ("DBGRQ",       1),
    ("IFEN",        1),
    ("TRANS1",      1),
    ("TBIT",        1),
    (None,          27),
])

EICE_DCCCTL = bitstruct("EICE_DCCCTL", 32, [
    ("R",           1),
    ("W",           1),
    (None,          26),
    ("Version",     4),
])

EICE_Wx_CTRL = bitstruct("EICE_Wx_CTRL", 9, [
    ("WRITE",       1),
    ("SIZE",        2),
    ("PROT",        2),
    ("DBGEXT",      1),
    ("CHAIN",       1),
    ("RANGE",       1),
    ("ENABLE",      1),
])
