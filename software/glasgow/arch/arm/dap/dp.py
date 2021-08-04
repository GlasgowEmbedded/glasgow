# Ref: https://static.docs.arm.com/ihi0031/c/IHI0031C_debug_interface_as.pdf
# Document Number: IHI0031C
# Accession: G00027

import enum

from ....support.bits import *
from ....support.bitstruct import *


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

DP_DPIDR = bitstruct("DP_DPIDR", 32, [
    ("DESIGNER",       12),
    ("VERSION",         4),
    ("MIN",             1),
    (None,              3),
    ("PARTNO",          8),
    ("REVISION",        4),
])


# ABORT DP register layout

DP_ABORT_addr = 0x00 # W/O

DP_ABORT = bitstruct("DP_ABORT", 32, [
    ("DAPABORT",        1),
    ("STKCMPCLR",       1), # only in DPv1+
    ("STKERRCLR",       1), # only in DPv1+
    ("WDERRCLR",        1), # only in DPv1+
    ("ORUNERRCLR",      1), # only in DPv1+
    (None,             27),
])


# CTRL/STAT DP register layout

DP_CTRL_STAT_addr = 0x04 # R/W

DP_CTRL_STAT = bitstruct("DP_CTRL_STAT", 32, [
    ("ORUNDETECT",      1),
    ("STICKYORUN",      1),
    ("TRNMODE",         2), # unimplemented in MINDP
    ("STICKYCMP",       1), # unimplemented in MINDP
    ("STICKYERR",       1),
    ("READOK",          1), # only in DPv1+
    ("WDATAERR",        1), # only in DPv1+, SW-DP
    ("MASKLANE",        4), # unimplemented in MINDP
    ("TRNCNT",         12), # unimplemented in MINDP
    (None,              2),
    ("CDBGRSTREQ",      1),
    ("CDBGRSTACK",      1),
    ("CDBGPWRUPREQ",    1),
    ("CDBGPWRUPACK",    1),
    ("CSYSPWRUPREQ",    1),
    ("CSYSPWRUPACK",    1),
])

class DP_TRNMODE(enum.IntEnum):
    NORMAL          = 0b00
    PUSHED_VERIFY   = 0b01
    PUSHED_COMPARE  = 0b10


# SELECT DP register layout

DP_SELECT_addr = 0x08 # R/W (only in DPv0), W/O (only in DPv1+)

DP_SELECT = bitstruct("DP_SELECT", 32, [
    ("DPBANKSEL",       4),
    ("APBANKSEL",       4),
    (None,             16),
    ("APSEL",           8),
])


# RESEND DP register layout (only in DPv1+)

DP_RESEND_addr = 0x08 # R/O


# RDBUFF DP register layout

DP_RDBUFF_addr = 0x0C # R/O


# TARGETSEL DP register layout (only in DPv2+)

DP_TARGETSEL_addr = 0x0C # W/O

DP_TARGETSEL = bitstruct("DP_TARGETSEL", 32, [
    ("present",         1),
    ("TDESIGNER",      11),
    ("TPARTNO",        16),
    ("TINSTANCE",       4),
])


# DLCR DP register layout (only in DPv1+, SW-DP)

DP_DLCR_addr = 0x14 # R/W

DP_DLCR = bitstruct("DP_DLCR", 32, [
    (None,              8),
    ("TURNROUND",       2),
    (None,             22),
])


# TARGETID DP register layout (only in DPv2+)

DP_TARGETID_addr = 0x24 # R/O

DP_TARGETID = bitstruct("DP_TARGETID", 32, [
    ("present",         1),
    ("TDESIGNER",      11),
    ("TPARTNO",        16),
    ("TREVISION",       4),
])


# DLPIDR DP register layout (only in DPv2+, SW-DP)

DP_DLPIDR_addr = 0x34 # R/O

DP_DLPIDR = bitstruct("DP_DLPIDR", 32, [
    ("PROTVSN",         4),
    (None,             24),
    ("TINSTANCE",       4),
])


# EVENTSTAT DP register layout (only in DPv2+)

DP_EVENTSTAT_addr = 0x44 # R/O

DP_EVENTSTAT = bitstruct("DP_EVENTSTAT", 32, [
    ("EA",              1),
    (None,             31),
])
