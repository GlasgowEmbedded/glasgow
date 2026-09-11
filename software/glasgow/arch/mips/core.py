# Ref: MIPS® Architecture For Programmers Vol. III: MIPS32® / microMIPS32™ Privileged Resource
#      Architecture
# Document Number: MD00090 Revision 6.02
# Accession: G00020

from collections import defaultdict

from glasgow.support.bitstruct import bitstruct


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

class CP0_Config(bitstruct, width=32):
    K0: int  = 3
    _0: int  = 4
    MT: int  = 3
    AR: int  = 3
    AT: int  = 2
    BE: int  = 1
    _1: int  = 9
    KU: int  = 3
    K23: int = 3
    M: int   = 1

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

class CP0_Config1(bitstruct, width=32):
    FP: int         = 1
    EP: int         = 1
    CA: int         = 1
    WR: int         = 1
    PC: int         = 1
    MD: int         = 1
    C2: int         = 1
    DA: int         = 3
    DL: int         = 3
    DS: int         = 3
    IA: int         = 3
    IL: int         = 3
    IS: int         = 3
    MMUSize_m1: int = 6
    M: int          = 1

# CP0 Debug layout

class CP0_Debug(bitstruct, width=32):
    DSS: int      = 1
    DBp: int      = 1
    DDBL: int     = 1
    DDBS: int     = 1
    DIB: int      = 1
    DINT: int     = 1
    DIBImpr: int  = 1
    OffLine: int  = 1
    SSt: int      = 1
    NoSSt: int    = 1
    DExcCode: int = 5
    EJTAGver: int = 3
    DDBLImpr: int = 1
    DDBSImpr: int = 1
    IEXI: int     = 1
    DBusEP: int   = 1
    CacheEP: int  = 1
    MCheckP: int  = 1
    IBusEP: int   = 1
    CountDM: int  = 1
    Halt: int     = 1
    Doze: int     = 1
    LSNM: int     = 1
    NoDCR: int    = 1
    DM: int       = 1
    DBD: int      = 1

# CP0 Debug2 layout

class CP0_Debug2(bitstruct, width=32):
    PaCo: int = 1
    Tup: int  = 1
    DQ: int   = 1
    Prm: int  = 1
    _0: int   = 28
