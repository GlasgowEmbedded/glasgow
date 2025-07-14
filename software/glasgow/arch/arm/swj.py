# Ref: Arm Debug Interface Architecture Specification ADIv5.0 to ADIv5.2, Issue E
# Accession: G00097
# Document Number: IHI0031E

from glasgow.support.bits import bits


__all__ = [
    "SWJ_line_reset_seq",
    "SWJ_jtag_to_swd_switch_seq", "SWJ_swd_to_jtag_switch_seq",
    "SWJ_jtag_to_dormant_switch_seq", "SWJ_swd_to_dormant_switch_seq",
    "SWJ_selection_alert_seq",
    "SWJ_dormant_to_swd_switch_seq", "SWJ_dormant_to_jtag_switch_seq",
]


# This sequence includes the final two low bits required for the following header to be processed.
# The other sequences below start with a line reset excluding the final two low bits, which would
# otherwise advance the line protocol state in a way precluding the switch from happening.
SWJ_line_reset_seq = bits(0x3ffffffffffff, 52)

# Deprecated SWJ-DP switch mechanism.
SWJ_jtag_to_swd_switch_seq     = bits(0x3ffffffffffff, 50) + bits(0xe79e, 16)
SWJ_swd_to_jtag_switch_seq     = bits(0x3ffffffffffff, 50) + bits(0xe73c, 16) + bits(0x1f, 5)

# Current "dormant operation" switch mechanism.
SWJ_jtag_to_dormant_switch_seq = bits(0x33bbbbba, 31)
SWJ_swd_to_dormant_switch_seq  = bits(0x3ffffffffffff, 50) + bits(0xe3bc, 16)
SWJ_selection_alert_seq        = \
    bits(0xff, 8) + bits(0x19bc0ea2e3ddafe986852d956209f392, 128) + bits(0x0, 4)
SWJ_dormant_to_swd_switch_seq  = bits(0x1a, 8)
SWJ_dormant_to_jtag_switch_seq = bits(0x0a, 8)
