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
    # DR
    "DR_ISDATA", "DR_ISADDRESS", "DR_ISCONFIGURATION",
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


def DR_ISDATA(width):
    return bitstruct("DR_ISDATA", 2 + width, [
        ("valid",    1),
        ("strobe",   1),
        ("data", width),
    ])

DR_ISADDRESS = bitstruct("DR_ISADDRESS", 18, [
    ("valid",    1),
    ("strobe",   1),
    ("address", 16),
])

def DR_ISCONFIGURATION(width):
    return bitstruct("DR_ISCONFIGURATION", 18 + width, [
        ("valid",    1),
        ("strobe",   1),
        ("data", width),
        ("address", 16),
    ])
