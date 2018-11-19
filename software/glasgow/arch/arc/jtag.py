# Ref: ARC® 700 External Interfaces Reference
# Document Number: 5117-014

from bitarray import bitarray

from ...support.bits import *


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

IR_RESET_TEST   = bitarray("0100", endian="little") # DR[32]
IR_STATUS       = bitarray("0001", endian="little") # DR[4]
IR_TXN_COMMAND  = bitarray("1001", endian="little") # DR[4]
IR_ADDRESS      = bitarray("0101", endian="little") # DR[32]
IR_DATA         = bitarray("1101", endian="little") # DR[32]
IR_IDCODE       = bitarray("0011", endian="little") # DR[32]
IR_BYPASS       = bitarray("1111", endian="little") # DR[1]

# DR values

DR_STATUS = Bitfield("DR_STATUS", 1, [
    ("ST",      1),
    ("FL",      1),
    ("RD",      1),
    ("PC_SEL",  1),
])

DR_TXN_COMMAND_WRITE_MEMORY = bitarray("0000", endian="little")
DR_TXN_COMMAND_WRITE_CORE   = bitarray("1000", endian="little")
DR_TXN_COMMAND_WRITE_AUX    = bitarray("0100", endian="little")
DR_TXN_COMMAND_READ_MEMORY  = bitarray("0010", endian="little")
DR_TXN_COMMAND_READ_CORE    = bitarray("1010", endian="little")
DR_TXN_COMMAND_READ_AUX     = bitarray("0110", endian="little")

DR_ADDRESS = Bitfield("DR_ADDRESS", 4, [
    ("Address", 32),
])

DR_DATA = Bitfield("DR_DATA", 4, [
    ("Data",    32),
])
