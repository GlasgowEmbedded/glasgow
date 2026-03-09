# Common (Q)SPI NAND/NOR/PSRAM instruction set specification facilities.
#
# There are many devices which have closely related and to some extent compatible instruction sets.
# There is no single source of truth defining acceptable instruction formats or even the overall
# framing, but in practice there is sufficient commonality that it is possible to describe
# an "arbitrary (Q)SPI instruction" in a mostly reliable way.

from enum import Enum
from dataclasses import dataclass
from typing import Literal
from collections.abc import Buffer, Iterator


__all__ = ["Direction", "CommandMode", "Instruction", "BaseCommandSet"]


class Direction(Enum):
    """Transfer direction.

    Specified relative to the controller.
    """

    Read  = "read"
    Write = "write"

    def __repr__(self):
        return f"{self.__class__.__qualname__}.{self.name}"


@dataclass(frozen=True)
class CommandMode:
    """Command mode.

    Specifies gearing for the opcode, address, and data phase.
    """

    opcode: Literal[0, 1, 2, 4]
    """Gearing of the opcode phase."""

    address: Literal[0, 1, 2, 4]
    """Gearing of the address phase.

    If :py:`0`, there is no address phase.
    """

    data: Literal[0, 1, 2, 4]
    """Gearing of the data phase.

    If :py:`0`, there is no data phase.
    """

    @property
    def uses_dual(self) -> bool:
        """Whether any phase uses dual SPI."""
        return 2 in (self.opcode, self.address, self.data)

    @property
    def uses_quad(self) -> bool:
        """Whether any phase uses quad SPI."""
        return 4 in (self.opcode, self.address, self.data)

    def __str__(self) -> str:
        return f"{self.opcode}-{self.address}-{self.data}"


