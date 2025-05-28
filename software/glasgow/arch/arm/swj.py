# Ref: Arm Debug Interface Architecture Specification ADIv5.0 to ADIv5.2, Issue E
# Accession: G00097
# Document Number: IHI0031E

from glasgow.support.bits import bits


__all__ = ["SWJ_line_reset_seq", "SWJ_jtag_to_swd_switch_seq"]


# This sequence includes the final two low bits required for the following header to be processed.
SWJ_line_reset_seq = bits(0x3ffffffffffff, 52)

# This sequence starts with a line reset excluding the final two low bits, which would otherwise
# advance the JTAG state machine in a way precluding the switch from happening.
SWJ_jtag_to_swd_switch_seq = bits(0x3ffffffffffff, 50) + bits(0xe79e, 16)
