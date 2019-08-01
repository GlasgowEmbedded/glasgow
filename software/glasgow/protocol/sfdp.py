# Ref: JEDEC JESD216
# Accession: G00024
# Ref: JEDEC JESD216A
# Accession: G00024A
# Ref: JEDEC JESD216B
# Accession: G00024B
#
# Currently, only JESD216 (initial revision) is implemented.

from abc import ABCMeta, abstractmethod
import struct

from ..database.jedec import *
from ..support.aobject import *
from ..support.bitstruct import *


__all__ = ["SFDPParser"]


class _JEDECRevisionMixin:
    @property
    def jedec_revision(self):
        if self.version == (1, 0):
            return "JESD216"
        if self.version == (1, 5):
            return "JESD216A"
        if self.version == (1, 6):
            return "JESD216B"
        return "unknown JESD216 revision"


_JEDEC_Flash_Param_0 = bitstruct("JEDEC_Flash_Param_0", 32, [
    ("block_sector_erase_size",         2),
    ("write_granularity",               1),
    ("volatile_wren_required",          1),
    ("volatile_wren_opcode_sel",        1),
    (None,                              3),
    ("_4_kbyte_erase_opcode",           8),
    ("has_1_1_2_fast_read",             1),
    ("address_byte_count",              2),
    ("has_double_transfer_rate",        1),
    ("has_1_2_2_fast_read",             1),
    ("has_1_4_4_fast_read",             1),
    ("has_1_1_4_fast_read",             1),
    (None,                              9),
])

_JEDEC_Flash_Param_1 = bitstruct("JEDEC_Flash_Param_1", 32, [
    ("density_value",                   31),
    ("density_over_2gbit",              1),
])

_JEDEC_Flash_Param_2 = bitstruct("JEDEC_Flash_Param_2", 32, [
    ("_fast_read_1_4_4_wait_states",    5),
    ("_fast_read_1_4_4_mode_bits",      3),
    ("_fast_read_1_4_4_opcode",         8),
    ("_fast_read_1_1_4_wait_states",    5),
    ("_fast_read_1_1_4_mode_bits",      3),
    ("_fast_read_1_1_4_opcode",         8),
])

_JEDEC_Flash_Param_3 = bitstruct("JEDEC_Flash_Param_3", 32, [
    ("_fast_read_1_1_2_wait_states",    5),
    ("_fast_read_1_1_2_mode_bits",      3),
    ("_fast_read_1_1_2_opcode",         8),
    ("_fast_read_1_2_2_wait_states",    5),
    ("_fast_read_1_2_2_mode_bits",      3),
    ("_fast_read_1_2_2_opcode",         8),
])

_JEDEC_Flash_Param_4 = bitstruct("JEDEC_Flash_Param_4", 32, [
    ("has_2_2_2_fast_read",             1),
    (None,                              3),
    ("has_4_4_4_fast_read",             1),
    (None,                              27),
])

_JEDEC_Flash_Param_5 = bitstruct("JEDEC_Flash_Param_5", 32, [
    (None,                              16),
    ("_fast_read_2_2_2_wait_states",    5),
    ("_fast_read_2_2_2_mode_bits",      3),
    ("_fast_read_2_2_2_opcode",         8),
])

_JEDEC_Flash_Param_6 = bitstruct("JEDEC_Flash_Param_6", 32, [
    (None,                              16),
    ("_fast_read_4_4_4_wait_states",    5),
    ("_fast_read_4_4_4_mode_bits",      3),
    ("_fast_read_4_4_4_opcode",         8),
])

_JEDEC_Flash_Param_7 = bitstruct("JEDEC_Flash_Param_7", 32, [
    ("sector_type_1_size",              8),
    ("sector_type_1_opcode",            8),
    ("sector_type_2_size",              8),
    ("sector_type_2_opcode",            8),
])

