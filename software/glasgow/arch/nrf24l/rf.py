# Ref: nRF24L01 Preliminary Product Specification
# Accession: G00040
# Ref: nRF24L01+ Preliminary Product Specification
# Accession: G00041
# Ref: https://travisgoodspeed.blogspot.com/2011/02/promiscuity-is-nrf24l01s-duty.html

import enum

from ...support.bitstruct import *


__all__ = [
    # Command opcodes
    "OP_R_REGISTER", "OP_W_REGISTER", "OP_R_RX_PL_WID", "OP_R_RX_PAYLOAD", "OP_W_TX_PAYLOAD",
    "OP_W_ACK_PAYLOAD", "OP_W_TX_PAYLOAD_NOACK", "OP_FLUSH_TX", "OP_FLUSH_RX", "OP_REUSE_TX_PL",
    "OP_NOP",
    # Register addresses
    "ADDR_CONFIG", "ADDR_EN_AA", "ADDR_EN_RXADDR", "ADDR_SETUP_AW", "ADDR_SETUP_RETR",
    "ADDR_RF_CH", "ADDR_RF_SETUP", "ADDR_STATUS", "ADDR_OBSERVE_TX", "ADDR_CD", "ADDR_RPD",
    "ADDR_RX_ADDR_Pn", "ADDR_TX_ADDR", "ADDR_RX_PW_Pn", "ADDR_FIFO_STATUS", "ADDR_DYNPD",
    "ADDR_FEATURE",
    # Registers
    "REG_CONFIG", "REG_EN_AA", "REG_EN_RXADDR", "REG_SETUP_AW", "REG_SETUP_RETR", "REG_RF_CH",
    "REG_RF_SETUP", "REG_STATUS", "REG_OBSERVE_TX", "REG_CD", "REG_RPD", "REG_FIFO_STATUS",
    "REG_DYNPD", "REG_FEATURE",
    # Enumerations
    "CRCO", "AW", "RF_DR", "RF_PWR",
]


# Command opcodes

OP_R_REGISTER           = 0b000_00000
OP_W_REGISTER           = 0b001_00000
OP_R_RX_PL_WID          = 0b0110_0000
OP_R_RX_PAYLOAD         = 0b0110_0001
OP_W_TX_PAYLOAD         = 0b1010_0000
OP_W_ACK_PAYLOAD        = 0b1010_1000
OP_W_TX_PAYLOAD_NOACK   = 0b1011_0000
OP_FLUSH_TX             = 0b1110_0001
OP_FLUSH_RX             = 0b1110_0010
OP_REUSE_TX_PL          = 0b1110_0011
OP_NOP                  = 0b1111_1111

# Register addresses

ADDR_CONFIG         = 0x00
ADDR_EN_AA          = 0x01
ADDR_EN_RXADDR      = 0x02
ADDR_SETUP_AW       = 0x03
ADDR_SETUP_RETR     = 0x04
ADDR_RF_CH          = 0x05
ADDR_RF_SETUP       = 0x06
ADDR_STATUS         = 0x07
ADDR_OBSERVE_TX     = 0x08
ADDR_CD             = 0x09 # (L)
ADDR_RPD            = 0x09 # (L+)
def ADDR_RX_ADDR_Pn(n):
    assert n in range(6)
    return 0x0a + n
ADDR_TX_ADDR        = 0x10
def ADDR_RX_PW_Pn(n):
    assert n in range(6)
    return 0x11 + n
ADDR_FIFO_STATUS    = 0x17
ADDR_DYNPD          = 0x1c # (L+)
ADDR_FEATURE        = 0x1d # (L+)


# Registers

class CRCO(enum.IntEnum):
    _1_BYTE     = 0b0
    _2_BYTES    = 0b1

