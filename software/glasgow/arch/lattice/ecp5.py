# Ref: FPGA-TN-02039 ECP5 and ECP5-5G sysCONFIG Usage Guide
# Ref: https://www.latticesemi.com/-/media/LatticeSemi/Documents/ApplicationNotes/EH/FPGA-TN-02039-1-7-ECP5-and-ECP5-5G-sysCONFIG.pdf
# Accession: G00087

import enum

from ...support.bits import *
from ...support.bitstruct import *


__all__ = [
    # IR values
    "IR_IDCODE", "IR_LSC_READ_STATUS", "IR_ISC_ENABLE", "IR_ISC_DISABLE", "IR_ISC_ERASE",
    "IR_LSC_BITSTREAM_BURST",
    # DR structures
    "Config_Target", "BSE_Error_Code", "LSC_Status",
]


# IR values (ascending numeric order)
# XXX: where did these values come from?
IR_ISC_ERASE           = bits("00001110")
IR_ISC_DISABLE         = bits("00100110")
IR_LSC_READ_STATUS     = bits("00111100")
IR_LSC_BITSTREAM_BURST = bits("01111010")
IR_ISC_ENABLE          = bits("11000110")
IR_IDCODE              = bits("11100000")


# Lattice status register
class Config_Target(enum.IntEnum):
    SRAM  = 0b000
    eFuse = 0b001


class BSE_Error_Code(enum.IntEnum):
    No_error   = 0b000
    ID_error   = 0b001
    CMD_error  = 0b010
    CRC_error  = 0b011
    PRMB_error = 0b100
    ABRT_error = 0b101
    OVFL_error = 0b110
    SDM_error  = 0b111

    @property
    def explanation(self):
        if self == self.No_error:
            return "success"
        if self == self.ID_error:
            return "IDCODE mismatch"
        if self == self.CMD_error:
            return "illegal command"
        if self == self.CRC_error:
            return "checksum error"
        if self == self.ABRT_error:
            return "configuration aborted"
        if self == self.OVFL_error:
            return "data overflow error"
        if self == self.SDM_error:
            return "bitstream past the size of SRAM array"


LSC_Status = bitstruct("LSC_Status", 32, [
    ("Transparent_Mode", 1),
    ("Config_Target",    3),
    ("JTAG_Active",      1),
    ("PWD_Protection",   1),
    (None,               1), # Not used
    ("Decrypt_Enable",   1),
    ("DONE",             1),
    ("ISC_Enable",       1),
    ("Write_Enable",     1),
    ("Read_Enable",      1),
    ("Busy_Flag",        1),
    ("Fail_Flag",        1),
    ("FEA_OTP",          1),
    ("Decrypt_Only",     1),
    ("PWD_Enable",       1),
    (None,               3), # Not used
    ("Encrypt_Preamble", 1),
    ("Std_Preamble",     1),
    ("SPIm_Fail_1",      1),
    ("BSE_Error_Code",   3),
    ("Execution_Error",  1),
    ("ID_Error",         1),
    ("Invalid_Command",  1),
    ("SED_Error",        1),
    ("Bypass_Mode",      1),
    ("Flow_Through_Mode",1),
])
