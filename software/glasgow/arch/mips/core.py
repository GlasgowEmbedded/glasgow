# Ref: MIPS® Architecture For Programmers Vol. III: MIPS32® / microMIPS32™ Privileged Resource Architecture
# Document Number: MD00090 Revision 6.02
# Accession: G00020

from collections import defaultdict

from ...support.bitstruct import *


__all__ = [
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
]


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

CP0_Config = bitstruct("CP0_Config", 32, [
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

CP0_Config1 = bitstruct("CP0_Config1", 32, [
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

CP0_Debug = bitstruct("CP0_Debug", 32, [
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

CP0_Debug2 = bitstruct("CP0_Debug2", 32, [
    ("PaCo",       1),
    ("Tup",        1),
    ("DQ",         1),
    ("Prm",        1),
    (None,        28),
])
