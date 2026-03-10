# Ref: JEDEC JESD216
# Accession: G00024
# Ref: JEDEC JESD216A
# Accession: G00024A
# Ref: JEDEC JESD216B
# Accession: G00024B
# Ref: Winbond W25Q32JV-DTR 3V 32M-BIT SERIAL FLASH MEMORY WITH DUAL/QUAD SPI & QPI & DTR
# Accession: G00108
# Ref: Micron MT25QU256ABA 256Mb, 1.8V Multiple I/O Serial Flash Memory
# Accession: G00109
# Ref: Macronix MX25L6445E, 3V, 64Mb Serial Flash
# Accession: G00110
# Ref: ISSI IS25LP128, 128Mb 3V SERIAL FLASH MEMORY
# Accession: G00111

from __future__ import annotations

from collections.abc import Callable
import enum
from enum_tools.documentation import document_enum

from glasgow.protocol.sfdp import (
    SFDPCollection, SFDPJEDECEnter4ByteAddressingMethods, SFDPJEDECExit4ByteAddressingMethods,
)
from . import Direction, CommandMode, Instruction, BaseCommandSet


__all__ = [
    "Direction", "CommandMode", "Instruction", "Opcode", "StatusReg1", "Command", "CommandSet",
]


# The purpose of this table and the instruction set object below is not to enumerate _every_
# possible command, but to have a small core of broadly useful commands and document their
# differences between major vendors. Not every opcode from this table will be used in commands
# below as most of the non-(1-1-1) opcodes are retrieved from SFDP when available, but it is
# still useful for manual experimentation.
class Opcode(enum.IntEnum):
    """Common (Q)SPI NOR Flash memory opcodes."""

    # None of these vendors will see the light of Heaven:
    #           Winbond W25Q32JV-DTR ↓
    #              Micron MT25QU256ABA ↓
    #                Macronix MX25L6445E ↓
    #                       ISSI IS25LP128 ↓
    #                                | | | |
    # Reset
    ResetDevice             = 0xFF # W
    EnableReset             = 0x66 # W M   I
    PerformReset            = 0x99 # W M   I

    # Power management
    ReleasePowerDown        = 0xAB # W M X I
    PowerDown               = 0xB9 # W M X I

    # Identification
    ReadSFDP                = 0x5A # W M X I

    ReadID                  = 0x90 # W   X I
    ReadJEDEC               = 0x9F # W M X I

    # Read
    Read                    = 0x03 # W M X I
    FastRead                = 0x0B # W M X I
    FastReadDualOutput      = 0x3B # W M   I
    FastReadQuadOutput      = 0x6B # W M   I
    FastReadDualInOut       = 0xBB # W M X I
    FastReadQuadInOut       = 0xEB # W M X I

    # Program
    PageProgram             = 0x02 # W M X I
    QuadInputPageProgram    = 0x32 # W M X I

    # Erase
    EraseChip               = 0x60 # W M X I   (C7h is an universal alternative)

    # Status Registers
    ReadStatusReg1          = 0x05 # W M X I
    WriteStatusReg1         = 0x01 # W M X I   (second data octet writes SR2 per JESD216B)
    ReadStatusReg2          = 0x35 # W
    WriteStatusReg2         = 0x31 # W
    ReadStatusReg3          = 0x15 # W
    WriteStatusReg3         = 0x11 # W

    WriteDisable            = 0x04 # W M X I
    WriteEnable             = 0x06 # W M X I

    StatusRegWriteEnable    = 0x50 # W

    # Addressing Modes
    Enter4ByteMode          = 0xB7 # M   I   (may require 06h per JESD216B)
    Leave4ByteMode          = 0xE9 # M   I   (may require 06h per JESD216B)

    def __str__(self):
        return f"{self.name}({self.value:02X}h)"

    def __repr__(self):
        return f"{self.__class__.__name__}.{self}"


