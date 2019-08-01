# Ref: ONFI Rev 1.0
# Accession: G00030

import struct
import crcmod

from ..support.bitstruct import *


__all__ = ["ONFIParameters", "ONFIParameterError"]


class ONFIParameterError(Exception):
    pass


_crc_onfi = crcmod.mkCrcFun(0x18005, initCrc=0x4f4e, rev=False)


_ONFI_Revision = bitstruct("ONFI_Revision", 16, [
    (None,                      1),
    ("rev_1_0",                 1),
    ("unknown",                 14)
])


_ONFI_Features = bitstruct("ONFI_Features", 16, [
    ("_16_bit_data_bus",        1),
    ("multiple_lun_ops",        1),
    ("non_seq_page_program",    1),
    ("interleaved_ops",         1),
    ("odd_to_even_copyback",    1),
    (None,                      11)
])


_ONFI_Optional_Commands = bitstruct("ONFI_Optional_Commands", 16, [
    ("page_cache_program",      1),
    ("read_cache",              1),
    ("get_set_features",        1),
    ("read_status_enhanced",    1),
    ("copyback",                1),
    ("read_unique_id",          1),
    (None,                      10)
])


_ONFI_Date_Code = bitstruct("ONFI_Date_Code", 16, [
    ("year",                    8),
    ("week",                    8),
])


_ONFI_Address_Cycles = bitstruct("ONFI_Address_Cycles", 8, [
    ("row",                     4),
    ("column",                  4),
])


_ONFI_Block_Endurance = bitstruct("ONFI_Block_Endurance", 16, [
    ("value",                   8),
    ("multiplier",              8),
])


_ONFI_Partial_Programming_Attributes = bitstruct("ONFI_Partial_Programming_Attributes", 8, [
    ("has_constraints",         1),
    (None,                      3),
    ("layout_is_data_spare",    1),
    (None,                      3)
])


_ONFI_Interleaved_Address_Bits = bitstruct("ONFI_Interleaved_Address_Bits", 8, [
    ("count",                   4),
    (None,                      4)
])


_ONFI_Interleaved_Operation_Attributes = bitstruct("ONFI_Interleaved_Operation_Attributes", 8, [
    ("overlapped_supported",    1),
    ("no_address_restrictions", 1),
    ("program_cache_supported", 1),
    ("program_cache_address_restrictions", 1),
    (None,                      4)
])


class ONFIParameters:
    def __init__(self, data):
        assert len(data) >= 256 and len(data) % 256 == 0

        if data[:4] != b"ONFI":
            raise ONFIParameterError("invalid signature")

        while len(data) > 0:
            crc_expected, = struct.unpack_from("<H", data, offset=254)
            crc_actual    = _crc_onfi(data[:254])
            if crc_expected == crc_actual:
                break
            # Switch to the next redundant parameters page.
            data = data[256:]
        else:
            raise ONFIParameterError("integrity checks failed on all redundant pages")

        # Revision information and features block
        #
        _, revisions, features, opt_commands, _ = \
                struct.unpack_from("<4sHHH22s", data, offset=0)

        self.revisions    = _ONFI_Revision.from_int(revisions)
        self.features     = _ONFI_Features.from_int(features)
        self.opt_commands = _ONFI_Optional_Commands.from_int(opt_commands)

        # Highest supported ONFI revision that we know of.
        self.revision = None
        if self.revisions.rev_1_0:
            self.revision = (1, 0)

        # Manufacturer information block
        #
        manufacturer, model, self.jedec_manufacturer_id, date_code, _ = \
                struct.unpack_from("<12s20sBH13s", data, offset=32)

        self.manufacturer = manufacturer.decode("ascii").rstrip()
        self.model        = model.decode("ascii").rstrip()
        if date_code == 0x0000:
            self.date_code = None
        else:
            self.date_code = _ONFI_Date_Code.from_int(date_code)

        # Memory organization block
        #
        self.bytes_per_page, self.bytes_per_spare, \
            self.bytes_per_partial_page, self.bytes_per_partial_spare, \
            self.pages_per_block, self.blocks_per_lun, self.luns_per_target, \
            address_cycles, self.bits_per_cell, \
            self.max_bad_blocks_per_lun, block_endurance, \
            self.guaranteed_valid_blocks, self.guaranteed_valid_block_endurance, \
            self.programs_per_page, partial_programming_attrs,\
            self.ecc_correctability_bits, \
            interleaved_address_bits, interleaved_op_attrs, _, = \
                struct.unpack_from("<LHLHLLBBBHHBHBBBBB13s", data, offset=80)

        self.address_cycles  = _ONFI_Address_Cycles.from_int(address_cycles)
        block_endurance      = _ONFI_Block_Endurance.from_int(block_endurance)
        self.block_endurance = block_endurance.value * (10 ** block_endurance.multiplier)
        self.partial_programming_attrs = \
            _ONFI_Partial_Programming_Attributes.from_int(partial_programming_attrs)
        self.interleaved_address_bits = \
            _ONFI_Interleaved_Address_Bits.from_int(interleaved_address_bits)
        self.interleaved_op_attrs = \
            _ONFI_Interleaved_Operation_Attributes.from_int(interleaved_op_attrs)

        # Electrical parameters block
        #
        self.io_pin_capacitance, \
            timing_mode_support, program_cache_timing_mode_support, \
            self.max_page_program_time, self.max_block_erase_time, self.max_page_read_time, \
            self.min_change_column_setup_time, _ = \
                struct.unpack_from("<BHHHHHH23s", data, offset=128)

        self.timing_modes = \
            [mode for mode in range(6) if timing_mode_support & (1 << mode)]
        self.program_cache_timing_modes = \
            [mode for mode in range(6) if program_cache_timing_mode_support & (1 << mode)]
