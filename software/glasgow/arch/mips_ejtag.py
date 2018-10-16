# Ref: MIPS® EJTAG Specification
# Document Number: MD00047 Revision 6.10

from collections import defaultdict
from bitarray import bitarray

from ..support.bits import *


__all__ = [
    # IR
    "IR_IMPCODE", "IR_ADDRESS", "IR_DATA", "IR_CONTROL", "IR_ALL", "IR_EJTAGBOOT", "IR_NORMALBOOT",
    "IR_FASTDATA", "IR_PCSAMPLE", "IR_FDC",
    # DR
    "DR_IMPCODE", "DR_IMPCODE_EJTAGver_values",
    "DR_CONTROL",
    # Address space
    "KUSEG_addr", "KSEG0_addr", "KSEG1_addr", "KSEG2_addr", "KSEG3_addr", "KSEGx_mask",
    # CP0
    "CP0_BadVAddr_addr", "CP0_SR_addr", "CP0_Cause_addr", "CP0_Config_addr", "CP0_Config1_addr",
    "CP0_Config2_addr", "CP0_Config3_addr", "CP0_Debug_addr", "CP0_Debug2_addr", "CP0_DEPC_addr",
    "CP0_DESAVE_addr",
    "CP0_Config", "CP0_Config_Kx_values", "CP0_Config_MT_values", "CP0_Config_AR_values",
    "CP0_Config_AT_values", "CP0_Config_BE_values",
    "CP0_Config1",
    "CP0_Debug", "CP0_Debug2",
    # DMSEG
    "DMSEG_addr", "DMSEG_mask",
    "DRSEG_addr", "DMSEG_TRAP_addr", "DRSEG_DCR_addr", "DRSEG_IBS_addr", "DRSEG_IBAn_addr",
    "DRSEG_IBMn_addr", "DRSEG_IBASIDn_addr", "DRSEG_IBCn_addr", "DRSEG_IBCCn_addr",
    "DRSEG_IBPCn_addr", "DRSEG_DBS_addr", "DRSEG_DBAn_addr", "DRSEG_DBMn_addr",
    "DRSEG_DBASIDn_addr", "DRSEG_DBCn_addr", "DRSEG_DBVn_addr", "DRSEG_DBCCn_addr",
    "DRSEG_DBPCn_addr", "DRSEG_IBS_addr_v1", "DRSEG_DBS_addr_v1", "DRSEG_IBAn_addr_v1",
    "DRSEG_IBCn_addr_v1", "DRSEG_IBMn_addr_v1", "DRSEG_DBAn_addr_v1", "DRSEG_DBCn_addr_v1",
    "DRSEG_DBMn_addr_v1", "DRSEG_DBVn_addr_v1",
    "DRSEG_DCR", "DRSEG_IBS", "DRSEG_IBC", "DRSEG_DBS", "DRSEG_DBC",
]


# IR values

IR_IMPCODE    = bitarray("11000", endian="little")
IR_ADDRESS    = bitarray("00010", endian="little")
IR_DATA       = bitarray("10010", endian="little")
IR_CONTROL    = bitarray("01010", endian="little")
IR_ALL        = bitarray("11010", endian="little")
IR_EJTAGBOOT  = bitarray("00110", endian="little")
IR_NORMALBOOT = bitarray("10110", endian="little")
IR_FASTDATA   = bitarray("01110", endian="little")
IR_PCSAMPLE   = bitarray("00101", endian="little")
IR_FDC        = bitarray("11101", endian="little")


# IMPCODE DR layout

DR_IMPCODE = Bitfield("DR_IMPCODE", 4, [
    ("MIPS32_64",  1),
    ("TypeInfo",  10),
    ("Type",       2),
    ("NoDMA",      1),
    (None,         1),
    ("MIPS16",     1),
    (None,         3),
    ("ASID_Size",  2),
    (None,         1),
    ("DINT_sup",   1),
    (None,         3),
    ("R4k_R3k",    1),
    ("EJTAGver",   3),
])

DR_IMPCODE_EJTAGver_values = defaultdict(lambda: "unknown", {
    0: "1.x/2.0",
    1: "2.5",
    2: "2.6",
    3: "3.1",
    4: "4.0",
    5: "5.0",
})

# CONTROL DR layout

DR_CONTROL = Bitfield("DR_CONTROL", 4, [
    (None,         3),
    ("DM",         1),
    (None,         1),
    ("DLock",      1), # Undocumented, EJTAG 1.x/2.0 specific
    (None,         1),
    ("Dsz",        2), # Undocumented, EJTAG 1.x/2.0 specific
    ("DRWn",       1), # Undocumented, EJTAG 1.x/2.0 specific
    ("DErr",       1), # Undocumented, EJTAG 1.x/2.0 specific
    ("DStrt",      1), # Undocumented, EJTAG 1.x/2.0 specific
    ("EjtagBrk",   1),
    ("ISAOnDebug", 1),
    ("ProbTrap",   1),
    ("ProbEn",     1),
    ("PrRst",      1),
    ("DMAAcc",     1), # Undocumented, EJTAG 1.x/2.0 specific
    ("PrAcc",      1),
    ("PRnW",       1),
    ("PerRst",     1),
    ("Halt",       1),
    ("Doze",       1),
    ("VPED",       1),
    (None,         5),
    ("Psz",        2),
    ("Rocc",       1),
])

