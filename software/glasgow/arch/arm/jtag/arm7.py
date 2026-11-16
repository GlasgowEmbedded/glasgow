# Ref: ARM7TDMI-S Revision: r4p3 Technical Reference Manual
# Document Number: DDI 0234B
# Accession: G00093

import enum

from glasgow.support.bits import bits
from glasgow.support.bitstruct import bitstruct


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


class EICE_DBGCTL(bitstruct, width=32):
    DBGACK: int     = 1
    DBGRQ: int      = 1
    INTDIS: int     = 1
    _0: int         = 1
    Monitor_En: int = 1
    EICE_Dis: int   = 1
    _1: int         = 26


class EICE_DBGSTA(bitstruct, width=32):
    DBGACK: int = 1
    DBGRQ: int  = 1
    IFEN: int   = 1
    TRANS1: int = 1
    TBIT: int   = 1
    _0: int     = 27

class EICE_DCCCTL(bitstruct, width=32):
    R: int       = 1
    W: int       = 1
    _0: int      = 26
    Version: int = 4

class EICE_Wx_CTRL(bitstruct, width=9):
    WRITE: int  = 1
    SIZE: int   = 2
    PROT: int   = 2
    DBGEXT: int = 1
    CHAIN: int  = 1
    RANGE: int  = 1
    ENABLE: int = 1
