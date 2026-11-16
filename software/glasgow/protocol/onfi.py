# Ref: ONFI Rev 1.0
# Accession: G00030

import struct
import amaranth.lib.crc

from ..support.bitstruct import *


__all__ = ["ONFIParameters", "ONFIParameterError"]


class ONFIParameterError(Exception):
    pass


_crc_onfi = staticmethod(amaranth.lib.crc.Algorithm(crc_width=16, polynomial=0x8005,
    initial_crc=0x4f4e, reflect_input=False, reflect_output=False,
    xor_output=0)(data_width=8).compute)


class _ONFI_Revision(bitstruct, width=16):
    _0: int      = 1
    rev_1_0: int = 1
    unknown: int = 14


class _ONFI_Features(bitstruct, width=16):
    data_bus_16_bit: int      = 1
    multiple_lun_ops: int     = 1
    non_seq_page_program: int = 1
    interleaved_ops: int      = 1
    odd_to_even_copyback: int = 1
    _0: int                   = 11


class _ONFI_Optional_Commands(bitstruct, width=16):
    page_cache_program: int   = 1
    read_cache: int           = 1
    get_set_features: int     = 1
    read_status_enhanced: int = 1
    copyback: int             = 1
    read_unique_id: int       = 1
    _0: int                   = 10


class _ONFI_Date_Code(bitstruct, width=16):
    year: int = 8
    week: int = 8


class _ONFI_Address_Cycles(bitstruct, width=8):
    row: int    = 4
    column: int = 4


class _ONFI_Block_Endurance(bitstruct, width=16):
    value: int      = 8
    multiplier: int = 8


class _ONFI_Partial_Programming_Attributes(bitstruct, width=8):
    has_constraints: int      = 1
    _0: int                   = 3
    layout_is_data_spare: int = 1
    _1: int                   = 3


class _ONFI_Interleaved_Address_Bits(bitstruct, width=8):
    count: int = 4
    _0: int    = 4


class _ONFI_Interleaved_Operation_Attributes(bitstruct, width=8):
    overlapped_supported: int               = 1
    no_address_restrictions: int            = 1
    program_cache_supported: int            = 1
    program_cache_address_restrictions: int = 1
    _0: int                                 = 4


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
