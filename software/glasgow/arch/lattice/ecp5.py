from ...support.bits import *
from ...support.bitstruct import *
from collections import namedtuple


# IR Values
IR_READ_ID             = bits("11100000")
IR_LSC_READ_STATUS     = bits("00111100")
IR_ISC_ENABLE          = bits("11000110")
IR_ISC_DISABLE         = bits("00100110")
IR_ISC_ERASE           = bits("00001110")
IR_LSC_BITSTREAM_BURST = bits("01111010")

LSC_Status_bits = bitstruct("LSC_STATUS", 32, [
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

BSEErrorCode = namedtuple("BSEErrorCode", ("code","error","error_info"))

bse_error_code = [
    BSEErrorCode(0b000, "No Error",   None                                   ),
    BSEErrorCode(0b001, "ID Error",   None                                   ),
    BSEErrorCode(0b010, "CMD Error",  "illegal command"                      ),
    BSEErrorCode(0b011, "CRC Error",  None                                   ),
    BSEErrorCode(0b100, "PRMB Error", "preamble error"                       ),
    BSEErrorCode(0b101, "ABRT Error", "configuration aborted by the user"    ),
    BSEErrorCode(0b110, "OVFL Error", "data overflow error"                  ),
    BSEErrorCode(0b111, "SDM Error",  "bitstream pass the size of SRAM array"),
]

ConfigTargetCode = namedtuple("ConfigTargetCode", ("code","target"))

config_target_code = [
    ConfigTargetCode(0b000, "SRAM"),
    ConfigTargetCode(0b001, "eFuse"),
]

class LSC_Status(LSC_Status_bits):
    def __init__(self):
        ...

    def __iter__(self):
        properties = {}
        properties["Config Target"]    = "{}".format(config_target_code[self.Config_Target])
        properties["BSE Error Code"]   = "{}".format(bse_error_code[self.BSE_Error_Code])

        return iter(properties.items())

    def BSEErrorCode(self):
        return bse_error_code[self.BSE_Error_Code]

    def flags_repl(self):
        s = ""
        for i in self:
            s += " {}".format(i)
        return s

    def __repr__(self):
        return "<{}.{} {}{}>".format(self.__module__, self.__class__.__name__, self.bits_repr(), self.flags_repl())