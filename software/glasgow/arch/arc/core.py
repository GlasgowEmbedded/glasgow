# Ref: https://sourceware.org/binutils/docs/as/ARC_002dRegs.html
# Accession: G00016
# Ref: linux/arch/arc/include/asm/arcregs.h
# Accession: G00017

from glasgow.support.bitstruct import bitstruct


__all__ = [
    # Core AUX registers
    "AUX_IDENTITY_addr", "AUX_PC_addr", "AUX_STATUS32_addr", "AUX_STATUS32_P0_addr",
    "AUX_AUX_USER_SP_addr", "AUX_INT_VECTOR_BASE_addr",
    "AUX_STATUS32", "AUX_DEBUG", "AUX_DEBUG_addr",
    # Build configuration AUX registers
    "AUX_DCCMBASE_BCR_addr", "AUX_CRC_BCR_addr", "AUX_DVFB_BCR_addr", "AUX_EXTARITH_BCR_addr",
    "AUX_VECBASE_BCR_addr", "AUX_PERIBASE_BCR_addr", "AUX_D_UNCACH_BCR_addr", "AUX_FP_BCR_addr",
    "AUX_DPFP_BCR_addr", "AUX_MMU_BCR_addr", "AUX_DCCM_BCR_addr", "AUX_TIMERS_BCR_addr",
    "AUX_ICCM_BCR_addr", "AUX_XY_MEM_BCR_addr", "AUX_MAC_BCR_addr", "AUX_MUL_BCR_addr",
    "AUX_SWAP_BCR_addr", "AUX_NORM_BCR_addr", "AUX_MIXMAX_BCR_addr", "AUX_BARREL_BCR_addr",
]


AUX_IDENTITY_addr            = 0x04
AUX_DEBUG_addr               = 0x05
AUX_PC_addr                  = 0x06
AUX_STATUS32_addr            = 0x0a
AUX_STATUS32_P0_addr         = 0x0b
AUX_AUX_USER_SP_addr         = 0x0d
AUX_INT_VECTOR_BASE_addr     = 0x25

class AUX_DEBUG(bitstruct, width=32):
    SS: int = 1
    FH: int = 1
    _0: int = 9
    IS: int = 1
    _1: int = 10
    RA: int = 1
    ZZ: int = 1
    _2: int = 4
    UB: int = 1
    BH: int = 1
    SH: int = 1
    LD: int = 1

class AUX_STATUS32(bitstruct, width=32):
    H: int  = 1
    E1: int = 1
    E2: int = 1
    A1: int = 1
    A2: int = 1
    AE: int = 1
    DE: int = 1
    U: int  = 1
    _0: int = 4
    L: int  = 1
    _1: int = 19

# Build Configuration Registers
AUX_DCCMBASE_BCR_addr        = 0x61
AUX_CRC_BCR_addr             = 0x62
AUX_DVFB_BCR_addr            = 0x64
AUX_EXTARITH_BCR_addr        = 0x65
AUX_VECBASE_BCR_addr         = 0x68
AUX_PERIBASE_BCR_addr        = 0x69
AUX_D_UNCACH_BCR_addr        = 0x6a
AUX_FP_BCR_addr              = 0x6b
AUX_DPFP_BCR_addr            = 0x6c
AUX_MMU_BCR_addr             = 0x6f
AUX_DCCM_BCR_addr            = 0x74
AUX_TIMERS_BCR_addr          = 0x75
AUX_ICCM_BCR_addr            = 0x78
AUX_XY_MEM_BCR_addr          = 0x79
AUX_MAC_BCR_addr             = 0x7a
AUX_MUL_BCR_addr             = 0x7b
AUX_SWAP_BCR_addr            = 0x7c
AUX_NORM_BCR_addr            = 0x7d
AUX_MIXMAX_BCR_addr          = 0x7e
AUX_BARREL_BCR_addr          = 0x7f
