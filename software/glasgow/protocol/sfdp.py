# Ref: JEDEC JESD216
# Accession: G00024
# Ref: JEDEC JESD216A
# Accession: G00024A
# Ref: JEDEC JESD216B
# Accession: G00024B
#
# Currently, only JESD216 (base) and JESD216A are implemented.

from __future__ import annotations
from collections.abc import Iterator, Callable, Awaitable
from dataclasses import dataclass
import enum
import struct

from glasgow.database.jedec import jedec_mfg_name_from_bytes
from glasgow.arch.qspi import CommandMode as CommandMode
from glasgow.support.bitstruct import bitstruct


__all__ = ["SFDPCollection", "SFDPJEDECFlashParametersTable"]


class _JEDECRevisionMixin:
    revision: tuple[int, int]

    @property
    def jedec_revision(self):
        match self.revision:
            case (1, 0):
                return "JESD216"
            case (1, 5):
                return "JESD216A"
            case (1, 6):
                return "JESD216B"
            case _:
                return "unknown JESD216 revision"


_JEDECFlashParam0 = bitstruct("JEDECFlashParam0", 32, [
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

_JEDECFlashParam1 = bitstruct("JEDECFlashParam1", 32, [
    ("density_value",                   31),
    ("density_over_2gbit",              1),
])

_JEDECFlashParam2 = bitstruct("JEDECFlashParam2", 32, [
    ("fast_read_1_4_4_wait_states",     5),
    ("fast_read_1_4_4_mode_clocks",     3),
    ("fast_read_1_4_4_opcode",          8),
    ("fast_read_1_1_4_wait_states",     5),
    ("fast_read_1_1_4_mode_clocks",     3),
    ("fast_read_1_1_4_opcode",          8),
])

_JEDECFlashParam3 = bitstruct("JEDECFlashParam3", 32, [
    ("fast_read_1_1_2_wait_states",     5),
    ("fast_read_1_1_2_mode_clocks",     3),
    ("fast_read_1_1_2_opcode",          8),
    ("fast_read_1_2_2_wait_states",     5),
    ("fast_read_1_2_2_mode_clocks",     3),
    ("fast_read_1_2_2_opcode",          8),
])

_JEDECFlashParam4 = bitstruct("JEDECFlashParam4", 32, [
    ("has_2_2_2_fast_read",             1),
    (None,                              3),
    ("has_4_4_4_fast_read",             1),
    (None,                             27),
])

_JEDECFlashParam5 = bitstruct("JEDECFlashParam5", 32, [
    (None,                             16),
    ("fast_read_2_2_2_wait_states",     5),
    ("fast_read_2_2_2_mode_clocks",     3),
    ("fast_read_2_2_2_opcode",          8),
])

_JEDECFlashParam6 = bitstruct("JEDECFlashParam6", 32, [
    (None,                             16),
    ("fast_read_4_4_4_wait_states",     5),
    ("fast_read_4_4_4_mode_clocks",     3),
    ("fast_read_4_4_4_opcode",          8),
])

_JEDECFlashParam7 = bitstruct("JEDECFlashParam7", 32, [
    ("sector_type_1_size",              8),
    ("sector_type_1_opcode",            8),
    ("sector_type_2_size",              8),
    ("sector_type_2_opcode",            8),
])

_JEDECFlashParam8 = bitstruct("JEDECFlashParam8", 32, [
    ("sector_type_3_size",              8),
    ("sector_type_3_opcode",            8),
    ("sector_type_4_size",              8),
    ("sector_type_4_opcode",            8),
])

_JEDECFlashParam9 = bitstruct("JEDECFlashParam9", 32, [
    ("max_erase_time_mult",             4),
    ("sector_type_1_avg_erase_time",    7),
    ("sector_type_2_avg_erase_time",    7),
    ("sector_type_3_avg_erase_time",    7),
    ("sector_type_4_avg_erase_time",    7),
])

_JEDECFlashParam10 = bitstruct("JEDECFlashParam10", 32, [
    ("max_program_time_mult",           4),
    ("page_size",                       4),
    ("page_program_typ_time",           6),
    ("byte_program_typ_time_first",     5),
    ("byte_program_typ_time_rest",      5),
    ("chip_erase_typ_time",             7),
    (None,                              1),
])

_JEDECFlashParam11 = bitstruct("JEDECFlashParam11", 32, [
    ("prohibited_ops_program_suspend",  4),
    ("prohibited_ops_erase_suspend",    4),
    (None,                              1),
    ("program_resume_suspend_interval", 4),
    ("suspend_program_max_latency",     7),
    ("erase_resume_suspend_interval",   4),
    ("suspend_erase_max_latency",       7),
    ("suspend_resume_supported",        1),
])

_JEDECFlashParam12 = bitstruct("JEDECFlashParam12", 32, [
    ("program_resume_instruction",      8),
    ("program_suspend_instruction",     8),
    ("resume_instruction",              8),
    ("suspend_instruction",             8),
])

_JEDECFlashParam13 = bitstruct("JEDECFlashParam13", 32, [
    (None,                              2),
    ("status_register_poll_device_busy",6),
    ("exit_deep_pd_to_next_op_delay",   7),
    ("exit_deep_pd_instruction",        8),
    ("enter_deep_pd_instruction",       8),
    ("deep_pd_supported",               1),
])


class SFDPJEDECQuadEnableRequirements(enum.Enum):
    Absent                      = 0b000
    """Device does not have a QE bit. Device may detect 1-1-4 and 1-4-4 commands based on their
    instruction. An IO3/HOLD# pin, if present, functions as hold during instruction input phase and
    an IO2/WP# pin, if present, functions as WP# during instruction input phase."""

    Reg2Bit1_WrReg1ClobberReg2  = 0b001
    """QE is bit 1 of status register 2. It is set via Write Status with two data bytes where bit 1
    of the second byte is one. It is cleared via Write Status with two data bytes where bit 1 of
    the second byte is zero. Writing only one byte to the status register has the side-effect of
    clearing status register 2, including the QE bit. The 100b code is used if writing one byte to
    the status register does not modify status register 2."""

    Reg1Bit6                    = 0b010
    """QE is bit 6 of status register 1. It is set via Write Status with one data byte where bit 6
    is one. It is cleared via Write Status with one data byte where bit 6 is zero."""

    Reg2Bit7                    = 0b011
    """QE is bit 7 of status register 2. It is set via Write status register 2 instruction 3Eh with
    one data byte where bit 7 is one. It is cleared via Write status register 2 instruction 3Eh with
    one data byte where bit 7 is zero. The status register 2 is read using instruction 3Fh."""

    Reg2Bit1_WrReg1PreserveReg2 = 0b100
    """QE is bit 1 of status register 2. It is set via Write Status with two data bytes where bit 1
    of the second byte is one. It is cleared via Write Status with two data bytes where bit 1 of
    the second byte is zero. In contrast to the 001b code, writing one byte to the status register
    does not modify status register 2."""

    Reg2Bit1_Read35h_Write05h   = 0b101
    """QE is bit 1 of the status register 2. Status register 1 is read using Read Status instruction
    05h. Status register 2 is read using instruction 35h. QE is set via Write Status instruction 01h
    with two data bytes where bit 1 of the second byte is one. It is cleared via Write Status with
    two data bytes where bit 1 of the second byte is zero."""

    Reg2Bit1_Read35h_Write31h   = 0b110
    """QE is bit 1 of the status register 2. Status register 1 is read using Read Status instruction
    05h. Status register 2 is read using instruction 35h, and status register 3 is read using
    instruction 15h. QE is set via Write Status Register instruction 31h with one data byte where
    bit 1 is one. It is cleared via Write Status Register instruction 31h with one data byte where
    bit 1 is zero."""

    Reserved                    = 0b111


_JEDECFlashParam14 = bitstruct("JEDECFlashParam14", 32, [
    ("_4_4_4_mode_disable_sequences",   4),
    ("_4_4_4_mode_enable_sequences",    5),
    ("_0_4_4_mode_supported",           1),
    ("_0_4_4_mode_exit_method",         6),
    ("_0_4_4_mode_entry_method",        4),
    ("quad_enable_requirements",        3),
    ("hold_wp_disable",                 1),
    (None,                              8),
])


class SFDPJEDECEnter4ByteAddressingMethods(enum.Flag):
    CommandB7h              = 0b0000_0001
    WriteEnableCommandB7h   = 0b0000_0010
    AddrRegisterC8hC5h      = 0b0000_0100
    BankRegister16h17h      = 0b0000_1000
    ModeRegisterB5hB1h      = 0b0001_0000
    DedicatedCommands       = 0b0010_0000
    Always4Byte             = 0b0100_0000
    Reserved7               = 0b1000_0000


class SFDPJEDECExit4ByteAddressingMethods(enum.Flag):
    CommandE9h              = 0b00_0000_0001
    WriteEnableCommandE9h   = 0b00_0000_0010
    AddrRegisterC8hC5h      = 0b00_0000_0100
    BankRegister16h17h      = 0b00_0000_1000
    ModeRegisterB5hB1h      = 0b00_0001_0000
    HardwareReset           = 0b00_0010_0000
    SoftwareReset           = 0b00_0100_0000
    PowerCycle              = 0b00_1000_0000
    Reserved8               = 0b01_0000_0000
    Reserved9               = 0b10_0000_0000


_JEDECFlashParam15 = bitstruct("JEDECFlashParam15", 32, [
    ("v_nv_register_write_enable_sr1",  7),
    (None,                              1),
    ("soft_reset_rescue_sequence",      6),
    ("exit_4_byte_addressing",         10),
    ("enter_4_byte_addressing",         8),
])


_JEDECFlashParam = [
    _JEDECFlashParam0,
    _JEDECFlashParam1,
    _JEDECFlashParam2,
    _JEDECFlashParam3,
    _JEDECFlashParam4,
    _JEDECFlashParam5,
    _JEDECFlashParam6,
    _JEDECFlashParam7,
    _JEDECFlashParam8,
    _JEDECFlashParam9,
    _JEDECFlashParam10,
    _JEDECFlashParam11,
    _JEDECFlashParam12,
    _JEDECFlashParam13,
    _JEDECFlashParam14,
    _JEDECFlashParam15,
]


class SFDPTable(_JEDECRevisionMixin):
    def __new__(cls, vendor_id, table_id, revision, parameter):
        if vendor_id == 0x00: # JEDEC
            if table_id == 0xff: # Flash Parameters
                cls = SFDPJEDECFlashParametersTable
        return object.__new__(cls)

    def __init__(self, vendor_id, table_id, revision, parameter):
        self.vendor_id = vendor_id
        self.table_id  = table_id
        self.revision  = revision
        self.parameter = parameter

    @property
    def vendor_name(self) -> str:
        if self.vendor_id == 0x00:
            vendor_name = "JEDEC"
        else:
            vendor_name = jedec_mfg_name_from_bytes([self.vendor_id])
        if vendor_name is None:
            return f"Unknown Vendor {self.vendor_id:#04x}"
        return vendor_name

    @property
    def table_name(self) -> str:
        return f"Unknown Table {self.table_id:#04x}"

    def description(self, index=None) -> list[str]:
        header  = f"SFDP table"
        if index is not None:
            header += f" #{index}"
        header += f": {self.vendor_name}, {self.table_name}"
        header += f", {self.revision[0]}.{self.revision[1]}"
        if self.vendor_id == 0x00: # JEDEC
            header += f" ({self.jedec_revision})"
        lines = [header]
        if any(self):
            key_width = max(len(key) for key, value in self) + 1
            for key, value in self:
                lines.append(f"  {key:{key_width}}: {value}")
        return lines

    def __str__(self) -> str:
        return f"{self.vendor_name}, {self.table_name}"

    def __iter__(self) -> Iterator[tuple[str, str]]:
        return iter(())


@dataclass(frozen=True)
class SFDPJEDECFastReadParameters:
    opcode: int
    """Instruction opcode."""

    mode_clocks: int
    """Amount of mode clocks.

    Mode clocks are clock cycles immediately following the address phase. The controller drives
    the bus for the duration of the mode clocks, and the device reacts, typically by altering
    how the next instruction opcode is processed.

    Device datasheets are inconsistent as to whether mode clocks are considered "dummy cycles".
    """

    wait_states: int
    """Amount of wait states.

    Wait states are clock cycles immediately following the mode clocks (if specified) or else
    the address phase. Neither the controller nor the device drives the bus, which provides
    turn-around period and avoids contention on bidirectional pins.

    Device datasheets consider wait states to "dummy cycles", but sometimes expand the latter term
    to also include mode clocks.

    Some devices define fast read modes with zero wait states and a non-zero number of mode clocks.
    This is ill-formed as no turnaround period would be available; upon closer inspection, usually
    some of the mode clocks are considered "don't cares" and so really are wait states. This may
    be used as an alternative to defining a fractional octet's worth of mode clocks.
    """


class SFDPJEDECFlashParametersTable(SFDPTable):
    address_byte_count: set[int]
    """Set of possible address byte counts."""

    page_size: int
    """Page size. Inexact before JESD216A."""

    exact_page_size: bool
    """Whether page size is exact or a lower bound. Always exact with JESD216A and later."""

    has_double_transfer_rate: bool
    """Whether double transfer rate instructions are supported "[in] some form"."""

    density_bits: int
    """Memory size (bits)."""

    density_bytes: int # type:ignore (doc only)
    """Memory size (bytes)."""

    fast_read_modes: dict[CommandMode, SFDPJEDECFastReadParameters]
    """Mapping from (`x`-`y`-`z`) fast read command modes to their instruction parameters."""

    erase_sizes: dict[int, int]
    """Mapping from supported erase sizes to their erase opcodes."""

    quad_enable_requirements: SFDPJEDECQuadEnableRequirements = \
        SFDPJEDECQuadEnableRequirements(0)
    """Position and access pattern for QE status bit."""

    enter_4_byte_addressing: SFDPJEDECEnter4ByteAddressingMethods = \
        SFDPJEDECEnter4ByteAddressingMethods(0)
    """Prologue sequence for addressing high data (located above 16 MiB)."""

    exit_4_byte_addressing: SFDPJEDECExit4ByteAddressingMethods = \
        SFDPJEDECExit4ByteAddressingMethods(0)
    """Epilogue sequence for addressing high data (located above 16 MiB)."""

    def __init__(self, vendor_id, table_id, revision, parameter):
        super().__init__(vendor_id, table_id, revision, parameter)
        try:
            self._parse(parameter)
        except ValueError as e:
            raise ValueError(f"cannot parse {self!s}: {e!s}") from None

    def _parse(self, parameter):
        # First, parse SFDP table bitfields.
        self._dwords = dw = []
        for index, param in zip(range(0, len(parameter), 4), _JEDECFlashParam):
            dw.append(param.from_bytes(self.parameter[index:index + 4]))
        if len(dw) < 9:
            raise ValueError("table too small for JESD214 (base)")

        # Second, populate our structured fields.

        # 1st DWORD
        if dw[0].address_byte_count == 0b00:
            self.address_byte_count = {3}
        elif dw[0].address_byte_count == 0b01:
            self.address_byte_count = {3, 4}
        elif dw[0].address_byte_count == 0b10:
            self.address_byte_count = {4}
        else:
            raise ValueError(f"invalid address byte count {dw[0].address_byte_count:#04b}")

        if dw[0].write_granularity:
            self.page_size = 64
        else:
            self.page_size = 1
        self.exact_page_size = False

        self.has_double_transfer_rate = dw[0].has_double_transfer_rate

        self.fast_read_modes = {}
        # (fast read modes described in DWORDs 3 and 4)

        # 2nd DWORD
        if dw[1].density_over_2gbit:
            self.density_bits = 1 << dw[1].density_value
        else:
            self.density_bits = dw[1].density_value + 1

        # 3rd DWORD
        if dw[0].has_1_1_4_fast_read:
            self.fast_read_modes[CommandMode(1,1,4)] = SFDPJEDECFastReadParameters(
                dw[2].fast_read_1_1_4_opcode,
                dw[2].fast_read_1_1_4_mode_clocks,
                dw[2].fast_read_1_1_4_wait_states)
        if dw[0].has_1_4_4_fast_read:
            self.fast_read_modes[CommandMode(1,4,4)] = SFDPJEDECFastReadParameters(
                dw[2].fast_read_1_4_4_opcode,
                dw[2].fast_read_1_4_4_mode_clocks,
                dw[2].fast_read_1_4_4_wait_states)

        # 4th DWORD
        if dw[0].has_1_1_2_fast_read:
            self.fast_read_modes[CommandMode(1,1,2)] = SFDPJEDECFastReadParameters(
                dw[3].fast_read_1_1_2_opcode,
                dw[3].fast_read_1_1_2_mode_clocks,
                dw[3].fast_read_1_1_2_wait_states)
        if dw[0].has_1_2_2_fast_read:
            self.fast_read_modes[CommandMode(1,2,2)] = SFDPJEDECFastReadParameters(
                dw[3].fast_read_1_2_2_opcode,
                dw[3].fast_read_1_2_2_mode_clocks,
                dw[3].fast_read_1_2_2_wait_states)

        # 5th DWORD
        # (fast read modes described in DWORDs 6 and 7)

        # 6th DWORD
        if dw[4].has_2_2_2_fast_read:
            self.fast_read_modes[CommandMode(2,2,2)] = SFDPJEDECFastReadParameters(
                dw[5].fast_read_2_2_2_opcode,
                dw[5].fast_read_2_2_2_mode_clocks,
                dw[5].fast_read_2_2_2_wait_states)

        # 7th DWORD
        if dw[4].has_4_4_4_fast_read:
            self.fast_read_modes[CommandMode(4,4,4)] = SFDPJEDECFastReadParameters(
                dw[6].fast_read_4_4_4_opcode,
                dw[6].fast_read_4_4_4_mode_clocks,
                dw[6].fast_read_4_4_4_wait_states)

        # 8th DWORD
        self.sector_sizes = {}
        if dw[7].sector_type_1_size > 0:
            self.sector_sizes[1 << dw[7].sector_type_1_size] = dw[7].sector_type_1_opcode
        if dw[7].sector_type_2_size > 0:
            self.sector_sizes[1 << dw[7].sector_type_2_size] = dw[7].sector_type_2_opcode

        # 9th DWORD
        if dw[8].sector_type_3_size > 0:
            self.sector_sizes[1 << dw[8].sector_type_3_size] = dw[8].sector_type_3_opcode
        if dw[8].sector_type_4_size > 0:
            self.sector_sizes[1 << dw[8].sector_type_4_size] = dw[8].sector_type_4_opcode

        if len(dw) < 16:
            return # prior to JESD216

        # 10th DWORD

        # 11th DWORD
        self.page_size = 1 << dw[10].page_size
        self.exact_page_size = True

        # 12th DWORD

        # 13th DWORD

        # 14th DWORD
        # (SR polling)

        # 15th DWORD
        # (Quad Enable)
        self.quad_enable_requirements = \
            SFDPJEDECQuadEnableRequirements(dw[14].quad_enable_requirements)

        # 16th DWORD
        self.exit_4_byte_addressing = \
            SFDPJEDECExit4ByteAddressingMethods(dw[15].exit_4_byte_addressing)
        self.enter_4_byte_addressing = \
            SFDPJEDECEnter4ByteAddressingMethods(dw[15].enter_4_byte_addressing)
        # (Soft Reset)
        # (SR1 Write Enable)

    @property
    def table_name(self) -> str:
        return "Flash Parameter Table"

    @property
    def density_bytes(self) -> int:
        return self.density_bits >> 3

    def __iter__(self) -> Iterator[tuple[str, str]]:
        properties = {}
        properties["density (bits)"] = f"{self.density_bits >> 20} Mibit"
        if self.density_bytes < 1024*1024:
            properties["density (bytes)"] = f"{self.density_bytes >> 10} KiB"
        else:
            properties["density (bytes)"] = f"{self.density_bytes >> 20} MiB"
        properties["address byte count"]  = "/".join(map(str, self.address_byte_count))
        if self.page_size == 1 or self.exact_page_size:
            properties["page size"] = f"{self.page_size} B"
        else:
            properties["page size"] = f">= {self.page_size} B"

        properties["sector sizes"] = ", ".join(f"{size} B" for size in self.sector_sizes)
        for sector_size, opcode in self.sector_sizes.items():
            properties[f"sector size {sector_size}"] = f"erase opcode {opcode:02X}h"

        properties["double transfer rate"] = "yes" if self.has_double_transfer_rate else "no"
        properties["fast read modes"] = \
            ", ".join(f"({mode})" for mode in self.fast_read_modes.keys())
        for mode, params in self.fast_read_modes.items():
            properties[f"fast read mode ({mode})"] = ", ".join((
                f"opcode {params.opcode:02X}h",
                f"{params.mode_clocks} mode clocks",
                f"{params.wait_states} wait states",
            ))

        if self.enter_4_byte_addressing != 0:
            properties["4-byte mode prologues"] = ", ".join([
                member.name for member in SFDPJEDECEnter4ByteAddressingMethods
                if member.name and self.enter_4_byte_addressing & member
            ])
        if self.exit_4_byte_addressing != 0:
            properties["4-byte mode epilogues"] = ", ".join([
                member.name for member in SFDPJEDECExit4ByteAddressingMethods
                if member.name and self.exit_4_byte_addressing & member
            ])

        return iter(properties.items())

    def raw_dwords(self) -> Iterator[tuple[int, list[str]]]:
        return iter([(int(dw), dw.bits_repr().split(" ")) for dw in self._dwords])


class SFDPCollection(_JEDECRevisionMixin):
    @classmethod
    async def parse(cls, read_sfdp: Callable[[int, int], Awaitable[bytes]]) -> SFDPCollection:
        sfdp_header = await read_sfdp(0, 8)
        signature, rev_minor, rev_major, num_param_headers, _ = \
            struct.unpack("4sBBBB", sfdp_header)
        if signature != b"SFDP":
            raise ValueError("SFDP signature not present")
        revision = (rev_major, rev_minor)

        tables = []
        for index in range(num_param_headers + 1):
            param_header = await read_sfdp(8 * (1 + index), 8)
            vendor_id, rev_minor, rev_major, length_dwords, pointer, table_id = \
                struct.unpack("BBBB3sB", param_header)
            pointer = int.from_bytes(pointer, "little")

            if index == 0 and vendor_id != 0x00:
                raise ValueError(
                    f"SFDP parameter header 0 has incorrect vendor ID {vendor_id:#04x}")

            parameter = await read_sfdp(pointer, length_dwords * 4)
            table = SFDPTable(vendor_id, table_id, (rev_major, rev_minor), parameter)
            tables.append(table)

        return cls(revision, tables)

    def __init__(self, revision: tuple[int, int], tables: list[SFDPTable]):
        self.revision = revision
        self.tables   = tables

    def __len__(self) -> int:
        return len(self.tables)

    def __iter__(self) -> Iterator[SFDPTable]:
        return iter(self.tables)

    @property
    def jedec_flash_table(self) -> SFDPJEDECFlashParametersTable:
        table = next(iter(self))
        assert isinstance(table, SFDPJEDECFlashParametersTable)
        return table

    def description(self) -> list[str]:
        lines = []
        for index, table in enumerate(self):
            lines.extend(table.description(index))
        return lines

    def __str__(self) -> str:
        return f"SFDP {self.revision[0]}.{self.revision[1]} ({self.jedec_revision})"