# Address space

KUSEG_addr = 0x0000_0000_0000_0000
KSEG0_addr = 0xffff_ffff_8000_0000
KSEG1_addr = 0xffff_ffff_a000_0000
KSEG2_addr = 0xffff_ffff_c000_0000
KSEG3_addr = 0xffff_ffff_e000_0000

KSEGx_mask = 0xffff_ffff_e000_0000

# CP0 addresses

CP0_BadVAddr_addr = ( 8, 0)
CP0_SR_addr       = (12, 0)
CP0_Cause_addr    = (13, 0)
CP0_Config_addr   = (16, 0)
CP0_Config1_addr  = (16, 1)
CP0_Config2_addr  = (16, 2)
CP0_Config3_addr  = (16, 3)
CP0_Debug_addr    = (23, 0)
CP0_Debug2_addr   = (23, 6)
CP0_DEPC_addr     = (24, 0)
CP0_DESAVE_addr   = (31, 0)

# CP0 Config layout

CP0_Config = Bitfield("CP0_Config", 4, [
    ("K0",         3),
    (None,         4),
    ("MT",         3),
    ("AR",         3),
    ("AT",         2),
    ("BE",         1),
    (None,         9),
    ("KU",         3),
    ("K23",        3),
    ("M",          1),
])

CP0_Config_Kx_values = defaultdict(lambda: "unknown", {
    # Values 0/1 not defined in MIPS reference, but seem consistent among vendors
    0: "write-through write-no-allocate",
    1: "write-through write-allocate",
    2: "uncached",
    3: "write-back write-allocate",
})

CP0_Config_MT_values = defaultdict(lambda: "unknown", {
    0: "absent",
    1: "standard TLB",
    2: "standard BAT",
    3: "standard fixed",
})

CP0_Config_AR_values = defaultdict(lambda: "unknown", {
    0: "R1",
    1: "R2",
})

CP0_Config_AT_values = defaultdict(lambda: "unknown", {
    0: "MIPS32",
    1: "MIPS64 32-bit",
    2: "MIPS64 64-bit",
})

CP0_Config_BE_values = {
    0: "little",
    1: "big",
}

# CP0 Config1 layout

CP0_Config1 = Bitfield("CP0_Config1", 4, [
    ("FP",         1),
    ("EP",         1),
    ("CA",         1),
    ("WR",         1),
    ("PC",         1),
    ("MD",         1),
    ("C2",         1),
    ("DA",         3),
    ("DL",         3),
    ("DS",         3),
    ("IA",         3),
    ("IL",         3),
    ("IS",         3),
    ("MMUSize_m1", 6),
    ("M",          1),
])

# CP0 Debug layout

CP0_Debug = Bitfield("CP0_Debug", 4, [
    ("DSS",        1),
    ("DBp",        1),
    ("DDBL",       1),
    ("DDBS",       1),
    ("DIB",        1),
    ("DINT",       1),
    ("DIBImpr",    1),
    ("OffLine",    1),
    ("SSt",        1),
    ("NoSSt",      1),
    ("DExcCode",   5),
    ("EJTAGver",   3),
    ("DDBLImpr",   1),
    ("DDBSImpr",   1),
    ("IEXI",       1),
    ("DBusEP",     1),
    ("CacheEP",    1),
    ("MCheckP",    1),
    ("IBusEP",     1),
    ("CountDM",    1),
    ("Halt",       1),
    ("Doze",       1),
    ("LSNM",       1),
    ("NoDCR",      1),
    ("DM",         1),
    ("DBD",        1),
])

# CP0 Debug2 layout

CP0_Debug2 = Bitfield("CP0_Debug2", 4, [
    ("PaCo",       1),
    ("Tup",        1),
    ("DQ",         1),
    ("Prm",        1),
])

# DMSEG/DRSEG addresses

DMSEG_addr          = 0xffff_ffff_ff20_0000
DRSEG_addr          = 0xffff_ffff_ff30_0000
DMSEG_mask          = 0xffff_ffff_ffe0_0000

DMSEG_TRAP_addr     = DMSEG_addr + 0x0200
DRSEG_DCR_addr      = DRSEG_addr + 0x0000

# DRSEG addresses in EJTAG 2.5+

