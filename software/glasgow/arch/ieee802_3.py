# Ref: IEEE Std 802.3-2018 §22.2.2.14, §22.3.4, §45
# Accession: G00098

from amaranth.lib import enum

from ..support.bitstruct import bitstruct


__all__ = [
    "REG_BASIC_CONTROL_addr", "REG_BASIC_CONTROL", "REG_BASIC_STATUS_addr", "REG_BASIC_STATUS",
    "REG_PHY_ID1_addr", "REG_PHY_ID1", "REG_PHY_ID2_addr", "REG_PHY_ID2",
    "MMD_FNCTN", "MMD_DEVAD", "REG_MMDCTRL_addr", "REG_MMDCTRL", "REG_MMDAD_addr"
]


REG_BASIC_CONTROL_addr  = 0x00
REG_BASIC_CONTROL       = bitstruct("REG_BASIC_CONTROL", 16, [
    (None,          6),
    ("SPD_SEL_1",   1),
    ("COLTST",      1),
    ("DUPLEXMD",    1),
    ("REAUTONEG",   1),
    ("ISOLATE",     1),
    ("PD",          1),
    ("AUTONEGEN",   1),
    ("SPD_SEL_0",   1),
    ("LOOPBACK",    1),
    ("SW_RESET",    1),
])


REG_BASIC_STATUS_addr   = 0x01
REG_BASIC_STATUS        = bitstruct("REG_BASIC_STATUS", 16, [
    ("EXTCAPA",     1),
    ("JABDET",      1),
    ("LNKSTS",      1),
    ("AUTONEGA",    1),
    ("RMTFLTD",     1),
    ("AUTONEGC",    1),
    ("MFPRESUPA",   1),
    (None,          1),
    ("EXTSTS",      1),
    ("_100BT2HDA",  1),
    ("_100BT2FDA",  1),
    ("_10BTHDA",    1),
    ("_10BTFDA",    1),
    ("_100BTXHDA",  1),
    ("_100BTXFDA",  1),
    ("_100BT4A",    1),
])


REG_PHY_ID1_addr = 0x02
REG_PHY_ID1      = bitstruct("REG_PHY_ID1", 16, [
    ("OUI_2_17",    16),
])


REG_PHY_ID2_addr = 0x03
REG_PHY_ID2      = bitstruct("REG_PHY_ID2", 16, [
    ("REV",         4),
    ("MODEL",       6),
    ("OUI_18_23",   6),
])


class MMD_FNCTN(enum.Enum, shape=2):
    Address      = 0b00
    Data_NoInc   = 0b01
    Data_RdWrInc = 0b10
    Data_WrInc   = 0b11


class MMD_DEVAD(enum.Enum, shape=5):
    PMA_PMD      = 0b00001
    PCS          = 0b00011
    # ...
    Clause22_Ext = 0b11101
    Vendor_1     = 0b11110
    Vendor_2     = 0b11111


REG_MMDCTRL_addr = 0x0D
REG_MMDCTRL      = bitstruct("REG_MMDCTRL", 16, [
    ("DEVAD",       5),
    (None,          9),
    ("FNCTN",       2),
])


REG_MMDAD_addr   = 0x0E
