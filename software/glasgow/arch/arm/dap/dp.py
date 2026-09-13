# Ref: https://static.docs.arm.com/ihi0031/c/IHI0031C_debug_interface_as.pdf
# Document Number: IHI0031C
# Accession: G00027

import enum

from glasgow.support.bitstruct import bitstruct


__all__ = [
    "DP_DPIDR_addr", "DP_DPIDR",
    "DP_ABORT_addr", "DP_ABORT",
    "DP_CTRL_STAT_addr", "DP_CTRL_STAT", "DP_TRNMODE",
    "DP_SELECT_addr", "DP_SELECT",
    "DP_RESEND_addr",
    "DP_RDBUFF_addr",
    "DP_TARGETSEL_addr", "DP_TARGETSEL",
    "DP_DLCR_addr", "DP_DLCR",
    "DP_TARGETID_addr", "DP_TARGETID",
    "DP_DLPIDR_addr", "DP_DLPIDR",
    "DP_EVENTSTAT_addr", "DP_EVENTSTAT",
]


# DPIDR DP register layout (only in DPv1+)

DP_DPIDR_addr = 0x00 # R/O

class DP_DPIDR(bitstruct, width=32):
    _0: int       = 1   # always 1
    DESIGNER: int = 11
    VERSION: int  = 4
    MIN: int      = 1
    _1: int       = 3
    PARTNO: int   = 8
    REVISION: int = 4


# ABORT DP register layout

DP_ABORT_addr = 0x00 # W/O

class DP_ABORT(bitstruct, width=32):
    DAPABORT: int   = 1
    STKCMPCLR: int  = 1   # only in DPv1+
    STKERRCLR: int  = 1   # only in DPv1+
    WDERRCLR: int   = 1   # only in DPv1+
    ORUNERRCLR: int = 1   # only in DPv1+
    _0: int         = 27


# CTRL/STAT DP register layout

DP_CTRL_STAT_addr = 0x04 # R/W

class DP_CTRL_STAT(bitstruct, width=32):
    ORUNDETECT: int   = 1
    STICKYORUN: int   = 1
    TRNMODE: int      = 2   # unimplemented in MINDP
    STICKYCMP: int    = 1   # unimplemented in MINDP
    STICKYERR: int    = 1
    READOK: int       = 1   # only in DPv1+
    WDATAERR: int     = 1   # only in DPv1+, SW-DP
    MASKLANE: int     = 4   # unimplemented in MINDP
    TRNCNT: int       = 12  # unimplemented in MINDP
    _0: int           = 2
    CDBGRSTREQ: int   = 1
    CDBGRSTACK: int   = 1
    CDBGPWRUPREQ: int = 1
    CDBGPWRUPACK: int = 1
    CSYSPWRUPREQ: int = 1
    CSYSPWRUPACK: int = 1

class DP_TRNMODE(enum.IntEnum):
    NORMAL          = 0b00
    PUSHED_VERIFY   = 0b01
    PUSHED_COMPARE  = 0b10


# SELECT DP register layout

DP_SELECT_addr = 0x08 # R/W (only in DPv0), W/O (only in DPv1+)

class DP_SELECT(bitstruct, width=32):
    DPBANKSEL: int = 4
    APBANKSEL: int = 4
    _0: int        = 16
    APSEL: int     = 8


# RESEND DP register layout (only in DPv1+)

DP_RESEND_addr = 0x08 # R/O


# RDBUFF DP register layout

DP_RDBUFF_addr = 0x0C # R/O


# TARGETSEL DP register layout (only in DPv2+)

DP_TARGETSEL_addr = 0x0C # W/O

class DP_TARGETSEL(bitstruct, width=32):
    present: int   = 1
    TDESIGNER: int = 11
    TPARTNO: int   = 16
    TINSTANCE: int = 4


# DLCR DP register layout (only in DPv1+, SW-DP)

DP_DLCR_addr = 0x14 # R/W

class DP_DLCR(bitstruct, width=32):
    _0: int        = 8
    TURNROUND: int = 2
    _1: int        = 22


# TARGETID DP register layout (only in DPv2+)

DP_TARGETID_addr = 0x24 # R/O

class DP_TARGETID(bitstruct, width=32):
    present: int   = 1
    TDESIGNER: int = 11
    TPARTNO: int   = 16
    TREVISION: int = 4


# DLPIDR DP register layout (only in DPv2+, SW-DP)

DP_DLPIDR_addr = 0x34 # R/O

class DP_DLPIDR(bitstruct, width=32):
    PROTVSN: int   = 4
    _0: int        = 24
    TINSTANCE: int = 4


# EVENTSTAT DP register layout (only in DPv2+)

DP_EVENTSTAT_addr = 0x44 # R/O

class DP_EVENTSTAT(bitstruct, width=32):
    EA: int = 1
    _0: int = 31
