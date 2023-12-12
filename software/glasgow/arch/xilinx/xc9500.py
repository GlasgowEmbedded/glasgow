# Ref: https://prjunnamed.github.io/prjcombine/xc9500/jtag.html

from ...support.bits import *
from ...support.bitstruct import *


__all__ = [
    # IR
    "IR_EXTEST", "IR_SAMPLE", "IR_INTEST", "IR_ISPEN",
    "IR_FPGM", "IR_FPGMI", "IR_FERASE", "IR_FBULK", "IR_FVFY", "IR_FVFYI", "IR_ISPEX",
    "IR_HIGHZ", "IR_USERCODE", "IR_IDCODE", "IR_BYPASS",
    "IR_STATUS",
    # DR
    "DR_ISPENABLE", "DR_ISDATA", "DR_ISCONFIGURATION",
    "CTRL_START", "CTRL_OK", "CTRL_WPROT", "CTRL_WORKING",
    "ADDR_OVERRIDE_MAGIC",
    # bitstream geometry
    "BS_MAIN_ROWS", "BS_MAIN_COLS", "BS_UIM_ROWS", "BS_UIM_COLS",
    "bs_main_address", "bs_uim_address",
    "USERCODE_BITS", "READ_PROT_BITS", "WRITE_PROT_BIT",
    # wait times
    "WAIT_ERASE", "WAIT_PROGRAM", "WAIT_ISPEX",
]


IR_EXTEST   = bits("00000000") # BOUNDARY[..]
IR_SAMPLE   = bits("00000001") # BOUNDARY[..]
IR_INTEST   = bits("00000010") # BOUNDARY[..]
IR_ISPEN    = bits("11101000") # ISPENABLE[4+fb]
IR_FPGM     = bits("11101010") # ISCONFIGURATION[27]
IR_FPGMI    = bits("11101011") # ISDATA[10]
IR_FERASE   = bits("11101100") # ISCONFIGURATION[27]
IR_FBULK    = bits("11101101") # ISCONFIGURATION[27]
IR_FVFY     = bits("11101110") # ISCONFIGURATION[27]
IR_FVFYI    = bits("11101111") # ISDATA[10]
IR_ISPEX    = bits("11110000") # BYPASS[1]
IR_HIGHZ    = bits("11111100") # BYPASS[1]
IR_USERCODE = bits("11111101") # USERCODE[32]
IR_IDCODE   = bits("11111110") # IDCODE[32]
IR_BYPASS   = bits("11111111") # BYPASS[1]

IR_STATUS = bitstruct("IR_STATUS", 8, [
    ("_fixed1",       1),
    ("_fixed0",       1),
    ("write_protect", 1),
    ("read_protect",  1),
    ("isp_enabled",   1),
    ("done",          1),
    ("_unused",       2),
])


def DR_ISPENABLE(fbs):
    return bitstruct("DR_ISPENABLE", 4 + fbs, [
        ("fbs",    fbs),
        ("uim",      1),
        ("unknown",  3),
    ])

DR_ISDATA = bitstruct("DR_ISDATA", 10, [
    ("control", 2),
    ("data",    8),
])

DR_ISCONFIGURATION = bitstruct("DR_ISCONFIGURATION", 27, [
    ("control",  2),
    ("data",     8),
    ("address", 17),
])


CTRL_WORKING = 0
CTRL_WPROT   = 2
CTRL_START   = 2
CTRL_OK      = 3

ADDR_OVERRIDE_MAGIC = 0x1aa55


BS_MAIN_ROWS = 72
BS_MAIN_COLS = 15

BS_UIM_ROWS = 18
BS_UIM_COLS = 5

def bs_main_address(fb, row, col):
    return fb << 13 | row << 5 | (col // 5) << 3 | (col % 5)

def bs_uim_address(fb, sfb, row, col):
    return fb << 13 | 1 << 12 | sfb << 8 | row << 3 | col

USERCODE_BITS = [
    (0, 7, 7 - i // 2, 6 + i % 2) for i in range(16)
] + [
    (0, 6, 7 - i // 2, 6 + i % 2) for i in range(16)
]

WRITE_PROT_BIT = (68, 0, 6)
READ_PROT_BITS = [(11, 3, 6), (68, 3, 6)]

# Everything in µs.

# This is 1_300_000 according to ISE. However, both of my (@wanda-phi's) devices
# seem to need 2s for an erase for unknown reason. Bump it and give it a bit extra.
WAIT_ERASE = 2_500_000
WAIT_PROGRAM = 640
WAIT_ISPEX = 100
