# Ref: https://www.xilinx.com/member/forms/download/sim-model-eval-license-xef.html?filename=xc9500xl.zip
# Accession: G00015
# Ref: reverse engineering by whitequark

from ...support.bits import *
from ...support.bitstruct import *


__all__ = [
    # IR
    "IR_EXTEST", "IR_SAMPLE", "IR_INTEST", "IR_FBLANK", "IR_ISPEN", "IR_ISPENC",
    "IR_FPGM", "IR_FPGMI", "IR_FERASE", "IR_FBULK", "IR_FVFY", "IR_FVFYI", "IR_ISPEX",
    "IR_CLAMP", "IR_HIGHZ", "IR_USERCODE", "IR_IDCODE", "IR_BYPASS",
    "IR_STATUS",
    # DR
    "DR_ISDATA", "DR_ISADDRESS", "DR_ISCONFIGURATION",
    "CTRL_START", "CTRL_OK", "CTRL_WPROT", "CTRL_WORKING",
    "ADDR_OVERRIDE_MAGIC",
    # bitstream geometry
    "BS_ROWS", "BS_COLS", "bs_address",
    "USERCODE_BITS", "READ_PROT_BIT", "WRITE_PROT_BIT", "DONE_BIT",
    # wait times
    "WAIT_ERASE", "WAIT_PROGRAM", "WAIT_BLANK_CHECK", "WAIT_ISPEX",
]


IR_EXTEST   = bits("00000000") # BOUNDARY[..]
IR_SAMPLE   = bits("00000001") # BOUNDARY[..]
IR_INTEST   = bits("00000010") # BOUNDARY[..]
IR_FBLANK   = bits("11100101") # ISADDRESS[18]
IR_ISPEN    = bits("11101000") # ISPENABLE[6]
IR_ISPENC   = bits("11101001") # ISPENABLE[6]
IR_FPGM     = bits("11101010") # ISCONFIGURATION[18+w]
IR_FPGMI    = bits("11101011") # ISDATA[2+w]
IR_FERASE   = bits("11101100") # ISADDRESS[18]
IR_FBULK    = bits("11101101") # ISADDRESS[18]
IR_FVFY     = bits("11101110") # ISCONFIGURATION[18+w]
IR_FVFYI    = bits("11101111") # ISDATA[2+w]
IR_ISPEX    = bits("11110000") # BYPASS[1]
IR_CLAMP    = bits("11111010") # BYPASS[1]
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


def DR_ISDATA(fbs):
    return bitstruct("DR_ISDATA", 2 + fbs * 8, [
        ("control",    2),
        ("data", fbs * 8),
    ])

DR_ISADDRESS = bitstruct("DR_ISADDRESS", 18, [
    ("control",  2),
    ("address", 16),
])

def DR_ISCONFIGURATION(fbs):
    return bitstruct("DR_ISCONFIGURATION", 18 + fbs * 8, [
        ("control",    2),
        ("data", fbs * 8),
        ("address",   16),
    ])


CTRL_WPROT   = 0
CTRL_OK      = 1
CTRL_WORKING = 2
CTRL_START   = 3

ADDR_OVERRIDE_MAGIC = 0xaa55


BS_ROWS = 108
BS_COLS = 15

def bs_address(row, col):
    return row << 5 | (col // 5) << 3 | (col % 5)

USERCODE_BITS = [
    (0, 7, 7 - i // 2, 6 + i % 2) for i in range(16)
] + [
    (0, 6, 7 - i // 2, 6 + i % 2) for i in range(16)
]

WRITE_PROT_BIT = (11, 0, 6)
READ_PROT_BIT = (11, 3, 6)
DONE_BIT = (0, 11, 6, 6)

# Everything in µs.
WAIT_ERASE = 200_000
WAIT_PROGRAM = 20_000
WAIT_BLANK_CHECK = 500
WAIT_ISPEX = 100
