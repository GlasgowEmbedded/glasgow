# Ref: Intel® Low Pin Count (LPC) Interface Specification
# Document Number: 251289-001
# Accession: G00019

# Transaction format summary. Derived from chapters 5-7 of the specification. Note that
# the specification has plenty of typos, which have been (hopefully) corrected here.
#
# Target cycles
# -------------
#
# Memory read (peripheral driving DATA):
#  START | CYCTYPE+DIR | ADDR[8] |  TAR[2] | SYNC[n] | DATA[2] | TAR[2]
# I/O read (peripheral driving DATA):
#  START | CYCTYPE+DIR | ADDR[4] |  TAR[2] | SYNC[n] | DATA[2] | TAR[2]
# Memory write (host driving DATA):
#  START | CYCTYPE+DIR | ADDR[8] | DATA[2] |  TAR[2] | SYNC[n] | TAR[2]
# I/O write (host driving DATA):
#  START | CYCTYPE+DIR | ADDR[4] | DATA[2] |  TAR[2] | SYNC[n] | TAR[2]
#
# Firmware cycles
# ---------------
# Firmware memory read (peripheral driving DATA):
#  START | IDSEL | ADDR[7] | MSIZE |   TAR[2] | SYNC[n] | DATA[2m]
# Firmware memory write (host driving DATA):
#  START | IDSEL | ADDR[7] | MSIZE | DATA[2m] | SYNC[n] |   TAR[2]
#
# DMA cycles
# ----------
# DMA read (host driving DATA):
#  START | CYCTYPE+DIR | CHANNEL | SIZE | ( DATA[2] | TAR[2] | SYNC | TAR[2] )[m]
# DMA write (peripheral driving DATA):
#  START | CYCTYPE+DIR | CHANNEL | SIZE | TAR[2] | ( SYNC | DATA[2] )[m] | TAR[2]
#
# Bus master cycles
# -----------------
# Memory read (host driving DATA):
#  START | TAR[2] | CYCTYPE+DIR | ADDR[8] | SIZE | TAR[2]   | SYNC[n] | DATA[2m] | TAR[2]
# I/O read (host driving DATA):
#  START | TAR[2] | CYCTYPE+DIR | ADDR[4] | SIZE | TAR[2]   | SYNC[n] | DATA[2m] | TAR[2]
# Memory write (peripheral driving DATA):
#  START | TAR[2] | CYCTYPE+DIR | ADDR[8] | SIZE | DATA[2m] | TAR[2]  | SYNC[n]  | TAR[2]
# I/O write (peripheral driving DATA):
#  START | TAR[2] | CYCTYPE+DIR | ADDR[4] | SIZE | DATA[2m] | TAR[2]  | SYNC[n]  | TAR[2]

START_TARGET        = 0b0000
START_BUS_MASTER_0  = 0b0010
START_BUS_MASTER_1  = 0b0011
START_FW_MEM_READ   = 0b1101
START_FW_MEM_WRITE  = 0b1110
STOP_ABORT          = 0b1111

DIR_READ            = 0b0
DIR_WRITE           = 0b1

CYCTYPE_IO          = 0b00
CYCTYPE_MEM         = 0b01
CYCTYPE_DMA         = 0b10

SIZE_1_BYTE         = 0b00
SIZE_2_BYTE         = 0b01
SIZE_4_BYTE         = 0b11

SYNC_READY          = 0b0000
SYNC_SHORT_WAIT     = 0b0101
SYNC_LONG_WAIT      = 0b0110
SYNC_READY_MORE     = 0b1001
SYNC_ERROR          = 0b1010

MSIZE_1_BYTE        = 0b0000
MSIZE_2_BYTE        = 0b0001
MSIZE_4_BYTE        = 0b0010
MSIZE_16_BYTE       = 0b0100
MSIZE_128_BYTE      = 0b0111
