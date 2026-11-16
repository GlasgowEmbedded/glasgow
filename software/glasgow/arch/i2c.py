# Ref: I2C-bus specification and user manual Rev 7.0
# Document Number: UM10204
# Accession: G00101

from typing import Self
from enum import Enum
from dataclasses import dataclass
import re


__all__ = ["ProbeStep", "ProbeDevice"]


@dataclass
class ProbeStep:
    """One step of a device probe sequence.

    Describes an action taken by an I²C controller taken to check whether a specific I²C target
    address matches the identity of a particular chip.

    While probe sequences can be created by constructing the underlying Python objects, it is
    recomended to use :meth:`parse` with a compact string representation. Not all probe sequences
    are well-formed; use :meth:`verify` to ensure that a sequence describes a legal I²C transaction.

    The string representation is a whitespace-separated sequence of the following tokens (chosen
    to resemble the diagrams in the I²C specification):

    * ``S``: START condition.
    * ``Sr``: repeated START condition.
    * ``P``: STOP condition.
    * ``AW``: WRITE target address.
    * ``AR``: READ target address.
    * ``0dDDD`` where ``DDD`` is a 1 to 3 digit decimal number: data to read or write, in decimal.
    * ``0xHH`` where ``H`` is a hex digit or ``?``: data to read or write, in hexadecimal.
    * ``0bBBBBBBBB`` where ``B`` is a binary digit or ``?``: data to read or write, in binary.

    The ``AW`` and ``AR`` tokens refer to the actual device address, which is not known until
    the moment when the probing is done; probe sequences are address-independent.

    Consider the following example probe sequences:

    * ``S AW 0xD0 Sr AR 0x60 P``: detects Bosch BME280 sensors by writing :py:`0xD0` to select
      the register, then reading the register value and comparing it with :py:`0x60`.
    * ``S AW 117 Sr AR 0b?110100? P``: detects InvenSense MPU-60X0 by writing :py:`117` to select
      the register, then reading the register value and comparing it with :py:`0b01101000` while
      masking off (ignoring) the first and last bit.
    """

    class Type(Enum):
        Start     = "S"
        RepStart  = "Sr"
        Stop      = "P"
        AddrWrite = "AW"
        AddrRead  = "AR"
        DataWrite = "DW"
        DataRead  = "DR"

    type: Type
    """Step type."""

    data: bytes | None = None
    """Data bytes. Only present if :py:`type in (Type.DataWrite, Type.DataRead)`."""

    mask: bytes | None = None
    """Mask bytes. Only present if :py:`type in (Type.MaskWrite, Type.MaskRead)`."""

    def __post_init__(self):
        match self.type:
            case self.Type.Start | self.Type.RepStart | self.Type.Stop:
                assert self.data is None and self.mask is None
            case self.Type.DataWrite:
                assert self.data is not None and self.mask == b"\xFF" * len(self.data)
            case self.Type.DataRead:
                assert self.data is not None and self.mask is not None

    @classmethod
    def parse(cls, source: str) -> list[Self]:
        """Parse a string into a probe sequence.

        Returns a sequence of steps corresponding to :py:`source`. Does not perform any semantic
        correctness checks; use the :meth:`check` method for that.

        Raises
        ------
        SyntaxError
            If the syntax of :py:`source` is invalid.
        """

        def parse_data(item: str, width: int):
            return sum(0x0 if digit == "?" else int(digit, 1 << width) << width * index
                for index, digit in enumerate(item[::-1]))

        def parse_mask(item: str, width: int):
            return sum(0x0 if digit == "?" else ((1 << width) - 1) << width * index
                for index, digit in enumerate(item[::-1]))

        steps = []
        data = bytearray()
        mask = bytearray()
        is_read = False
        for step_source in source.split():
            if step_source in ("S", "Sr", "P", "AW", "AR"):
                if data:
                    if is_read:
                        steps.append(ProbeStep(ProbeStep.Type.DataRead, bytes(data), bytes(mask)))
                    else:
                        steps.append(ProbeStep(ProbeStep.Type.DataWrite, bytes(data), bytes(mask)))
                    data.clear()
                    mask.clear()
                steps.append(ProbeStep(ProbeStep.Type(step_source)))
                is_read = (step_source == "AR")
            elif (m := re.match(r"^0d([0-9]{1,3})$", step_source)) and \
                    (val := int(m[1], 10)) <= 0xFF:
                data.append(val)
                mask.append(0xFF)
            elif m := re.match(r"^0x([0-9a-fA-F?]{2})$", step_source):
                data.append(parse_data(m[1], 4))
                mask.append(parse_mask(m[1], 4))
            elif m := re.match(r"^0b([01?]{8})$", step_source):
                data.append(parse_data(m[1], 1))
                mask.append(parse_mask(m[1], 1))
            else:
                raise SyntaxError(f"invalid probe step syntax: {step_source!r}")
        return steps

    @classmethod
    def check(cls, steps: list[Self]):
        """Verify well-formedness of a probe sequence.

        Raises
        ------
        ValueError
            If the sequence is not allowed by the I²C specification.
        """
        state = "Idle"
        for step in steps:
            match state, step.type:
                case "Idle", cls.Type.Start:
                    state = "Addr"
                case "Addr", cls.Type.AddrWrite:
                    state = "DataWrite"
                case "Addr", cls.Type.AddrRead:
                    state = "DataRead"
                case ("DataWrite", cls.Type.DataWrite) | ("DataRead", cls.Type.DataRead):
                    state = "Done"
                case "Done", cls.Type.RepStart:
                    state = "Addr"
                case "Done", cls.Type.Stop:
                    state = "Idle"
                case _:
                    raise ValueError(f"step {step!r} is not valid in state {state!r}")
        if state != "Idle":
            raise ValueError(f"state is not 'Idle' at end of transaction")
        return steps

    def __str__(self) -> str:
        """Unparse the step.

        Converts the step to a representation recognized by :meth:`parse`.
        """
        match self.type:
            case (self.Type.Start | self.Type.RepStart | self.Type.Stop |
                  self.Type.AddrWrite | self.Type.AddrRead):
                return self.type.value
            case self.Type.DataRead | self.Type.DataWrite:
                items = []
                for data, mask in zip(self.data, self.mask):
                    if mask == 0xFF:
                        items.append(f"0x{data:02X}")
                    else:
                        items.append(f"0b{"".join(
                            f"{(data >> bit) & 1}" if (mask >> bit) & 1 else "?"
                            for bit in range(0, 8)[::-1]
                        )}")
                return " ".join(items)