_JEDEC_Flash_Param_8 = bitstruct("JEDEC_Flash_Param_8", 32, [
    ("sector_type_3_size",              8),
    ("sector_type_3_opcode",            8),
    ("sector_type_4_size",              8),
    ("sector_type_4_opcode",            8),
])


class SFDPTable(_JEDECRevisionMixin):
    def __new__(cls, vendor_id, table_id, revision, parameter):
        if vendor_id == 0x00: # JEDEC
            if table_id == 0xff: # Flash Parameters
                cls = SFDPJEDECFlashParametersTable
        return object.__new__(cls)

    def __init__(self, vendor_id, table_id, revision, parameter):
        self.vendor_id = vendor_id
        self.table_id  = table_id
        self.version   = revision
        self.parameter = parameter

    @property
    def vendor_name(self):
        if self.vendor_id == 0x00:
            vendor_name = "JEDEC"
        else:
            vendor_name = jedec_mfg_name_from_bytes([self.vendor_id])
        if vendor_name is None:
            return "Unknown Vendor {:#04x}".format(self.vendor_id)
        return vendor_name

    @property
    def table_name(self):
        return "Unknown Table {:#04x}".format(self.table_id)

    def __str__(self):
        return "{}, {}".format(self.vendor_name, self.table_name)

    def __iter__(self):
        return iter(())


