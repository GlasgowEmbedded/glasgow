# Ref: ARC® 700 External Interfaces Reference
# Document Number: 5117-014
# Accession: G00004

from ...support.bits import *
from ...support.bitstruct import *


__all__ = [
    # IR
    "IR_RESET_TEST", "IR_STATUS", "IR_TXN_COMMAND", "IR_ADDRESS", "IR_DATA", "IR_IDCODE",
    # DR
    "DR_STATUS",
    "DR_TXN_COMMAND_WRITE_MEMORY", "DR_TXN_COMMAND_WRITE_CORE", "DR_TXN_COMMAND_WRITE_AUX",
    "DR_TXN_COMMAND_READ_MEMORY", "DR_TXN_COMMAND_READ_CORE", "DR_TXN_COMMAND_READ_AUX",
    "DR_ADDRESS",
    "DR_DATA",
]


# IR values

IR_RESET_TEST   = bits("0010") # DR[32]
IR_STATUS       = bits("1000") # DR[4]
IR_TXN_COMMAND  = bits("1001") # DR[4]
IR_ADDRESS      = bits("1010") # DR[32]
IR_DATA         = bits("1011") # DR[32]
IR_IDCODE       = bits("1100") # DR[32]
IR_BYPASS       = bits("1111") # DR[1]

# DR values

DR_STATUS = bitstruct("DR_STATUS", 4, [
    ("ST",      1),
    ("FL",      1),
    ("RD",      1),
    ("PC_SEL",  1),
])

DR_TXN_COMMAND_WRITE_MEMORY = bits("0000")
DR_TXN_COMMAND_WRITE_CORE   = bits("0001")
DR_TXN_COMMAND_WRITE_AUX    = bits("0010")
DR_TXN_COMMAND_READ_MEMORY  = bits("0100")
DR_TXN_COMMAND_READ_CORE    = bits("0101")
DR_TXN_COMMAND_READ_AUX     = bits("0110")

DR_ADDRESS = bitstruct("DR_ADDRESS", 32, [
    ("Address", 32),
])

DR_DATA = bitstruct("DR_DATA", 32, [
    ("Data",    32),
])