@dataclass(frozen=True, kw_only=True)
class Instruction[OpcodeT: int]:
    """Instruction format.

    The :py:`Instruction` describes the framing of each part (opcode, address, dummy, and data)
    of an abstract (Q)SPI instruction. The :py:`(x_opcode, x_address, x_data)` tuple corresponds
    to the SFDP ``x-y-z`` terminology (e.g. ``1-1-4`` for quad output has
    :py:`x_opcode, x_address, x_data = 1, 1, 4`). These "gearing" parameters indicate how many
    bits are transmitted per cycle, e.g. it takes :py:`8 // x_opcode` cycles to transmit
    the instruction opcode.
    """

    opcode: OpcodeT
    """Instruction opcode (one octet)."""

    x_opcode: Literal[0, 1, 2, 4] = 1
    """Gearing of the opcode phase."""

    x_address: Literal[0, 1, 2, 4] = 1
    """Gearing of the address phase.

    If :py:`0`, there is no address phase, and :data:`address_octets` must also be :py:`0`.
    """

    x_data: Literal[0, 1, 2, 4] = 1
    """Gearing of the data phase.

    If :py:`0`, there is no data phase, and :data:`data_octets` must also be :py:`0`.
    """

    address_octets: int = 0
    """Length of the address phase, in octets.

    Typically, between 0 and 4 inclusive, but this is not a hard requirement.
    """

    mode_cycles: int = 0
    """Length of the mode phase, in cycles.

    Typically, between 0 and 4 inclusive, and an integer multiple of the number of cycles needed
    to exchange a byte in the address phase, but this is not a hard requirement.
    """

    dummy_cycles: int = 0
    """Length of the dummy phase, in cycles.

    Typically, either :py:`0` or :py:`8 // x_address`, but this is not guaranteed: certain devices
    require dummy phase of a length that is not an integer multiple of the number of cycles needed
    to exchange a byte in the address or data phase.
    """

    direction: Direction | None = None
    """Direction of the data phase.

    Must be :py:`None` if and only if :py:`x_data == 0`.
    """

    data_octets: int | None = 0
    """Length of the data phase, in octets.

    Typically, variable (indicated as :py:`None`), but certain commands return a fixed amount of
    data. See also :attr:`data_repeats`.
    """

    data_repeats: bool = False
    """Whether the data output repeats.

    If true, then the output repeats after transferring more than :attr:`data_octets`. For status
    registers, each repeat indicates up-to-date state at the moment of the transfer.

    If false, data output might return all-zeroes, all-ones, or be undriven after transferring
    :attr:`data_octets`, and this condition should be avoided.
    """

    def __post_init__(self):
        if self.x_address == 0:
            assert self.address_octets == 0
        else:
            assert self.address_octets > 0

        if self.x_data == 0:
            assert self.direction is None
            assert self.data_octets == 0
            assert not self.data_repeats
        else:
            assert self.direction is not None
            assert self.data_octets != 0

        if self.mode_cycles != 0:
            # NOTE(whitequark): There is no well-defined meaning for these unless
            # `x_address == x_data`, as far as I know from reading datasheets.
            # JESD216 doesn't seem to know either.
            assert self.direction is not None
            assert self.x_address == self.x_data

    @classmethod
    def spi_1_0_0(cls, opcode: OpcodeT):
        """SPI instruction with 1-0-0 gearing."""
        return cls(
            opcode=opcode, x_opcode=1, x_address=0, x_data=0,
        )

    @classmethod
    def spi_1_1_0(cls, opcode: OpcodeT, *, address_octets: int = 0):
        """SPI instruction with 1-1-0 gearing."""
        return cls(
            opcode=opcode, x_opcode=1, x_address=1, x_data=0, address_octets=address_octets,
        )

    @classmethod
    def spi_1_0_1(cls, opcode: OpcodeT, *,
            dummy_cycles: int = 0, direction: Direction | Literal["read", "write"],
            data_octets: int | None = None, data_repeats: bool = False):
        """SPI instruction with 1-0-1 gearing."""
        return cls(
            opcode=opcode, x_opcode=1, x_address=0, x_data=1, dummy_cycles=dummy_cycles,
            direction=Direction(direction), data_octets=data_octets, data_repeats=data_repeats,
        )

    @classmethod
    def spi_1_1_1(cls, opcode: OpcodeT, *, address_octets: int = 0,
            dummy_cycles: int = 0, direction: Direction | Literal["read", "write"],
            data_octets: int | None = None, data_repeats: bool = False):
        """SPI instruction with 1-1-1 gearing."""
        return cls(
            opcode=opcode, x_opcode=1, x_address=1, x_data=1, address_octets=address_octets,
            dummy_cycles=dummy_cycles, direction=Direction(direction), data_octets=data_octets,
            data_repeats=data_repeats,
        )

    @classmethod
    def dspi_1_1_2(cls, opcode: OpcodeT, *, address_octets: int = 0,
            mode_cycles: int = 0, dummy_cycles: int = 0,
            direction: Direction | Literal["read", "write"],
            data_octets: int | None = None, data_repeats: bool = False):
        """Dual SPI instruction with 1-1-2 gearing."""
        return cls(
            opcode=opcode, x_opcode=1, x_address=1, x_data=2, address_octets=address_octets,
            mode_cycles=mode_cycles, dummy_cycles=dummy_cycles, direction=Direction(direction),
            data_octets=data_octets, data_repeats=data_repeats,
        )

    @classmethod
    def dspi_1_2_2(cls, opcode: OpcodeT, *, address_octets: int = 0,
            mode_cycles: int = 0, dummy_cycles: int = 0,
            direction: Direction | Literal["read", "write"],
            data_octets: int | None = None, data_repeats: bool = False):
        """Dual SPI instruction with 1-2-2 gearing."""
        return cls(
            opcode=opcode, x_opcode=1, x_address=2, x_data=2, address_octets=address_octets,
            mode_cycles=mode_cycles, dummy_cycles=dummy_cycles, direction=Direction(direction),
            data_octets=data_octets, data_repeats=data_repeats,
        )

    @classmethod
    def qspi_1_1_4(cls, opcode: OpcodeT, *, address_octets: int = 0,
            mode_cycles: int = 0, dummy_cycles: int = 0,
            direction: Direction | Literal["read", "write"],
            data_octets: int | None = None, data_repeats: bool = False):
        """Quad SPI instruction with 1-1-4 gearing."""
        return cls(
            opcode=opcode, x_opcode=1, x_address=1, x_data=4, address_octets=address_octets,
            mode_cycles=mode_cycles, dummy_cycles=dummy_cycles, direction=Direction(direction),
            data_octets=data_octets, data_repeats=data_repeats,
        )

    @classmethod
    def qspi_1_4_4(cls, opcode: OpcodeT, *, address_octets: int = 0,
            mode_cycles: int = 0, dummy_cycles: int = 0,
            direction: Direction | Literal["read", "write"],
            data_octets: int | None = None, data_repeats: bool = False):
        """Quad SPI instruction with 1-4-4 gearing."""
        return cls(
            opcode=opcode, x_opcode=1, x_address=4, x_data=4, address_octets=address_octets,
            mode_cycles=mode_cycles, dummy_cycles=dummy_cycles, direction=Direction(direction),
            data_octets=data_octets, data_repeats=data_repeats,
        )

    @property
    def mode(self) -> CommandMode:
        """Command mode of this instruction."""
        return CommandMode(self.x_opcode, self.x_address, self.x_data)

    def check_usage(self, address: int | None, data: Buffer | None, length: int | None):
        if self.x_address == 0 and address is not None:
            raise ValueError(
                "instruction does not have an address phase, but an address was provided")
        if self.x_address != 0 and address is None:
            raise ValueError(
                "instruction has an address phase, but an address was not provided")
        match (self.x_data, self.direction):
            case (0, _):
                if data is not None:
                    raise ValueError(
                        "instruction does not have a data phase, but data was provided")
                if length is not None:
                    raise ValueError(
                        "instruction does not have a data phase, but length was provided")
            case (_, Direction.Read):
                if data is not None:
                    raise ValueError(
                        "instruction has a read data phase, but data was provided")
                if length is None and self.data_octets is None:
                    raise ValueError(
                        "instruction has a read data phase with a variable length, but length "
                        "was not provided")
            case (_, Direction.Write):
                if length is not None:
                    raise ValueError(
                        "instruction has a write data phase, but length was provided")
                if data is None:
                    raise ValueError(
                        "instruction has a write data phase, but data was not provided")

    def __str__(self) -> str:
        if type(self.opcode) is int:
            return f"{self.opcode:02X}h"
        else:
            return f"{self.opcode}"


