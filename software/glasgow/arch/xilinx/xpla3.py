# Ref: https://prjunnamed.github.io/prjcombine/xpla3/jtag.html

from ...support.bits import *
from ...support.bitstruct import *

__all__ = [
    "MFG_PHILIPS", "MFG_XILINX",
    # IR
    "IR_EXTEST", "IR_IDCODE", "IR_SAMPLE", "IR_INTEST", "IR_STRTEST", 
    "IR_HIGHZ", "IR_CLAMP", "IR_ISP_WRITE", "IR_ISP_EOTF", "IR_ISP_ENABLE",
    "IR_ISP_ERASE", "IR_ISP_PROGRAM", "IR_ISP_VERIFY", "IR_ISP_INIT",
    "IR_ISP_READ", "IR_ISP_DISABLE", "IR_TEST_MODE", "IR_BYPASS",
    # DR
    "DR_MISR",
    # bits
    "FB_BITS", "MC_BITS_IOB", "MC_BITS_BURIED",
]

MFG_PHILIPS = 0x15
MFG_XILINX  = 0x49

IR_EXTEST      = bits("00000") # BOUNDARY[..]
IR_IDCODE      = bits("00001") # IDCODE[32]
IR_SAMPLE      = bits("00010") # BOUNDARY[..]
IR_INTEST      = bits("00011") # BOUNDARY[..]
IR_STRTEST     = bits("00100") # BOUNDARY[..]
IR_HIGHZ       = bits("00101") # BYPASS[1]
IR_CLAMP       = bits("00110") # BYPASS[1]
IR_ISP_WRITE   = bits("00111") # MISR[..]
IR_ISP_EOTF    = bits("01000") # MISR[..]
IR_ISP_ENABLE  = bits("01001") # MISR[..]
IR_ISP_ERASE   = bits("01010") # MISR[..]
IR_ISP_PROGRAM = bits("01011") # MISR[..]
IR_ISP_VERIFY  = bits("01100") # MISR[..]
IR_ISP_INIT    = bits("01101") # MISR[..]
IR_ISP_READ    = bits("01110") # MISR[..]
IR_ISP_DISABLE = bits("10000") # MISR[..]
IR_TEST_MODE   = bits("10001") # MISR[..]
IR_BYPASS      = bits("11111") # BYPASS[1]


def DR_MISR(columns, rows):
    row_bits = (rows - 1).bit_length()
    return bitstruct("DR_MISR", row_bits + 1 + columns, [
        ("data",  columns),
        ("plane",       1),
        ("row",  row_bits),
    ])


FB_BITS = [
        (2, 0, 0), # FCLK_MUX[0]
        (2, 0, 1), # FCLK_MUX[1]
        (2, 0, 2), # FCLK_MUX[2]
        (2, 0, 3), # FCLK_MUX[3]
        (0, 0, 0), # LCT0_INV[0]
        (0, 0, 1), # LCT1_INV[0]
        (0, 0, 2), # LCT2_INV[0]
        (0, 0, 3), # LCT3_INV[0]
        (1, 0, 0), # LCT4_INV[0]
        (1, 0, 1), # LCT5_INV[0]
        (1, 0, 2), # LCT6_INV[0]
        (1, 0, 3), # LCT7_INV[0]
]

MC_BITS_IOB = [
        (0, 1, 4), # MC_IOB_MUX[0]
        (0, 1, 0), # LUT[0]
        (0, 1, 1), # LUT[1]
        (0, 1, 2), # LUT[2]
        (0, 1, 3), # LUT[3]
        (0, 0, 0), # IOB_SLEW[0]
        (0, 0, 1), # OE_MUX[0]
        (0, 0, 2), # OE_MUX[1]
        (0, 0, 3), # OE_MUX[2]
        (1, 1, 3), # CE_MUX[0]
        (1, 1, 4), # CLK_INV[0]
        (1, 1, 0), # CLK_MUX[0]
        (1, 1, 1), # CLK_MUX[1]
        (1, 1, 2), # CLK_MUX[2]
        (1, 0, 0), # REG_D_IREG[0]
        (1, 0, 1), # REG_D_SHIFT_DIR[0]
        (1, 0, 3), # REG_D_SHIFT[0]
        (1, 0, 2), # IOB_ZIA_MUX[0]
        (2, 1, 0), # RST_MUX[0]
        (2, 1, 1), # RST_MUX[1]
        (2, 1, 2), # RST_MUX[2]
        (2, 0, 0), # SET_MUX[0]
        (2, 0, 1), # SET_MUX[1]
        (2, 0, 2), # SET_MUX[2]
        (2, 1, 3), # REG_MODE[0]
        (2, 1, 4), # REG_MODE[1]
        (2, 0, 3), # MC_ZIA_MUX[0]
]

MC_BITS_BURIED = [
        (0, 1, 0), # LUT[0]
        (0, 1, 1), # LUT[1]
        (0, 1, 2), # LUT[2]
        (0, 1, 3), # LUT[3]
        (1, 1, 3), # CE_MUX[0]
        (1, 1, 4), # CLK_INV[0]
        (1, 1, 0), # CLK_MUX[0]
        (1, 1, 1), # CLK_MUX[1]
        (1, 1, 2), # CLK_MUX[2]
        (1, 0, 0), # REG_D_IREG[0]
        (1, 0, 1), # REG_D_SHIFT_DIR[0]
        (1, 0, 3), # REG_D_SHIFT[0]
        (2, 1, 0), # RST_MUX[0]
        (2, 1, 1), # RST_MUX[1]
        (2, 1, 2), # RST_MUX[2]
        (2, 0, 0), # SET_MUX[0]
        (2, 0, 1), # SET_MUX[1]
        (2, 0, 2), # SET_MUX[2]
        (2, 1, 3), # REG_MODE[0]
        (2, 1, 4), # REG_MODE[1]
        (2, 0, 3), # MC_ZIA_MUX[0]
]
