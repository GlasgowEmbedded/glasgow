# Ref: MIPS® EJTAG Specification
# Document Number: MD00047 Revision 6.10
# Accession: G0007

from collections import defaultdict

from glasgow.support.bits import bits
from glasgow.support.bitstruct import bitstruct


__all__ = [
    # IR
    "IR_IMPCODE", "IR_ADDRESS", "IR_DATA", "IR_CONTROL", "IR_ALL", "IR_EJTAGBOOT", "IR_NORMALBOOT",
    "IR_FASTDATA", "IR_PCSAMPLE", "IR_FDC",
    # DR
    "DR_IMPCODE", "DR_IMPCODE_EJTAGver_values",
    "DR_CONTROL",
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

IR_IMPCODE    = bits("00011")
IR_ADDRESS    = bits("01000")
IR_DATA       = bits("01001")
IR_CONTROL    = bits("01010")
IR_ALL        = bits("01011")
IR_EJTAGBOOT  = bits("01100")
IR_NORMALBOOT = bits("01101")
IR_FASTDATA   = bits("01110")
IR_PCSAMPLE   = bits("10100")
IR_FDC        = bits("10111")


# IMPCODE DR layout

class DR_IMPCODE(bitstruct, width=32):
    MIPS32_64: int = 1
    TypeInfo: int  = 10
    Type: int      = 3
    NoDMA: int     = 1
    _0: int        = 1
    MIPS16: int    = 1
    _1: int        = 4
    ASID_Size: int = 2
    _2: int        = 1
    DINT_sup: int  = 1
    _3: int        = 3
    R4k_R3k: int   = 1
    EJTAGver: int  = 3

DR_IMPCODE_EJTAGver_values = defaultdict(lambda: "unknown", {
    0: "1.x/2.0",
    1: "2.5",
    2: "2.6",
    3: "3.1",
    4: "4.0",
    5: "5.0",
})

# CONTROL DR layout

class DR_CONTROL(bitstruct, width=32):
    _0: int         = 3
    DM: int         = 1
    _1: int         = 1
    DLock: int      = 1  # Undocumented, EJTAG 1.x/2.0 specific
    _2: int         = 1
    Dsz: int        = 2  # Undocumented, EJTAG 1.x/2.0 specific
    DRWn: int       = 1  # Undocumented, EJTAG 1.x/2.0 specific
    DErr: int       = 1  # Undocumented, EJTAG 1.x/2.0 specific
    DStrt: int      = 1  # Undocumented, EJTAG 1.x/2.0 specific
    EjtagBrk: int   = 1
    ISAOnDebug: int = 1
    ProbTrap: int   = 1
    ProbEn: int     = 1
    PrRst: int      = 1
    DMAAcc: int     = 1  # Undocumented, EJTAG 1.x/2.0 specific
    PrAcc: int      = 1
    PRnW: int       = 1
    PerRst: int     = 1
    Halt: int       = 1
    Doze: int       = 1
    VPED: int       = 1
    _3: int         = 5
    Psz: int        = 2
    Rocc: int       = 1

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

class DRSEG_DCR(bitstruct, width=32):
    ProbEn: int             = 1
    SRstE: int              = 1
    NMIpend: int            = 1
    NMIE: int               = 1
    IntE: int               = 1
    PCSe: int               = 1
    PCR: int                = 3
    PCS: int                = 1
    CBT: int                = 1
    RDVec: int              = 1
    _0: int                 = 2
    IVM: int                = 1
    DVM: int                = 1
    InstBrk: int            = 1
    DataBrk: int            = 1
    FDCImpl: int            = 1
    _1: int                 = 3
    DAS: int                = 1
    DASe: int               = 1
    DASQ: int               = 1
    PCnoASID: int           = 1
    PCIM: int               = 1
    PCnoTCID: int           = 1
    PCnoGID: int            = 1
    ENM: int                = 1
    _2: int                 = 1
    EJTAG_Brk_Override: int = 1

# DRSEG IBS layout

class DRSEG_IBS(bitstruct, width=32):
    BS: int       = 15
    IBPshare: int = 1
    _0: int       = 8
    BCN: int      = 4
    _1: int       = 2
    ASIDsup: int  = 1
    _2: int       = 1

# DRSEG IBC layout

class DRSEG_IBC(bitstruct, width=32):
    BE: int      = 1
    _0: int      = 1
    TE: int      = 1
    VPEuse: int  = 1
    HWART: int   = 1
    EXCL: int    = 1
    HWARTS: int  = 1
    _1: int      = 15
    TCuse: int   = 1
    ASIDuse: int = 1
    TC: int      = 8

# DRSEG DBS layout

class DRSEG_DBS(bitstruct, width=32):
    BS: int        = 15
    DBPshare: int  = 1
    _0: int        = 8
    BCN: int       = 4
    NoLVMatch: int = 1
    NoSVMatch: int = 1
    ASIDsup: int   = 1
    _1: int        = 1

# DRSEG DBC layout

class DRSEG_DBC(bitstruct, width=32):
    BE: int      = 1
    IVM: int     = 1
    TE: int      = 1
    VPEuse: int  = 1
    BLM: int     = 8
    NoLB: int    = 1
    NoSB: int    = 1
    BAI: int     = 8
    TCuse: int   = 1
    ASIDuse: int = 1
    TC: int      = 8