@dataclass
class ProbeDevice:
    vendor:    str
    """Vendor name.

    If the company has been acquired, list the old and the new names separated by ``/``, e.g.:
    ``InvenSense/TDK``.
    """

    product:   str
    """Product name.

    If the probe sequence identifies a set of products, separate every product name by ``/``. e.g.:
    ``FUSB302BMPX/FUSB302BVMPX/FUSB302BUCX``.
    """

    addresses: set[int]
    """Set of every I2C address the device can be configured to use."""

    sequence:  list[ProbeStep]
    """Probe sequence positively identifying this specific device."""

    def __init__(self, vendor: str, product: str, addresses: set[int], sequence: str):
        self.vendor    = vendor
        self.product   = product
        self.addresses = addresses
        self.sequence  = ProbeStep.parse(sequence)

        ProbeStep.check(self.sequence)

    @property
    def name(self) -> str:
        """Device name.

        Returns :py:`f"{self.vendor} {self.product}"`.
        """
        return f"{self.vendor} {self.product}"

    def __repr__(self):
        properties = [
            f"{self.vendor!r}",
            f"{self.product!r}",
            f"addresses=[{', '.join(f"{item:#09b}" for item in self.addresses)}]",
            f"sequence='{' '.join(f"{item}" for item in self.sequence)}'",
        ]
        return f"ProbeChip({', '.join(properties)})"
