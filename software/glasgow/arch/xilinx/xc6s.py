# Ref: Spartan-6 FPGA Configuration User Guide
# Document Number: UG380
# Accession: G00039

# The configuration flow is unfortunately not well documented by Xilinx. For a successful flow,
# it is crucial to understand the nature of the JTAG TAP in relation to normal configuration pins.
#
# Selecting the IR opcode JPROGRAM is equivalent to asserting the PROGRAM_B pin, and observing
# the captured IR values is equivalent to sampling INIT_B and DONE pins, with the exception that
# the physical pins can be configured as open-drain, but TAP always observes logical levels inside
# the chip's configuration logic. Based on black box RE, the ISC_DONE bit corresponds to EOS output
# of the STARTUP primitive.
#
# Similarly, selecting the IR opcode CFG_IN is equivalent to driving the serial DIN pin, which is
# why the data provided on TDI is a series of 8-bit words MSB first, unlike the JTAG convention.
#
# Deasserting JPROGRAM by shifting a different opcode (such as BYPASS) is inherently racy, because
# deasserting PROGRAM_B normally starts configuration from external memory. However, JTAG has
# higher priority, and shifting in CFG_IN, CFG_OUT, JSTART or JSHUTDOWN override the normal process
# of configuring from an external source. Because of this, while polling the status of INIT_B in
# the captured IR, it is necessary to shift in one of those opcodes.

from ...support.bits import *
from ...support.bitstruct import *


__all__ = [
    # IR
    "IR_INTEST", "IR_EXTEST", "IR_SAMPLE", "IR_HIGHZ", "IR_BYPASS", "IR_IDCODE",
    "IR_USERCODE", "IR_USER1", "IR_USER2", "IR_USER3", "IR_USER4",
    "IR_CFG_OUT", "IR_CFG_IN",  "IR_JPROGRAM", "IR_JSTART", "IR_JSHUTDOWN",
    "IR_ISC_ENABLE", "IR_ISC_DISABLE", "IR_ISC_PROGRAM", "IR_ISC_READ", "IR_ISC_NOOP",
    "IR_ISC_DNA",
    "IR_CAPTURE"
]


# IR values

IR_EXTEST       = bits("001111") # BOUNDARY[3*nIO]
IR_SAMPLE       = bits("000001") # BOUNDARY[3*nIO]
IR_USER1        = bits("000010") # USER1[..]
IR_USER2        = bits("000011") # USER2[..]
IR_USER3        = bits("011010") # USER3[..]
IR_USER4        = bits("011011") # USER4[..]
IR_CFG_OUT      = bits("000100") # CONFIG[∞]
IR_CFG_IN       = bits("000101") # CONFIG[∞]
IR_INTEST       = bits("000111") # BOUNDARY[3*nIO]
IR_USERCODE     = bits("001000") # USERCODE[32]
IR_IDCODE       = bits("001001") # IDCODE[32]
IR_HIGHZ        = bits("001010") # BYPASS[1]
IR_JPROGRAM     = bits("001011") # BYPASS[1]
IR_JSTART       = bits("001100") # BYPASS[1]
IR_JSHUTDOWN    = bits("001101") # BYPASS[1]
IR_ISC_ENABLE   = bits("010000") # ISC_CONFIG[5]
IR_ISC_PROGRAM  = bits("010001") # ISC_PDATA[16]
IR_ISC_NOOP     = bits("010100") # ISC_DEFAULT[5]
IR_ISC_READ     = bits("010101") # ?
IR_ISC_DISABLE  = bits("010110") # ISC_CONFIG[5]
IR_ISC_DNA      = bits("110000") # DNA[57]
IR_BYPASS       = bits("111111") # BYPASS[1]


# Captured IR value

IR_CAPTURE = bitstruct("IR_CAPTURE", 6, [
    (None,          2),
    ("ISC_DONE",    1),
    ("ISC_ENABLED", 1),
    ("INIT_B",      1), # documented as INIT(1)
    ("DONE",        1),
])