class BaseCommandSet[CommandT]:
    """Base class for command sets.

    A command set is a mapping from an abstract command (e.g. "Erase 4K Sector") to a specific
    concrete instruction (e.g. "20h, 1-0-0, 3 address bytes"). Maintaining this mapping is necessary
    because similar devices from different vendors, different variants of the same device from
    the same vendor, or the exact same device with different volatile configuration, may have
    the same abstract commands represented by different concrete opcodes.

    Technology-specific command sets should inherit from this class and include methods that parse
    memory architecture self-description data (if available) or assist in manually configuring
    the instruction set; for example, see :class:`glasgow.arch.qspi.nor.CommandSet`.
    """

    def __init__(self):
        self._commands: dict[CommandT, Instruction] = {}

    def update(self, updates: dict[CommandT, Instruction]):
        """Add multiple :py:`CommandT`-:class:`Instruction` mappings.

        Overwrites mappings that already exist.
        """
        self._commands.update(updates)

    def __setitem__(self, command: CommandT, instruction: Instruction):
        """Add a single :py:`CommandT`-:class:`Instruction` mapping.

        Overwrites mappings that already exist.
        """
        self._commands[command] = instruction

    def __getitem__(self, command: CommandT) -> Instruction:
        """Map a :py:`CommandT` to a specific :class:`Instruction`.

        Raises
        ------
        KeyError
            If the mapping does not exist.
        """
        return self._commands[command]

    def __contains__(self, command: CommandT) -> bool:
        """Check whether :py:`command` is mapped."""
        return command in self._commands

    def __iter__(self) -> Iterator[CommandT]:
        """Iterate through every mapped :py:`CommandT`."""
        return iter(self._commands)