@document_enum
class StatusReg1(enum.IntFlag):
    """Status Register 1 flags.

    Only includes six universally agreed upon LSBs. The two remaining MSBs have wildly varying
    function.
    """

    BUSY  = 0b00000001
    """Operation in Progress bit"""
    WREN  = 0b00000010
    """Write Enable Latch bit"""
    BP0   = 0b00000100
    """Block Protection bit 0"""
    BP1   = 0b00001000
    """Block Protection bit 1"""
    BP2   = 0b00010000
    """Block Protection bit 2"""
    BP3   = 0b00100000
    """Block Protection bit 3 or Top/Bottom Block Protection bit"""
    BPALL = BP3|BP2|BP1|BP0
    """All Block Protection bits"""

    def __str__(self):
        return f"{self.name}({self.value:08b})"

    def __repr__(self):
        return f"{self.__class__.__name__}.{self}"


# The purpose of this table is to absolve ourselves of the sins of the vendors, so while they
# are unlikely to see the light of Heaven, we one day might.
#
# Due to the extreme difficulty of aligning heathens with each other, this command set is heavily
# SFDP-oriented (JESD216). Non-SFDP commands would require explicit manual configuration and
# the overhead of doing this in a tool meant to work with many devices from many vendors means
# these should be avoided as much as reasonably feasible.
class Command(enum.Enum):
    r"""Abstract (Q)SPI NOR Flash memory commands.

    While some commands directly correspond to a specific :enum:`Opcode`, other commands have
    multiple functionally equivalent opcodes with different throughput, or in some cases there
    is no globally uniform opcode assignment at all.

    The mapping of :class:`Command`\ s to :class:`Instruction <glasgow.arch.qspi.Instruction>`\ s
    (and therefore :class:`Opcode`\ s) is maintained within a :class:`CommandSet`.
    """

    # Power management
    PowerUp         = enum.auto() # → Opcode.ReleasePowerDown
    PowerDown       = enum.auto() # → Opcode.PowerDown

    # Identification
    ReadJEDEC       = enum.auto() # → Opcode.ReadJEDEC
    ReadSFDP        = enum.auto() # → Opcode.ReadSFDP

    # Data manipulation
    ReadData        = enum.auto() # → Opcode.Read
                                  # → Opcode.FastRead
                                  # → Opcode.FastReadDualOutput
                                  # → Opcode.FastReadQuadOutput
                                  # → Opcode.FastReadDualInOut
                                  # → Opcode.FastReadQuadInOut
    ProgramData     = enum.auto() # → Opcode.PageProgram
                                  # → Opcode.QuadInputPageProgram
    EraseData4K     = enum.auto() # → Opcode.<vendor>_Erase4K
    EraseData32K    = enum.auto() # → Opcode.<vendor>_Erase32K
    EraseData64K    = enum.auto() # → Opcode.<vendor>_Erase64K
    EraseDataAll    = enum.auto() # → Opcode.EraseChip

    # Register manipulation
    WriteEnable     = enum.auto() # → Opcode.WriteEnable
    WriteDisable    = enum.auto() # → Opcode.WriteDisable

    ReadStatusReg1  = enum.auto() # → Opcode.ReadStatusReg1
    ReadStatusReg2  = enum.auto() # → Opcode.ReadStatusReg2
    ReadStatusReg3  = enum.auto() # → Opcode.ReadStatusReg3

    WriteStatusRegs = enum.auto() # → Opcode.WriteStatusReg1

    # Mode switching
    Enter4ByteMode  = enum.auto() # → Opcode.Enter4ByteMode
    Leave4ByteMode  = enum.auto() # → Opcode.Leave4ByteMode

    def __repr__(self):
        return f"{self.__class__.__name__}.{self.name}"

    @classmethod
    def all_erase_sizes(cls) -> set[int]:
        """Every known erase size."""
        return {4096, 32768, 65536}

    @classmethod
    def erase_for_size(cls, erase_size: int) -> Command:
        """Select erase command for an :py:`erase_size`-long region.

        Raises
        ------
        ValueError
            If :py:`erase_size` is not in :meth:`erase_erase_sizes`.
        """
        match erase_size:
            case 4096:
                return cls.EraseData4K
            case 32768:
                return cls.EraseData32K
            case 65536:
                return cls.EraseData64K
            case _:
                raise ValueError(f"unsupported erase size {erase_size}")