DRSEG_IBS_addr      = DRSEG_addr + 0x1000
def DRSEG_IBAn_addr(n):     return DRSEG_addr + 0x1100 + 0x100 * n
def DRSEG_IBMn_addr(n):     return DRSEG_addr + 0x1108 + 0x100 * n
def DRSEG_IBASIDn_addr(n):  return DRSEG_addr + 0x1110 + 0x100 * n
def DRSEG_IBCn_addr(n):     return DRSEG_addr + 0x1118 + 0x100 * n
def DRSEG_IBCCn_addr(n):    return DRSEG_addr + 0x1120 + 0x100 * n
def DRSEG_IBPCn_addr(n):    return DRSEG_addr + 0x1128 + 0x100 * n

DRSEG_DBS_addr      = DRSEG_addr + 0x2000
def DRSEG_DBAn_addr(n):     return DRSEG_addr + 0x2100 + 0x100 * n
def DRSEG_DBMn_addr(n):     return DRSEG_addr + 0x2108 + 0x100 * n
def DRSEG_DBASIDn_addr(n):  return DRSEG_addr + 0x2110 + 0x100 * n
def DRSEG_DBCn_addr(n):     return DRSEG_addr + 0x2118 + 0x100 * n
def DRSEG_DBVn_addr(n):     return DRSEG_addr + 0x2120 + 0x100 * n
def DRSEG_DBCCn_addr(n):    return DRSEG_addr + 0x2128 + 0x100 * n
def DRSEG_DBPCn_addr(n):    return DRSEG_addr + 0x2130 + 0x100 * n

# DRSEG addresses in EJTAG 1.x/2.0

DRSEG_IBS_addr_v1   = DRSEG_addr + 0x0004
DRSEG_DBS_addr_v1   = DRSEG_addr + 0x0008

def DRSEG_IBAn_addr_v1(n):  return DRSEG_addr + 0x0100 +  0x10 * n
def DRSEG_IBCn_addr_v1(n):  return DRSEG_addr + 0x0104 +  0x10 * n
def DRSEG_IBMn_addr_v1(n):  return DRSEG_addr + 0x0108 +  0x10 * n

def DRSEG_DBAn_addr_v1(n):  return DRSEG_addr + 0x0200 +  0x10 * n
def DRSEG_DBCn_addr_v1(n):  return DRSEG_addr + 0x0204 +  0x10 * n
def DRSEG_DBMn_addr_v1(n):  return DRSEG_addr + 0x0208 +  0x10 * n
def DRSEG_DBVn_addr_v1(n):  return DRSEG_addr + 0x020c +  0x10 * n

# DRSEG DCR layout

DRSEG_DCR = Bitfield("DRSEG_DCR", 4, [
    ("ProbEn",     1),
    ("SRstE",      1),
    ("NMIpend",    1),
    ("NMIE",       1),
    ("IntE",       1),
    ("PCSe",       1),
    ("PCR",        3),
    ("PCS",        1),
    ("CBT",        1),
    ("RDVec",      1),
    (None,         2),
    ("IVM",        1),
    ("DVM",        1),
    ("InstBrk",    1),
    ("DataBrk",    1),
    ("FDCImpl",    1),
    (None,         3),
    ("DAS",        1),
    ("DASe",       1),
    ("DASQ",       1),
    ("PCnoASID",   1),
    ("PCIM",       1),
    ("PCnoTCID",   1),
    ("PCnoGID",    1),
    ("ENM",        1),
    (None,         1),
    ("EJTAG_Brk_Override", 1),
])

# DRSEG IBS layout

DRSEG_IBS = Bitfield("DRSEG_IBS", 4, [
    ("BS",        15),
    ("IBPshare",   1),
    (None,         8),
    ("BCN",        4),
    (None,         2),
    ("ASIDsup",    1),
    (None,         1),
])

# DRSEG IBC layout

DRSEG_IBC = Bitfield("DRSEG_IBC", 4, [
    ("BE",         1),
    (None,         1),
    ("TE",         1),
    ("VPEuse",     1),
    ("HWART",      1),
    ("EXCL",       1),
    ("HWARTS",     1),
    (None,        15),
    ("TCuse",      1),
    ("ASIDuse",    1),
    ("TC",         8),
])

# DRSEG DBS layout

DRSEG_DBS = Bitfield("DRSEG_DBS", 4, [
    ("BS",        15),
    ("DBPshare",   1),
    (None,         8),
    ("BCN",        4),
    ("NoLVMatch",  1),
    ("NoSVMatch",  1),
    ("ASIDsup",    1),
    (None,         1),
])

# DRSEG DBC layout

DRSEG_DBC = Bitfield("DRSEG_DBC", 4, [
    ("BE",         1),
    ("IVM",        1),
    ("TE",         1),
    ("VPEuse",     1),
    ("BLM",        8),
    ("NoLB",       1),
    ("NoSB",       1),
    ("BAI",        8),
    ("TCuse",      1),
    ("ASIDuse",    1),
    ("TC",         8),
])