class SFDPJEDECFlashParametersTable(SFDPTable):
    def __init__(self, vendor_id, table_id, revision, parameter):
        super().__init__(vendor_id, table_id, revision, parameter)

        try:
            if len(parameter) < 9 * 4:
                raise ValueError("table too small")

            # First, parse SFDP table bitfields
            words = struct.unpack("4s" * 9, parameter[0:4*9])
            word0 = _JEDEC_Flash_Param_0.from_bytes(words[0])
            word1 = _JEDEC_Flash_Param_1.from_bytes(words[1])
            word2 = _JEDEC_Flash_Param_2.from_bytes(words[2])
            word3 = _JEDEC_Flash_Param_3.from_bytes(words[3])
            word4 = _JEDEC_Flash_Param_4.from_bytes(words[4])
            word5 = _JEDEC_Flash_Param_5.from_bytes(words[5])
            word6 = _JEDEC_Flash_Param_6.from_bytes(words[6])
            word7 = _JEDEC_Flash_Param_7.from_bytes(words[7])
            word8 = _JEDEC_Flash_Param_8.from_bytes(words[8])

            # Second, populate our structured fields
            if word1.density_over_2gbit:
                self.density = 1 << word1.density_value
            else:
                self.density = word1.density_value + 1

            if word0.address_byte_count == 0b00:
                self.address_byte_count = {3}
            elif word0.address_byte_count == 0b01:
                self.address_byte_count = {3, 4}
            elif word0.address_byte_count == 0b10:
                self.address_byte_count = {4}
            else:
                raise ValueError("invalid address byte count {:#04b}"
                                 .format(word0.address_byte_count))

            if word0.write_granularity:
                self.write_granularity = 64
            else:
                self.write_granularity = 1

            self.sector_sizes = {}
            if word7.sector_type_1_size > 0:
                self.sector_sizes[1 << word7.sector_type_1_size] = word7.sector_type_1_opcode
            if word7.sector_type_2_size > 0:
                self.sector_sizes[1 << word7.sector_type_2_size] = word7.sector_type_2_opcode
            if word8.sector_type_3_size > 0:
                self.sector_sizes[1 << word8.sector_type_3_size] = word8.sector_type_3_opcode
            if word8.sector_type_4_size > 0:
                self.sector_sizes[1 << word8.sector_type_4_size] = word8.sector_type_4_opcode

            self.has_double_transfer_rate = word0.has_double_transfer_rate

            self.fast_read_modes = {}
            if word0.has_1_1_2_fast_read:
                self.fast_read_modes[(1,1,2)] = (
                    word3._fast_read_1_1_2_opcode,
                    word3._fast_read_1_1_2_wait_states,
                    word3._fast_read_1_1_2_mode_bits)
            if word0.has_1_1_4_fast_read:
                self.fast_read_modes[(1,1,4)] = (
                    word2._fast_read_1_1_4_opcode,
                    word2._fast_read_1_1_4_wait_states,
                    word2._fast_read_1_1_4_mode_bits)
            if word0.has_1_2_2_fast_read:
                self.fast_read_modes[(1,2,2)] = (
                    word3._fast_read_1_2_2_opcode,
                    word3._fast_read_1_2_2_wait_states,
                    word3._fast_read_1_2_2_mode_bits)
            if word0.has_1_4_4_fast_read:
                self.fast_read_modes[(1,4,4)] = (
                    word2._fast_read_1_4_4_opcode,
                    word2._fast_read_1_4_4_wait_states,
                    word2._fast_read_1_4_4_mode_bits)
            if word4.has_2_2_2_fast_read:
                self.fast_read_modes[(2,2,2)] = (
                    word5._fast_read_2_2_2_opcode,
                    word5._fast_read_2_2_2_wait_states,
                    word5._fast_read_2_2_2_mode_bits)
            if word4.has_4_4_4_fast_read:
                self.fast_read_modes[(4,4,4)] = (
                    word6._fast_read_4_4_4_opcode,
                    word6._fast_read_4_4_4_wait_states,
                    word6._fast_read_4_4_4_mode_bits)

        except ValueError as e:
            raise ValueError("cannot parse {}: {}".format(str(self), str(e))) from None

    @property
    def table_name(self):
        return "Flash Parameter Table"

    def __iter__(self):
        properties = {}
        properties["density (Mbits)"]    = "{}".format(self.density >> 20)
        properties["density (Mbytes)"]   = "{}".format(self.density >> 23)
        properties["address byte count"] = ", ".join(map(str, self.address_byte_count))
        properties["write granularity"]  = "{} byte(s)".format(self.write_granularity)

        properties["sector sizes"] = ", ".join(map(str, self.sector_sizes))
        for sector_size, opcode in self.sector_sizes.items():
            properties["sector size {}".format(sector_size)] = \
                "erase opcode {:#04x}".format(opcode)

        properties["double transfer rate"] = "yes" if self.has_double_transfer_rate else "no"
        properties["fast read modes"] = \
            ", ".join("({}-{}-{})".format(*mode) for mode in self.fast_read_modes.keys())
        for mode, (opcode, wait_states, mode_bits) in self.fast_read_modes.items():
            properties["fast read mode ({}-{}-{})".format(*mode)] = \
                ("opcode {:#04x}, {} wait states, {} mode bits"
                 .format(opcode, wait_states, mode_bits))

        return iter(properties.items())


class SFDPParser(_JEDECRevisionMixin, aobject, metaclass=ABCMeta):
    @abstractmethod
    async def read(self, offset, length):
        pass

    async def __init__(self):
        sfdp_header = await self.read(0, 8)
        signature, ver_minor, ver_major, num_param_headers, _ = \
            struct.unpack("4sBBBB", sfdp_header)
        if signature != b"SFDP":
            raise ValueError("SFDP signature not present")
        self.version = (ver_major, ver_minor)

        self.tables = []
        for index in range(num_param_headers + 1):
            param_header = await self.read(8 * (1 + index), 8)
            vendor_id, rev_minor, rev_major, length_dwords, pointer, table_id = \
                struct.unpack("BBBB3sB", param_header)
            pointer = int.from_bytes(pointer, "little")

            if index == 0 and vendor_id != 0x00:
                raise ValueError("SFDP parameter header 0 has incorrect vendor ID {:#04x}"
                                 .format(vendor_id))

            parameter = await self.read(pointer, length_dwords * 4)
            table = SFDPTable(vendor_id, table_id, (rev_major, rev_minor), parameter)
            self.tables.append(table)

    def __len__(self):
        return len(self.tables)

    def __iter__(self):
        return iter(self.tables)