type InstructionSequence = list[Instruction | tuple[Instruction, bytes]]


class CommandSet(BaseCommandSet[Command]):
    """SPI NOR Flash command set.

    When created, the command set only contains the opcodes that are implemented by every JESD216
    compliant device. This makes identification and configuration possible, but data transfer
    cannot occur until the corresponding command set is configured via :meth:`use_explicit` or
    :meth:`use_jesd216`.

    Created with the following mappings:

    * :data:`Command.PowerUp`: :data:`Opcode.ReleasePowerDown`, (1-0-0) mode
    * :data:`Command.PowerDown`: :data:`Opcode.PowerDown`, (1-0-0) mode
    * :data:`Command.ReadSFDP`: :data:`Opcode.ReadSFDP`, (1-1-1) mode
    * :data:`Command.ReadJEDEC`: :data:`Opcode.ReadJEDEC`, (1-0-1) mode
    * :data:`Command.ReadStatusReg1`: :data:`Opcode.ReadStatusReg1`, (1-0-1) mode
    * :data:`Command.ReadStatusReg2`: :data:`Opcode.ReadStatusReg2`, (1-0-1) mode
    * :data:`Command.ReadStatusReg3`: :data:`Opcode.ReadStatusReg3`, (1-0-1) mode
    * :data:`Command.WriteStatusRegs`: :data:`Opcode.WriteStatusReg1`, (1-0-1) mode
    * :data:`Command.WriteEnable`: :data:`Opcode.WriteEnable`, (1-0-0) mode
    * :data:`Command.WriteDisable`: :data:`Opcode.WriteDisable`, (1-0-0) mode
    * :data:`Command.EraseDataAll`: :data:`Opcode.EraseChip`, (1-0-0) mode
    """

    def __init__(self):
        super().__init__()

        self.update({
            # Power management
            Command.PowerUp:
                Instruction.spi_1_0_0(Opcode.ReleasePowerDown),
            Command.PowerDown:
                Instruction.spi_1_0_0(Opcode.PowerDown),

            # Identification
            Command.ReadSFDP:
                Instruction.spi_1_1_1(Opcode.ReadSFDP, address_octets=3, dummy_cycles=8,
                    direction="read", data_repeats=True),
            Command.ReadJEDEC:
                Instruction.spi_1_0_1(Opcode.ReadJEDEC, dummy_cycles=0,
                    direction="read", data_octets=3, data_repeats=False),

            # Register manipulation
            Command.ReadStatusReg1:
                Instruction.spi_1_0_1(Opcode.ReadStatusReg1, data_octets=1, dummy_cycles=0,
                    direction="read", data_repeats=True),
            Command.ReadStatusReg2:
                Instruction.spi_1_0_1(Opcode.ReadStatusReg2, data_octets=1, dummy_cycles=0,
                    direction="read", data_repeats=True),
            Command.ReadStatusReg3:
                Instruction.spi_1_0_1(Opcode.ReadStatusReg3, data_octets=1, dummy_cycles=0,
                    direction="read", data_repeats=True),
            Command.WriteStatusRegs:
                Instruction.spi_1_0_1(Opcode.WriteStatusReg1, data_octets=1, dummy_cycles=0,
                    direction="write", data_repeats=False),

            Command.WriteEnable:
                Instruction.spi_1_0_0(Opcode.WriteEnable),
            Command.WriteDisable:
                Instruction.spi_1_0_0(Opcode.WriteDisable),

            Command.EraseDataAll:
                Instruction.spi_1_0_0(Opcode.EraseChip),
        })

    def use_explicit(self, *, address_bytes: int, page_size: int | None = None,
            opcode_erase_4k:  Opcode | int | None = None,
            opcode_erase_32k: Opcode | int | None = None,
            opcode_erase_64k: Opcode | int | None = None,
            data_operation_prologue: Callable[[int], InstructionSequence] = lambda address: []):
        """Use explicitly specified instructions.

        Adds up to five mappings:

        * :data:`Command.ReadData`: :data:`Opcode.Read`, (1-1-1) mode
        * :data:`Command.EraseData4K`: :py:`opcode_erase_4k`, (1-1-0) mode (if specified)
        * :data:`Command.EraseData32K`: :py:`opcode_erase_32k`, (1-1-0) mode (if specified)
        * :data:`Command.EraseData64K`: :py:`opcode_erase_64k`, (1-1-0) mode (if specified)
        * :data:`Command.ProgramData`: :data:`Opcode.PageProgram`, (1-1-1) mode
          (if :py:`page_size` is specified)

        Configures the :meth:`data_operation_prologue` method to execute
        :py:`data_operation_prologue`.

        This function is intended for "lowest common denominator" configuration in absence of
        SFDP data. If you need to configure a different or more complex command set, you should
        add the necessary mappings directly.
        """
        self.data_operation_prologue = data_operation_prologue # type:ignore
        self[Command.ReadData] = Instruction.spi_1_1_1(Opcode.Read,
            address_octets=address_bytes, direction="read", data_repeats=True)
        if opcode_erase_4k is not None:
            self[Command.EraseData4K] = Instruction.spi_1_1_0(opcode_erase_4k,
                address_octets=address_bytes)
        if opcode_erase_32k is not None:
            self[Command.EraseData32K] = Instruction.spi_1_1_0(opcode_erase_32k,
                address_octets=address_bytes)
        if opcode_erase_64k is not None:
            self[Command.EraseData64K] = Instruction.spi_1_1_0(opcode_erase_64k,
                address_octets=address_bytes)
        self[Command.ProgramData] = Instruction.spi_1_1_1(Opcode.PageProgram,
            address_octets=address_bytes, direction="write", data_octets=page_size)

    # Disable dual and quad instructions by default; these sometimes have poorly documented or
    # board-specific constraints, while single SPI mode is always reliable.
    def use_jesd216(self, sfdp: SFDPCollection,
            enable_dual: bool = False, enable_quad: bool = False):
        """Use instructions specified by :py:`sfdp`.

        To determine the highest throughput instruction, all the possible (1-`x`-`y`) modes are
        ordered first by `y` and then `x`.

        Adds the following mappings:

        * :data:`Command.ReadData` (fastest available, considering :py:`enable_dual` and
          :py:`enable_quad`)
        * :data:`Command.EraseData4K` (if available)
        * :data:`Command.EraseData32K` (if available)
        * :data:`Command.EraseData64K` (if available)
        * :data:`Command.ProgramData`: :data:`Opcode.PageProgram`, (1-1-1) mode
        * :data:`Command.Enter4ByteMode`: :data:`Opcode.Enter4ByteMode` (if relevant)
        * :data:`Command.Leave4ByteMode`: :data:`Opcode.Leave4ByteMode` (if relevant)

        Configures the :meth:`data_operation_prologue` method to execute any appropriate
        mode switch or register access sequence for 4-byte addressing.

        Raises
        ------
        ValueError
            If JEDEC flash parameters table is not present.
        ValueError
            If JEDEC flash parameters table contains unsupported parameters for required features.
        """
        if (jedec_params := sfdp.jedec_flash_table) is None:
            raise ValueError("JEDEC flash parameters table not present")

        if jedec_params.address_byte_count == {3}:
            address_bytes = 3
        elif jedec_params.address_byte_count == {4}:
            address_bytes = 4
        elif jedec_params.address_byte_count == {3, 4}:
            enter_method = jedec_params.enter_4_byte_addressing
            if enter_method & (SFDPJEDECEnter4ByteAddressingMethods.CommandB7h |
                               SFDPJEDECEnter4ByteAddressingMethods.WriteEnableCommandB7h):
                # All data manipulation instructions are assumed to be invoked only when the flash
                # is in the 4-byte mode, and the prologue sequence is configured to make sure this
                # is always the case.
                self[Command.Enter4ByteMode] = Instruction.spi_1_0_0(Opcode.Enter4ByteMode)
                if enter_method & SFDPJEDECEnter4ByteAddressingMethods.WriteEnableCommandB7h:
                    self.data_operation_prologue = \
                        lambda address: [self[Command.WriteEnable], self[Command.Enter4ByteMode]]
                else:
                    self.data_operation_prologue = \
                        lambda address: [self[Command.Enter4ByteMode]]
                address_bytes = 4
            else:
                raise ValueError(
                    f"mode switching required, but no compatible mode switching methods found "
                    f"(enter_4_byte_addressing={jedec_params.enter_4_byte_addressing:010b})")

            exit_method = jedec_params.exit_4_byte_addressing
            if exit_method & (SFDPJEDECExit4ByteAddressingMethods.CommandE9h |
                              SFDPJEDECExit4ByteAddressingMethods.WriteEnableCommandE9h):
                self[Command.Leave4ByteMode] = Instruction.spi_1_0_0(Opcode.Leave4ByteMode)
            else:
                # We would rather always be in the 4-byte mode, so not being able to exit it
                # is not a problem at all. (Some devices can enter 4-byte mode but not exit
                # except by being reset, despite how absurd that sounds.)
                pass
        else:
            assert False

        # Map best read instruction.
        read_instrs = []
        read_instrs.append(Instruction.spi_1_1_1(Opcode.Read,
            address_octets=address_bytes, direction="read", data_repeats=True))
        for spi_mode, instr_params in jedec_params.fast_read_modes.items():
            if spi_mode.uses_dual and not enable_dual:
                continue
            if spi_mode.uses_quad and not enable_quad:
                continue
            match spi_mode:
                case CommandMode(1, x_address, x_data):
                    read_instrs.append(Instruction(
                        opcode=instr_params.opcode,
                        x_opcode=1, x_address=x_address, x_data=x_data,
                        address_octets=address_bytes,
                        mode_cycles=instr_params.mode_clocks,
                        dummy_cycles=instr_params.wait_states,
                        direction=Direction.Read,
                        data_octets=None, data_repeats=True,
                    ))
        self[Command.ReadData] = max(read_instrs, key=lambda instr: (instr.x_data, instr.x_address))

        # Map erase instructions.
        for erase_size, erase_opcode in jedec_params.sector_sizes.items():
            command = Command.erase_for_size(erase_size)
            self[command] = Instruction.spi_1_1_0(erase_opcode,
                address_octets=address_bytes)

        # Map best program instruction.
        self[Command.ProgramData] = Instruction.spi_1_1_1(Opcode.PageProgram,
            address_octets=address_bytes, direction="write",
            data_octets=jedec_params.page_size)

    @property
    def min_erase_size(self) -> int | None:
        """Smallest supported erase size."""
        for size in sorted(Command.all_erase_sizes()):
            if Command.erase_for_size(size) in self:
                return size
        return None

    def data_operation_prologue(self, address: int) -> InstructionSequence:
        """Compute prologue sequence for a data operation starting at :py:`address`.

        Returns an (address-specific) sequence of commands or write instructions that must be
        executed to prepare for any operation (reading, erasing, or programming) addressing
        the data region. A preceding call to :meth:`use_explicit` or :meth:`use_jesd216` may
        affect the specific sequence returned by this method.

        .. danger::

            If the steps above are not followed exactly, the outcome of any read, erase, or program
            operations may be completely unpredictable.
        """
        return []