REG_CONFIG      = bitstruct("REG_CONFIG", 8, [
    ("PRIM_RX",     1),
    ("PWR_UP",      1),
    ("CRCO",        1),
    ("EN_CRC",      1),
    ("MASK_MAX_RT", 1),
    ("MASK_TX_DS",  1),
    ("MASK_RX_DR",  1),
    (None,          1),
])

REG_EN_AA       = bitstruct("REG_EN_AA", 8, [
    ("ENAA_P0",     1),
    ("ENAA_P1",     1),
    ("ENAA_P2",     1),
    ("ENAA_P3",     1),
    ("ENAA_P4",     1),
    ("ENAA_P5",     1),
    (None,          2),
])

REG_EN_RXADDR   = bitstruct("REG_EN_RXADDR", 8, [
    ("ERX_P0",      1),
    ("ERX_P1",      1),
    ("ERX_P2",      1),
    ("ERX_P3",      1),
    ("ERX_P4",      1),
    ("ERX_P5",      1),
    (None,          2),
])

class AW(enum.IntEnum):
    _2_BYTES    = 0b00 # undocumented
    _3_BYTES    = 0b01
    _4_BYTES    = 0b10
    _5_BYTES    = 0b11

REG_SETUP_AW    = bitstruct("REG_SETUP_AW", 8, [
    ("AW",          2),
    (None,          6),
])

REG_SETUP_RETR  = bitstruct("REG_SETUP_RETR", 8, [
    ("ARC",         4), # 250*ARC+86 us (L); 250*ARC us (L+)
    ("ARD",         4), # up to ARD retransmits
])

REG_RF_CH       = bitstruct("REG_RF_CH", 8, [
    ("RF_CH",       7),
    (None,          1),
])

class RF_DR(enum.IntEnum):
    _1_Mbps     = 0b00
    _2_Mbps     = 0b01
    _250_kbps   = 0b10

class RF_PWR(enum.IntEnum):
    m18_dBm     = 0b00
    m12_dBm     = 0b01
    m6_dBm      = 0b10
    _0_dBm      = 0b11

REG_RF_SETUP    = bitstruct("REG_RF_SETUP", 8, [
    ("LNA_HCURR",   1), # (L)
    ("RF_PWR",      2),
    ("RF_DR_LOW",   1), # RF_DR (L)
    ("PLL_LOCK",    1),
    ("RF_DR_HIGH",  1), # (L+)
    (None,          1),
    ("CONT_WAVE",   1), # (L+)
])

REG_STATUS      = bitstruct("REG_STATUS", 8, [
    ("TX_FULL",     1),
    ("RX_P_NO",     3),
    ("MAX_RT",      1),
    ("TX_DS",       1),
    ("RX_DR",       1),
    (None,          1),
])

REG_OBSERVE_TX  = bitstruct("REG_OBSERVE_TX", 8, [
    ("ARC_CNT",     4),
    ("PLOS_CNT",    4),
])

# (L)
REG_CD          = bitstruct("REG_CD", 8, [
    ("CD",          1),
    (None,          7),
])

# (L+)
REG_RPD         = bitstruct("REG_RPD", 8, [
    ("RPD",         1),
    (None,          7),
])

REG_FIFO_STATUS = bitstruct("REG_FIFO_STATUS", 8, [
    ("RX_EMPTY",    1),
    ("RX_FULL",     1),
    (None,          2),
    ("TX_EMPTY",    1),
    ("TX_FULL",     1),
    ("TX_REUSE",    1),
    (None,          1),
])

# (L+)
REG_DYNPD       = bitstruct("REG_DYNPD", 8, [
    ("DPL_P0",      1),
    ("DPL_P1",      1),
    ("DPL_P2",      1),
    ("DPL_P3",      1),
    ("DPL_P4",      1),
    ("DPL_P5",      1),
    (None,          2),
])

# (L+)
REG_FEATURE     = bitstruct("REG_FEATURE", 8, [
    ("EN_DYN_ACK",  1),
    ("EN_ACK_PAY",  1),
    ("EN_DPL",      1),
    (None,          5),
])
