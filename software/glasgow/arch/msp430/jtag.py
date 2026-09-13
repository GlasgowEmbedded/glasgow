# Ref: MSP430™ Programming With the JTAG Interface
# Accession: G00038

from glasgow.support.bits import bits
from glasgow.support.bitstruct import bitstruct


__all__ = [
    # IR
    "IR_ADDR_16BIT", "IR_ADDR_CAPTURE", "IR_DATA_TO_ADDR", "IR_DATA_16BIT", "IR_DATA_QUICK",
    "IR_BYPASS", "IR_CNTRL_SIG_16BIT", "IR_CNTRL_SIG_CAPTURE", "IR_CNTRL_SIG_RELEASE",
    "IR_DATA_PSA", "IR_SHIFT_OUT_PSA", "IR_PREPARE_BLOW", "IR_EX_BLOW", "IR_JMB_EXCHANGE",
    # DR
    "DR_CNTRL_SIG_124", "DR_CNTRL_SIG_56",
]


# IR values

# Controlling the Memory Address Bus (MAB)
IR_ADDR_16BIT           = bits(0x83, 8)
IR_ADDR_CAPTURE         = bits(0x84, 8)
# Controlling the Memory Data Bus (MDB)
IR_DATA_TO_ADDR         = bits(0x85, 8)
IR_DATA_16BIT           = bits(0x41, 8)
IR_DATA_QUICK           = bits(0x43, 8)
IR_BYPASS               = bits(0xFF, 8)
# Controlling the CPU
IR_CNTRL_SIG_16BIT      = bits(0x13, 8)
IR_CNTRL_SIG_CAPTURE    = bits(0x14, 8)
IR_CNTRL_SIG_RELEASE    = bits(0x15, 8)
# Memory Verification by Pseudo Signature Analysis (PSA)
IR_DATA_PSA             = bits(0x44, 8)
IR_SHIFT_OUT_PSA        = bits(0x46, 8)
# JTAG Access Security Fuse Programming
IR_PREPARE_BLOW         = bits(0x22, 8)
IR_EX_BLOW              = bits(0x24, 8)
# JTAG Mailbox System
IR_JMB_EXCHANGE         = bits(0x61, 8)


# CNTRL_SIG DR layout

class DR_CNTRL_SIG_124(bitstruct, width=16):
    R_W: int           = 1
    _0: int            = 2
    HALT_JTAG: int     = 1
    BYTE: int          = 1
    _1: int            = 2
    INSTR_LOAD: int    = 1
    _2: int            = 1
    TCE: int           = 1
    TCE1: int          = 1
    POR: int           = 1
    RELEASE_LBYTE: int = 1
    TAGFUNCSAT: int    = 1
    SWITCH: int        = 1
    _3: int            = 1

class DR_CNTRL_SIG_56(bitstruct, width=16):
    R_W: int           = 1
    _0: int            = 2
    WAIT: int          = 1
    BYTE: int          = 1
    _1: int            = 2
    INSTR_LOAD: int    = 1
    CPUSUSP: int       = 1
    TCE: int           = 1
    TCE1: int          = 1
    POR: int           = 1
    RELEASE_LBYTE: int = 2
    INSTR_SEQ_NO: int  = 2
