"""Backend-independent resources used to build and control applets.

An :class:`AbstractAssembly` connects Amaranth gateware to physical ports, host-accessible
registers, and bytestream pipes. Applet interfaces allocate these resources when building,
then use the returned register and pipe objects from asynchronous host code. Hardware and
simulation assemblies implement the same interface.

The pins of an applet, and the supplies that power them, are declared as a dataclass with
:func:`glasgow_ports`; see :meth:`AbstractAssembly.add_ports`.
"""

from __future__ import annotations
from abc import ABCMeta, abstractmethod
from typing import (Self, Any, Literal, Union, dataclass_transform, overload,
    get_args, get_origin, get_type_hints)
from contextlib import contextmanager
from collections.abc import Buffer, Callable, Generator, Iterable, Mapping
from dataclasses import dataclass
import argparse
import dataclasses
import re
import enum
import math
import types

from amaranth import *
from amaranth.lib import io, stream

from glasgow.support import logging
from glasgow.gateware.ports import PortGroup
from glasgow.gateware import octoram


__all__ = [
    "ClockingError", "VoltageConflictError", "AssemblyBuildError",
    "PullState", "GlasgowPort", "GlasgowVio", "GlasgowSupply", "GlasgowPin", "GlasgowAnalog",
    "glasgow_ports",
    "AbstractRORegister", "AbstractRWRegister", "ClockDivisor", "DRAMOptions",
    "AbstractInPipe", "AbstractOutPipe", "AbstractInOutPipe",
    "AbstractAssembly"
]


class ClockingError(Exception):
    """A requested clock frequency cannot be represented by its divisor register."""

    pass


class PullState(enum.Enum):
    """Logical pin pull state: floating, high, or low.

    Inverting a state with :py:`~state` exchanges high and low and leaves floating unchanged.
    :py:`state ^ invert` conditionally inverts it.
    """

    Float = "float"
    High  = "high"
    Low   = "low"

    def enabled(self) -> bool:
        """Return whether this state enables a pull resistor."""
        return self != self.Float

    def __invert__(self) -> PullState:
        match self:
            case self.Float: return self
            case self.High:  return self.Low
            case self.Low:   return self.High

    def __xor__(self, invert: bool) -> PullState:
        return ~self if invert else self

    def __rxor__(self, invert: bool) -> PullState:
        return ~self if invert else self

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}.{self.name}"

    def __str__(self) -> str:
        return self.value


class GlasgowPort(enum.Enum):
    """Physical port identifier, or :attr:`ALL` for all supply-capable ports.

    The ports available on a device depend on its hardware revision. :attr:`ALL` is a voltage
    configuration selector and cannot identify a pin.
    """

    A = "A"
    B = "B"
    C = "C"
    D = "D"
    SYN = "SYN"
    LED = "LED"
    ALL = "*"

    @property
    def has_supply(self) -> bool:
        """Returns :py:`True` if the port has power supply and sensing, :py:`False` otherwise."""
        match self:
            case self.A | self.B | self.C | self.D | self.ALL:
                return True
            case _:
                return False

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}.{self.name}"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class GlasgowVio:
    """Port voltage request, specified in volts or by sensing another port.

    Supply exactly one of :py:`value` and :py:`sense`. For example, :py:`GlasgowVio(3.3)`
    requests 3.3 V, while :py:`GlasgowVio(sense="A")` requests mirroring port A's voltage.
    Creating a request does not change the device configuration; pass it to
    :meth:`AbstractAssembly.set_port_voltage` or :meth:`AbstractAssembly.use_voltage`.
    """

    value: float | None       = None
    sense: GlasgowPort | None = None

    def __init__(self, value: float | None = None, *, sense: GlasgowPort | str | None = None):
        if (value is None and sense is None) or (value is not None and sense is not None):
            raise ValueError("exactly one of voltage value or a port to be sensed may be present")
        if sense is not None and not GlasgowPort(sense).has_supply:
            raise ValueError(f"port {sense} is not capable of sensing voltage")
        object.__setattr__(self, "value", float(value) if value is not None else None)
        object.__setattr__(self, "sense", GlasgowPort(sense) if sense is not None else None)

    @classmethod
    def parse(cls, value: str) -> dict[GlasgowPort, GlasgowVio]:
        """Parse comma-separated CLI voltage clauses into per-port requests.

        Examples: :py:`"3.3"` or :py:`"*=3.3"` selects all ports; :py:`"AB=3.3"` selects A
        and B; :py:`"B=SA"` mirrors A onto B. Later clauses replace earlier ones for the same
        key. Invalid clauses raise :exc:`ValueError`.
        """
        result = {}
        for clause in value.split(","):
            if m := re.match(r"^(\*=)?([0-9]+(\.[0-9]+)?)$", clause):
                volts = float(m.group(2))
                result[GlasgowPort.ALL] = GlasgowVio(value=volts)
            elif m := re.match(r"^([A-Z]+)=([0-9]+(\.[0-9]+)?)$", clause):
                ports, volts = m.group(1), float(m.group(2))
                for port in ports:
                    result[GlasgowPort(port)] = GlasgowVio(value=volts)
            elif m := re.match(r"^([A-Z]+)=S([A-Z])$", clause):
                ports, sense = m.group(1), m.group(2)
                for port in ports:
                    result[GlasgowPort(port)] = GlasgowVio(sense=sense)
            else:
                raise ValueError(f"{clause!r} is not a valid voltage argument")
        return result

    def __str__(self) -> str:
        if self.sense is not None:
            return f"S{self.sense}"
        assert self.value is not None # guaranteed by `__init__`
        return f"{self.value:.2f}"


class AssemblyBuildError(Exception):
    """Raised when an applet requests something that an assembly cannot provide, such as adding
    a resource after the assembly has been built, or a resource the hardware revision lacks.

    This is a mistake in the applet or its invocation rather than a bug in the assembly, and it is
    frequently encountered by people new to writing applets.
    """


class VoltageConflictError(Exception):
    """Raised when two requests for the voltage of the same port disagree, or when a requested
    voltage is outside of the range a supply declares to be safe.
    """


@dataclass(frozen=True)
class _SupplyField:
    # Metadata attached to a field created by `GlasgowSupply.field()`.
    voltage_min: float
    voltage_max: float
    current_max: float | None
    option:      str | None


@dataclass(frozen=True)
class _PinField:
    # Metadata attached to a field created by `GlasgowPin.field()`.
    width:   tuple[int, ...]
    default: str | bool | int | None
    invert:  bool
    power:   Any
    pull:    PullState | None
    help:    str | None


_FIELD_METADATA_KEY = "glasgow"


def _width_choices(width: int | range | Iterable[int]) -> tuple[int, ...]:
    match width:
        case int():
            choices = (width,)
        case _:
            choices = tuple(sorted(set(width)))
    if not choices or choices[0] < 1:
        raise ValueError(f"pin width must be at least 1 (use an optional field to allow no pins), "
                         f"not {width!r}")
    return choices


@dataclass(frozen=True)
class GlasgowSupply:
    """Power supply of a group of pins.

    A supply is either set to a fixed :py:`voltage`, or set to follow the voltage measured on the
    sense input of a port, :py:`sense`. A port may follow its own sense input, which is how the
    voltage of the target is mirrored. If neither is specified, the voltage of the ports it
    powers is left unchanged.

    A :py:`GlasgowSupply` instance can be used as the default value of a field in a ports
    dataclass to declare a supply that is not configurable by the user; use
    :py:`GlasgowSupply.field` for a configurable one. Pins refer to their supply using the
    :py:`power=` argument of :py:`GlasgowPin.field`.

    Attributes
    ----------
    voltage : float | None
        Voltage, in volts, that every port powered by this supply is set to.
    sense : GlasgowPort | None
        Port whose sense input every port powered by this supply follows.
    current_max : float | None
        Maximum current, in amperes, that the device powered by this supply is expected to draw.
    """

    voltage:     float | None       = None
    sense:       GlasgowPort | None = None
    current_max: float | None       = None

    def __post_init__(self):
        if self.voltage is not None and self.sense is not None:
            raise ValueError("at most one of voltage value or a port to be sensed may be present")
        if self.voltage is not None:
            object.__setattr__(self, "voltage", float(self.voltage))
        if self.sense is not None:
            sense = GlasgowPort(self.sense)
            if not sense.has_supply:
                raise ValueError(f"port {sense} is not capable of sensing voltage")
            object.__setattr__(self, "sense", sense)
        if self.current_max is not None:
            object.__setattr__(self, "current_max", float(self.current_max))

    @classmethod
    def field(cls, *, voltage_min: float = 1.8, voltage_max: float = 5.0,
              current_max: float | None = None,
              option: str | None = None) -> Any:
        """Declare a user-configurable supply.

        Returns a :py:`dataclasses.field` that, when used in a ports dataclass, causes a command
        line option to be generated for the supply. If the dataclass has exactly one such supply,
        the option is :py:`-V/--voltage`; otherwise it is :py:`--<name>-voltage`, where
        ``<name>`` is the field name without a ``_supply`` suffix.

        Parameters
        ----------
        voltage_min, voltage_max : float
            Inclusive range of voltages, in volts, that the powered device operates correctly at.
            Values outside this range are rejected. The defaults are the range Glasgow itself can
            supply; narrow them to what the device is rated for.
        current_max : float | None
            Maximum current, in amperes, that the powered device is expected to draw.
        option : str | None
            Name of the command line option, without leading dashes, overriding the default.
        """
        if voltage_min > voltage_max:
            raise ValueError(f"voltage_min {voltage_min} is greater than voltage_max {voltage_max}")
        return dataclasses.field(metadata={_FIELD_METADATA_KEY:
            _SupplyField(float(voltage_min), float(voltage_max),
                         None if current_max is None else float(current_max), option)})

    @classmethod
    def parse(cls, value: str) -> GlasgowSupply:
        """Parse a voltage specification: a number of volts (:py:`"3.3"`) or the sense input of
        a port to follow (:py:`"SA"`).
        """
        if m := re.match(r"^([0-9]+(\.[0-9]+)?)$", value):
            return cls(voltage=float(m.group(1)))
        elif m := re.match(r"^S([A-Z])$", value):
            try:
                return cls(sense=GlasgowPort(m.group(1)))
            except ValueError as e:
                raise ValueError(f"{value!r} is not a valid voltage: {e}") from None
        else:
            raise ValueError(f"{value!r} is not a valid voltage (try '3.3', or 'SA' to follow "
                             f"the voltage sensed on port A)")

    def __str__(self):
        if self.sense is not None:
            return f"S{self.sense}"
        if self.voltage is not None:
            return f"{self.voltage:.2f}"
        return "unchanged"


@dataclass(frozen=True)
class GlasgowPin:
    """Digital pin identifier with optional logical inversion.

    :py:`GlasgowPin(GlasgowPort.A, 3, invert=True)` identifies A3 with inverted polarity.
    :py:`~pin` toggles inversion. Pin availability is checked by the assembly when allocated.

    To declare the pins of an applet, use :meth:`field` in a dataclass created by
    :func:`glasgow_ports`.
    """

    port:   GlasgowPort
    number: int
    invert: bool = False

    def __init__(self, port: GlasgowPort | str, number: int, *, invert: bool = False):
        if GlasgowPort(port) == GlasgowPort.ALL:
            raise ValueError("port ALL cannot identify a pin")
        object.__setattr__(self, "port", GlasgowPort(port))
        object.__setattr__(self, "number", int(number))
        object.__setattr__(self, "invert", bool(invert))

    @classmethod
    def parse(cls, value: str) -> tuple[GlasgowPin, ...]:
        """Parse a comma-separated pin list, preserving order.

        Ranges include both endpoints and may descend: :py:`"A3:1"` selects A3, A2, A1.
        A trailing :py:`"#"` inverts a pin or range. Empty clauses, :py:`"-"`, and :py:`"NC"`
        select no pins. Invalid clauses raise :exc:`ValueError`.
        """
        result = []
        for clause in value.split(","):
            if clause.upper() in ("", "-", "NC"):
                pass
            elif m := re.match(r"^([A-Z]+)([0-9]+)(#)?$", clause):
                port, number, invert = GlasgowPort(m.group(1)), int(m.group(2)), bool(m.group(3))
                result.append(cls(port=port, number=number, invert=invert))
            elif m := re.match(r"^([A-Z]+)([0-9]+):([0-9]+)(#)?$", clause):
                port, pin_first, pin_last, invert = \
                    GlasgowPort(m.group(1)), int(m.group(2)), int(m.group(3)), bool(m.group(4))
                if pin_last >= pin_first:
                    for number in range(pin_first, pin_last + 1, +1):
                        result.append(cls(port=port, number=number, invert=invert))
                else:
                    for number in range(pin_first, pin_last - 1, -1):
                        result.append(cls(port=port, number=number, invert=invert))
            else:
                raise ValueError(f"{clause!r} is not a valid pin "
                     "(try 'A3', 'A5,B1', 'B4:7', or specify 'NC' to leave unconnected)")
        return tuple(result)

    @classmethod
    def field(cls, *, width: int | range | Iterable[int] = 1,
              default: str | bool | int | None = None, invert: bool = False, power: Any = None,
              pull: PullState | str | None = None, help: str | None = None) -> Any:
        """Declare an applet pin, or a group of pins, in a ports dataclass.

        Returns a :py:`dataclasses.field` that causes a command line option to be generated
        for the pins. The field should be annotated as :py:`io.PortLike`, or
        :py:`io.PortLike | None` if the pins may be left unconnected. The dataclass must be
        created with :py:`kw_only=True`, which :py:`glasgow_ports` does.

        Each pin names the supply that powers it, which must be a field declared earlier in the
        same class. For example, this declares an I²C bus whose voltage is chosen with
        :py:`-V/--voltage`, with an optional, active-low interrupt pin::

            @glasgow_ports
            class I2CPorts:
                supply: GlasgowSupply = GlasgowSupply.field(voltage_max=3.6)
                scl: io.PortLike = GlasgowPin.field(power=supply, default="A0")
                sda: io.PortLike = GlasgowPin.field(power=supply, default="A1")
                int: io.PortLike | None = GlasgowPin.field(power=supply, invert=True)

        The pins are powered at the voltage of :py:`supply`, which Glasgow applies to whichever
        ports the pins end up on. (If the user gives no voltage, the port's voltage is left
        unchanged.) A device that always runs at one voltage declares
        :py:`supply: GlasgowSupply = GlasgowSupply(voltage=3.3)` instead; it has no command line
        option, and the pins refer to it in the same way.

        Parameters
        ----------
        width : int | range | Iterable[int]
            Number of pins: a single value, a range, or a collection of allowed values.
        default : str | bool | int | None
            Pins used if the option is not given: a pin specification such as :py:`"A0"` or
            :py:`"B0:3"`, :py:`True` to allocate the first free pins, or an :py:`int` to allocate
            that number of free pins. If there is no default and the field is not optional, the
            option is required.
        invert : bool
            Set this for active-low pins, such as a chip select or reset. The inversion is done
            by the port, at the I/O buffer, so the gateware always sees the logical level: it
            drives and reads :py:`1` for asserted, and must not invert the port itself (for
            example with :py:`~`), or the inversion would be undone. This composes with an
            inversion requested by the user in the pin specification (:py:`"A0#"`).
        power : GlasgowSupply | dataclasses.Field | None
            The supply that powers the pins, given as the name of an earlier supply field in the
            same class, as in :py:`power=supply` above. The voltage of the supply is applied to
            the ports of the pins.
        pull : PullState | str | None
            Pull resistor enabled on the pins while the applet is assembled. The state is that of
            the logical level that the gateware sees, so for an inverted pin :py:`"high"`
            enables a pull-down on the physical pin. Not applied if the pins are left unconnected.
        help : str | None
            Help text; if omitted, the docstring following the field is used.
        """
        if default is not None and not isinstance(default, (str, bool, int)):
            raise TypeError(f"default must be a pin specification, True, or a count, "
                            f"not {default!r}")
        return dataclasses.field(metadata={_FIELD_METADATA_KEY:
            _PinField(_width_choices(width), default, bool(invert), power,
                      None if pull is None else PullState(pull), help)})

    @property
    def _legacy_number(self) -> int:
        match self.port:
            case GlasgowPort.A: return  0 + self.number
            case GlasgowPort.B: return  8 + self.number
            case GlasgowPort.C: return 16 + self.number
            case GlasgowPort.D: return 24 + self.number
            case _: raise ValueError(f"pin {self} has no legacy number")

    def __invert__(self) -> Self:
        return type(self)(self.port, self.number, invert=not self.invert)

    def __str__(self):
        return f"{self.port}{self.number}{'#' if self.invert else ''}"


@dataclass(frozen=True)
class GlasgowAnalog:
    """Analog measurement channel.

    An analog measurement channel refers to a pair of nets: either two analog pins in the same
    port, or an analog pin and signal ground.
    """

    class Nodes(enum.Enum):
        SingleEnded_Pos = "P"
        """Measures :math:`V_{AxP} - V_{COM}`."""
        SingleEnded_Neg = "N"
        """Measures :math:`V_{COM} - V_{AxN}`."""
        Differential    = "PN"
        """Measures :math:`V_{AxP} - V_{AxN}`."""

    port:   GlasgowPort
    nodes:  Nodes = Nodes.Differential
    invert: bool = False

    def __init__(self, port: GlasgowPort | str, nodes: Nodes | str, *, invert: bool = False):
        if GlasgowPort(port) == GlasgowPort.ALL:
            raise ValueError("port ALL cannot identify an analog channel")
        object.__setattr__(self, "port", GlasgowPort(port))
        object.__setattr__(self, "nodes", self.Nodes(nodes))
        object.__setattr__(self, "invert", bool(invert))

    @overload
    @classmethod
    def parse(cls, value: str, *, optional: Literal[True]) -> GlasgowAnalog | None:
        pass

    @overload
    @classmethod
    def parse(cls, value: str, *, optional: Literal[False] = False) -> GlasgowAnalog:
        pass

    @classmethod
    def parse(cls, value: str, *, optional: bool = False) -> GlasgowAnalog | None:
        """Parse an analog channel such as :py:`"AP"`, :py:`"AN#"`, :py:`"BPN"`, or :py:`"BNP"`.

        :py:`"P"` and :py:`"N"` select single-ended measurements; :py:`"PN"` and :py:`"NP"`
        select differential measurements with opposite polarity. With :py:`optional=True`,
        an empty string, :py:`"-"`, or :py:`"NC"` returns :py:`None`.
        Invalid channels raise :exc:`ValueError`.
        """
        if optional and value.upper() in ("", "-", "NC"):
            return None
        elif m := re.match(r"^([A-Z])([PN])(#)?$", value):
            port, nodes, invert = GlasgowPort(m.group(1)), cls.Nodes(m.group(2)), bool(m.group(3))
            return cls(port=port, nodes=nodes, invert=invert)
        elif m := re.match(r"^([A-Z])PN?$", value):
            port = GlasgowPort(m.group(1))
            return cls(port=port, nodes=cls.Nodes.Differential, invert=False)
        elif m := re.match(r"^([A-Z])NP?$", value):
            port = GlasgowPort(m.group(1))
            return cls(port=port, nodes=cls.Nodes.Differential, invert=True)
        else:
            if optional:
                raise ValueError(f"{value!r} is not a analog channel "
                        "(try 'AP', 'AN#', 'BPN', 'BNP', or specify 'NC' to leave unconnected)")
            else:
                raise ValueError(f"{value!r} is not a analog channel "
                        "(try 'AP', 'AN#', 'BPN', 'BNP')")

    def __invert__(self) -> Self:
        return type(self)(self.port, self.nodes, invert=not self.invert)

    def __str__(self):
        match self.nodes, self.invert:
            case (self.Nodes.SingleEnded_Pos | self.Nodes.SingleEnded_Neg), _:
                return f"{self.port}{self.nodes}{'#' if self.invert else ''}"
            case self.Nodes.Differential, False:
                return f"{self.port}PN"
            case self.Nodes.Differential, True:
                return f"{self.port}NP"
            case _:
                assert False


@overload
def glasgow_ports[T](cls: type[T], /) -> type[T]:
    pass


@overload
def glasgow_ports[T](*, kw_only: Literal[True] = True,
                     **kwargs: Any) -> Callable[[type[T]], type[T]]:
    pass


@dataclass_transform(kw_only_default=True)
def glasgow_ports(cls=None, /, **kwargs):
    """Declare a dataclass of applet pins and supplies.

    Equivalent to :py:`@dataclass(kw_only=True)`, which ports dataclasses require: optional pins
    have a default, and the constructor is meant to be called with keywords. Any other argument
    is forwarded to :py:`dataclass`, so :py:`@glasgow_ports(frozen=True)` works; the only
    argument that is rejected is :py:`kw_only=False`.

    Its fields are declared with :py:`GlasgowPin.field` and :py:`GlasgowSupply`, and it is
    consumed by :meth:`~glasgow.applet.GlasgowAppletArguments.add_ports_arguments` and
    :meth:`AbstractAssembly.add_ports`.

    Raises
    ------
    TypeError
        If :py:`kw_only=False` is passed.
    """
    if not kwargs.pop("kw_only", True):
        raise TypeError("glasgow_ports requires keyword-only fields; kw_only=False is not allowed")
    def decorate(cls):
        return dataclass(kw_only=True, **kwargs)(cls)
    return decorate if cls is None else decorate(cls)


@dataclass(frozen=True)
class _SupplyInfo:
    field:  dataclasses.Field
    spec:   _SupplyField | None # `None` for a fixed supply, which has no command line option
    fixed:  GlasgowSupply | None


@dataclass(frozen=True)
class _PinInfo:
    field:    dataclasses.Field
    spec:     _PinField
    optional: bool
    supply:   str | None # name of the field of the supply that powers the pins


@dataclass(frozen=True)
class _PortsLayout:
    supplies: dict[str, _SupplyInfo]
    pins:     dict[str, _PinInfo]


def _inspect_ports(cls: type) -> _PortsLayout:
    """Extract and validate the supply and pin declarations of a ports dataclass."""
    if not (isinstance(cls, type) and dataclasses.is_dataclass(cls)):
        raise TypeError(f"{cls!r} is not a dataclass")

    for f in dataclasses.fields(cls):
        if not f.kw_only:
            raise TypeError(f"field {f.name!r} of {cls.__name__} is not keyword-only; declare "
                            f"the class with @glasgow_ports (or @dataclass(kw_only=True))")

    hints = get_type_hints(cls)
    supplies = {}
    pins = {}
    pin_fields = []
    for f in dataclasses.fields(cls):
        match f.metadata.get(_FIELD_METADATA_KEY):
            case _SupplyField() as spec:
                supplies[f.name] = _SupplyInfo(f, spec, None)
            case _PinField() as spec:
                hint = hints[f.name]
                optional = (get_origin(hint) in (Union, types.UnionType) and
                            type(None) in get_args(hint))
                pin_fields.append((f, spec, optional))
            case None if isinstance(f.default, GlasgowSupply):
                supplies[f.name] = _SupplyInfo(f, None, f.default)
            case _:
                raise TypeError(f"field {f.name!r} of {cls.__name__} is not declared with "
                                f"GlasgowSupply or GlasgowPin")

    for f, spec, optional in pin_fields:
        supply = None
        if spec.power is not None:
            for name, info in supplies.items():
                if spec.power is info.field or spec.power is info.fixed:
                    supply = name
            if supply is None:
                raise TypeError(f"pin {f.name!r} of {cls.__name__} is powered by a supply that is "
                                f"not a (previous) field of the same class")
        pins[f.name] = _PinInfo(f, spec, optional, supply)
    return _PortsLayout(supplies, pins)


def _check_supply_range(name: str, spec: _SupplyField | None, supply: GlasgowSupply):
    if spec is None or supply.voltage is None:
        return
    if not spec.voltage_min <= supply.voltage <= spec.voltage_max:
        label = "" if name == "supply" else f" {name!r}"
        raise VoltageConflictError(
            f"supply{label} cannot be set to {supply.voltage:.2f} V: the powered device "
            f"supports {spec.voltage_min:.2f}..{spec.voltage_max:.2f} V")


class AbstractRORegister(metaclass=ABCMeta):
    """Asynchronous host access to a gateware value.

    :py:`await register` is equivalent to :py:`await register.get()`. Values follow the
    registered signal's shape, including structured values for shape-castable signals.
    """

    @property
    @abstractmethod
    def shape(self) -> Shape:
        """The registered signal's Amaranth shape or shape-castable object."""
        pass

    @abstractmethod
    async def get(self) -> Any:
        """Read the current gateware value."""
        pass

    def __await__(self):
        return self.get().__await__()


class AbstractRWRegister(AbstractRORegister):
    """Asynchronous host access to a gateware signal that can also be written."""

    @abstractmethod
    async def set(self, value: Any):
        """Write a value compatible with the registered signal's shape."""
        pass


class ClockDivisor:
    """Frequency control for a zero-based integer clock divisor register.

    A register value of :math:`n` gives a period of :math:`(n + 1) T`, where :math:`T` is
    :py:`ref_period` in seconds. Normally created by :meth:`AbstractAssembly.add_clock_divisor`.

    With :py:`round_mode="floor"`, the divisor is rounded up so that the generated frequency
    does not exceed the request, except for requests above the reference frequency.
    With :py:`round_mode="nearest"`, the divisor is rounded to the nearest integer.
    The reported frequency is rounded to integer hertz (upwards in floor mode).
    :py:`tolerance` is a relative error threshold for logging a warning, not rejecting a request.
    """

    def __init__(self, logger: logging.Logger, register: AbstractRWRegister, *,
                 ref_period: float, tolerance: float, round_mode: Literal["floor", "nearest"],
                 name: str):
        if round_mode not in ("floor", "nearest"):
            raise ValueError(f"round_mode must be 'floor' or 'nearest', not {round_mode!r}")
        self._logger     = logger
        self._register   = register
        self._ref_period = ref_period
        self._tolerance  = tolerance
        self._round_mode = round_mode
        self._name       = name

    def _round(self, value: float) -> int:
        if self._round_mode == "floor":
            return math.ceil(value)
        else:
            return round(value)

    async def get_frequency(self) -> int:
        """Read the divisor and return the resulting frequency in integer hertz."""
        divisor = await self._register.get()
        return self._round(1 / ((divisor + 1) * self._ref_period))

    async def set_frequency(self, requested: int):
        """Set the divisor for a requested frequency in hertz.

        Raise :exc:`ClockingError` if the request is non-positive or requires a divisor too
        large for the register. Requests above the reference frequency select divisor zero.
        Log a warning if the relative error exceeds the configured tolerance.
        """
        if requested <= 0:
            raise ClockingError(
                f"requested frequency {requested / 1e3:.3f} kHz for clock {self._name!r} "
                f"is zero or negative")

        divisor = max(self._round(1 / (self._ref_period * requested) - 1), 0)
        if divisor.bit_length() > self._register.shape.width:
            minimum = 1 / ((1 << self._register.shape.width) * self._ref_period)
            raise ClockingError(
                f"requested frequency {requested / 1e3:.3f} kHz for clock "
                f"{self._name!r} is below minimum achievable {minimum / 1e3:.3f} kHz")

        actual = self._round(1 / ((divisor + 1) * self._ref_period))
        if abs(requested - actual) / requested <= self._tolerance:
            level = logging.DEBUG
        else:
            level = logging.WARNING
        self._logger.log(level, "setting clock %r frequency to %.3f kHz (requested %.3f kHz)",
            self._name, actual / 1e3, requested / 1e3)
        await self._register.set(divisor)


@dataclass(frozen=True, kw_only=True)
class DRAMOptions:
    """Dynamic memory allocation and buffering options.

    :py:`size` is the requested capacity in bytes; :py:`None` selects the backend default.
    :py:`r_buffer_size` and :py:`w_buffer_size` are read and write queue depths in memory-bus
    data beats, not bytes. :py:`None` omits the corresponding queue.
    """

    size: int | None = None

    r_buffer_size: int | None = None
    w_buffer_size: int | None = None


class AbstractInPipe(metaclass=ABCMeta):
    """Byte stream from gateware to the host (USB IN direction).

    Reads consume bytes in order; boundaries between gateware transfers are not preserved.
    """

    @property
    @abstractmethod
    def readable(self) -> int | None:
        """Number of bytes currently buffered for reading, or :py:`None` if unknown."""
        pass

    @abstractmethod
    async def recv(self, length: int) -> memoryview:
        """Wait for and consume exactly :py:`length` bytes.

        Raises
        ------
        ValueError
            If :py:`length` is not positive.
        """
        pass

    @abstractmethod
    async def recv_until(self, delimiter: bytes) -> bytes:
        """Wait for and consume bytes through the first :py:`delimiter`, including it.

        Raises
        ------
        ValueError
            If :py:`delimiter` is empty.
        """
        pass

    @abstractmethod
    async def reset(self):
        """Discard pending transfers and reset the pipe.

        On hardware, this also resets the associated applet clock domain.
        """
        pass

    @abstractmethod
    async def detach(self) -> tuple[int, int | None]:
        """Release the hardware USB interface and return :py:`(in_interface, None)`.

        The pipe cannot be used afterwards. Unsupported by simulation and on Windows.
        """
        pass


class AbstractOutPipe(metaclass=ABCMeta):
    """Byte stream from the host to gateware (USB OUT direction).

    Writes may be buffered. Flush pending commands before waiting for a response that depends
    on them, otherwise a short command may remain in the host buffer indefinitely.
    """

    @property
    @abstractmethod
    def writable(self) -> int | None:
        """Available output transfer capacity in bytes, or :py:`None` if unbounded or unknown."""
        pass

    @abstractmethod
    async def send(self, data: Buffer):
        """Queue bytes for transmission, waiting for buffer space if necessary.

        Completion does not imply that gateware has received or processed the bytes.
        Use :meth:`flush` to submit any data remaining in the host buffer.
        """
        pass

    @abstractmethod
    async def flush(self):
        """Submit buffered bytes and wait for pending transfers to complete.

        This does not acknowledge completion of commands executed by gateware.
        """
        pass

    @abstractmethod
    async def reset(self):
        """Discard pending transfers and reset the pipe.

        On hardware, this also resets the associated applet clock domain.
        """
        pass

    @abstractmethod
    async def detach(self) -> tuple[int | None, int]:
        """Release the hardware USB interface and return :py:`(None, out_interface)`.

        The pipe cannot be used afterwards. Unsupported by simulation and on Windows.
        """
        pass


class AbstractInOutPipe(AbstractInPipe, AbstractOutPipe):
    """Paired input and output byte streams.

    The two directions have independent buffers. :meth:`reset` resets both directions.
    """

    @abstractmethod
    async def detach(self) -> tuple[int, int]:
        """Release both hardware USB interfaces and return :py:`(in_interface, out_interface)`.

        The pipe cannot be used afterwards. Unsupported by simulation and on Windows.
        """
        pass


class AbstractAssembly(metaclass=ABCMeta):
    """Allocate gateware and host resources for applets.

    Resource allocation happens during applet construction, before the assembly is built or
    started. Allocate resources inside :meth:`add_applet` to associate them with that applet.
    Submodules use the applet's clock domain, exposed to their gateware as :py:`sync`.
    Backend-specific assembly classes provide build and execution lifecycle operations.
    """

    DEFAULT_FIFO_DEPTH = 512

    # Logger for the applet currently being assembled (if any). For internal use only.
    _logger: logging.Logger | None = None

    @property
    @abstractmethod
    def sys_clk_period(self) -> float: # TODO: migrate to `amaranth.hdl.Period`
        """Applet system clock period in seconds; may differ between hardware and simulation."""
        pass

    @contextmanager
    @abstractmethod
    def add_applet(self, applet: Any) -> Generator[None]:
        """Associate new resources with :py:`applet` and its logger within this context."""
        pass

    @abstractmethod
    def add_submodule[E: Elaboratable](self, elaboratable: E, *, name: str | None = None) -> E:
        """Add an Amaranth elaboratable to the assembly and return it.

        :py:`name` optionally sets its submodule name.
        """
        pass

    @abstractmethod
    def add_platform_pin(self, pin: GlasgowPin, port_name: str) -> io.PortLike:
        """Allocate a physical pin as an Amaranth I/O port named :py:`port_name`."""
        pass

    def add_port(self, pins: GlasgowPin | tuple[GlasgowPin, ...] | str | io.PortLike | None,
            name: str) -> io.PortLike | None:
        """Allocate an I/O port from a pin, ordered tuple of pins, or CLI pin specification.

        Tuple order determines bit order, starting at bit zero. Pin inversion is applied by
        the hardware backend. :py:`None` or an empty pin selection returns :py:`None`.
        An existing Amaranth port is returned unchanged.

        Raises
        ------
        TypeError
            If :py:`pins` is none of the above.
        """
        match pins:
            case None:
                return None
            case str():
                return self.add_port(GlasgowPin.parse(pins), name)
            case tuple():
                port = None
                for idx, pin in enumerate(pins):
                    pin_port = self.add_port(pin, f"{name}[{idx}]")
                    if port is None:
                        port  = pin_port
                    else:
                        port += pin_port
                return port
            case GlasgowPin() as pin:
                return self.add_platform_pin(pin, name)
            case io.PortLike() as port:
                return port
            case _:
                raise TypeError(f"cannot add a port for object {pins!r}")

    def add_port_group(
            self, **ports: GlasgowPin | tuple[GlasgowPin, ...] | str | io.PortLike | None
    ) -> PortGroup:
        """Allocate named ports using :meth:`add_port`.

        Return a :class:`~glasgow.gateware.ports.PortGroup`.

        Keyword names become attributes of the returned group; optional ports may be :py:`None`.
        This does not configure supply voltages or pulls; applets should declare a ports class
        and use :meth:`add_ports` instead, which does.
        """
        return PortGroup(**{name: self.add_port(pins, name) for name, pins in ports.items()})

    def use_supply(self, supply: GlasgowSupply, pins: Iterable[GlasgowPin], *,
                   limits: tuple[float, float] | None = None):
        """Request the voltage of :py:`supply` for the ports that :py:`pins` belong to.

        This is done automatically by :py:`add_ports` for the pins of a ports dataclass. Call it
        directly for pins that are not known until after the command line is parsed. A supply with
        neither a voltage nor a sense input to follow requests nothing. A port may follow its own
        sense input, which is how the voltage of the target is mirrored; pins that are not on a
        port with a supply (such as LEDs) are ignored.

        If :py:`limits` is given, it is the inclusive range of voltages in volts that the pins may
        safely be driven at; see :py:`set_port_voltage`.

        Raises
        ------
        VoltageConflictError
            If the voltage conflicts with one already requested for the same port.
        """
        ports = sorted({pin.port for pin in pins if pin.port.has_supply},
                       key=lambda port: port.value)
        for port in ports:
            if supply.voltage is not None:
                self.set_port_voltage(port, GlasgowVio(supply.voltage))
            elif supply.sense is not None:
                self.set_port_voltage(port, GlasgowVio(sense=supply.sense), limits=limits)

    def add_ports[T](self, cls: type[T], args: argparse.Namespace | Mapping[str, Any]) -> T:
        """Create the ports and apply the supply voltages declared by a ports dataclass.

        :py:`cls` is a dataclass whose fields are declared with :py:`GlasgowPin.field` and
        :py:`GlasgowSupply` (see
        :meth:`~glasgow.applet.GlasgowAppletArguments.add_ports_arguments`). :py:`args` provides a
        value for each field, either as parsed command line arguments or as a mapping:
        pins as :py:`GlasgowPin` objects, a string, a tuple of pins, or :py:`None` for an optional
        field; supplies as :py:`GlasgowSupply` objects or a string.

        Each pin is added with :py:`add_port`, and the voltage of the supply that powers it is
        requested for the port the pin belongs to.

        Returns an instance of :py:`cls` where every pin field is an :py:`io.PortLike` (or
        :py:`None`) and every supply field is the resolved :py:`GlasgowSupply`.

        Raises
        ------
        ValueError
            If a pin specification has a width that the field does not allow.
        VoltageConflictError
            If a supply voltage is outside of the range allowed by its declaration, or if it
            conflicts with a voltage already requested for the same port.
        """
        layout = _inspect_ports(cls)
        values = vars(args) if isinstance(args, argparse.Namespace) else args

        supplies = {}
        for name, info in layout.supplies.items():
            if info.fixed is not None:
                supply = info.fixed
            else:
                supply = values.get(name)
                assert info.spec is not None # only a fixed supply has no `_SupplyField`
                if supply is None:
                    supply = GlasgowSupply(current_max=info.spec.current_max)
                elif isinstance(supply, str):
                    supply = GlasgowSupply.parse(supply)
                _check_supply_range(name, info.spec, supply)
            supplies[name] = supply

        ports = {}
        supply_pins = {name: [] for name in supplies}
        for name, info in layout.pins.items():
            pins = values.get(name)
            if isinstance(pins, str):
                pins = GlasgowPin.parse(pins)
            elif isinstance(pins, GlasgowPin):
                pins = (pins,)
            if isinstance(pins, tuple):
                if len(pins) == 0:
                    pins = None
                else:
                    if len(pins) not in info.spec.width:
                        raise ValueError(f"pin {name!r} expects "
                            f"{' or '.join(map(str, info.spec.width))} pins, got {len(pins)}")
                    if info.spec.invert:
                        pins = tuple(~pin for pin in pins)
                    if info.supply is not None:
                        supply_pins[info.supply].extend(pins)
                    if info.spec.pull is not None:
                        for pin in pins:
                            self.set_pin_pull(pin, info.spec.pull)
            if pins is None and not info.optional:
                raise ValueError(f"pin {name!r} is required")
            ports[name] = self.add_port(pins, name)

        for name, supply in supplies.items():
            spec = layout.supplies[name].spec
            limits = (spec.voltage_min, spec.voltage_max) if spec else None
            self.use_supply(supply, supply_pins[name], limits=limits)

        return cls(**ports, **supplies)

    @abstractmethod
    def add_ro_register(self, signal: Signal) -> AbstractRORegister:
        """Expose a gateware-driven signal for asynchronous host reads."""
        pass

    @abstractmethod
    def add_rw_register(self, signal: Signal) -> AbstractRWRegister:
        """Expose a host-driven signal for asynchronous host reads and writes."""
        pass

    def add_clock_divisor(self, signal: Signal, ref_period: float, *,
            tolerance: float | None = None,
            round_mode: Literal["floor", "nearest"] = "floor", name: str) -> ClockDivisor:
        """Expose a plain-shaped divisor signal as a :class:`ClockDivisor`.

        :py:`ref_period` is in seconds. :py:`tolerance` defaults to 1% relative frequency
        error and controls warning logging only. See :class:`ClockDivisor` for rounding rules.
        :py:`name` identifies the clock in diagnostics.
        """
        if not isinstance(signal.shape(), Shape):
            raise TypeError(f"signal must have a plain shape, not {signal.shape()!r}")
        if tolerance is None:
            tolerance = 1e-2 # assume the clock doesn't need to be very accurate and 1% is enough
        if self._logger is None:
            raise RuntimeError("the assembly has no logger")
        return ClockDivisor(self._logger, self.add_rw_register(signal),
                            ref_period=ref_period, tolerance=tolerance, round_mode=round_mode,
                            name=name)

    @abstractmethod
    def add_in_pipe(self, in_stream: stream.Interface, *, in_flush: Value = C(0),
            fifo_depth: int | None = None, buffer_size: int | None = None) -> AbstractInPipe:
        """Connect an 8-bit gateware producer stream to a host input pipe.

        :py:`in_stream` uses the Amaranth stream handshake in the applet clock domain.
        Assert :py:`in_flush` to forward a partial input packet promptly.
        :py:`fifo_depth` is the gateware FIFO depth in bytes: :py:`None` selects
        :attr:`DEFAULT_FIFO_DEPTH`, and zero omits the FIFO. :py:`buffer_size` is the host
        buffering threshold in bytes, or :py:`None` for unbounded buffering.
        Simulation does not model these buffering limits.
        """
        pass

    @abstractmethod
    def add_out_pipe(self, out_stream: stream.Interface, *,
            fifo_depth: int | None = None, buffer_size: int | None = None) -> AbstractOutPipe:
        """Connect a host output pipe to an 8-bit gateware consumer stream.

        :py:`out_stream` uses the Amaranth stream handshake in the applet clock domain.
        :py:`fifo_depth` and :py:`buffer_size` have the same units and defaults as in
        :meth:`add_in_pipe`, applied to the output direction.
        """
        pass

    @abstractmethod
    def add_inout_pipe(self, in_stream: stream.Interface, out_stream: stream.Interface, *,
            in_flush: Value = C(0),
            in_fifo_depth: int | None = None, in_buffer_size: int | None = None,
            out_fifo_depth: int | None = None, out_buffer_size: int | None = None
    ) -> AbstractInOutPipe:
        """Connect paired gateware producer and consumer streams to a bidirectional pipe.

        See :meth:`add_in_pipe` and :meth:`add_out_pipe` for stream direction and buffering.
        The :py:`in_` and :py:`out_` options configure each direction independently;
        :py:`in_flush` only flushes the gateware-to-host direction.
        """
        pass

    @abstractmethod
    def add_dynamic_memory(
            self, options: DRAMOptions = DRAMOptions()) -> tuple[octoram.Signature, range]:
        """Allocate dynamic memory and return its bus interface and byte address range.

        :py:`options` controls capacity and buffering. Availability and allocation limits
        depend on the backend and hardware revision; on hardware, revision C support is
        experimental and must be enabled by setting the environment variable
        :py:`GLASGOW_REVC_DRAM=yes`.
        """
        pass

    @abstractmethod
    def add_indicator(self, signal: Signal, *, name: str) -> None:
        """Drive a user indicator LED from :py:`signal`, identified by :py:`name` in diagnostics."""
        pass

    @abstractmethod
    def set_port_voltage(self, port: GlasgowPort, vio: GlasgowVio, *,
                         limits: tuple[float, float] | None = None) -> None:
        """Request the voltage of :py:`port`.

        :py:`port` may be :attr:`GlasgowPort.ALL`, with either a fixed voltage or a sense input to
        follow; in the latter case every supply-capable port mirrors the sensed voltage.

        If :py:`limits` is given, it is the inclusive range of voltages in volts that the pins on
        the port may safely be driven at. A voltage that is only known once the device is
        running, such as one that follows the sense input of a port, is checked against it then.
        """

    @abstractmethod
    def set_pin_pull(self, pin: GlasgowPin, state: PullState) -> None:
        """Record a logical pin pull state to apply with :meth:`configure_ports`.

        Pin inversion exchanges physical pull-up and pull-down. Hardware support depends
        on the device revision.
        """
        pass

    def use_voltage(self, ports: Mapping[GlasgowPort | str, GlasgowVio | float]) -> None:
        """Record a mapping of port identifiers to volts or :class:`GlasgowVio` requests.

        For example: :py:`assembly.use_voltage({"A": 3.3, "B": GlasgowVio(sense="A")})`.
        Applets that declare a ports class do not need this; :meth:`add_ports` requests the
        voltage of each supply, and diagnoses conflicts.

        Raises
        ------
        ValueError
            If a port identifier is not valid.
        TypeError
            If a voltage is neither a :class:`GlasgowVio` nor a number of volts.
        """
        for port, vio_desc in ports.items():
            port = GlasgowPort(port)
            match vio_desc:
                case GlasgowVio() as vio:
                    pass
                case bool():
                    raise TypeError(f"cannot use {vio_desc!r} as the voltage of port {port}")
                case int() | float():
                    vio = GlasgowVio(vio_desc)
                case _:
                    raise TypeError(f"cannot use {vio_desc!r} as the voltage of port {port}; "
                                    f"expected a GlasgowVio or a number of volts")
            self.set_port_voltage(port, vio)

    def use_pulls(self,
                  pulls: Mapping[tuple[GlasgowPin, ...] | GlasgowPin | str, PullState | str]
    ) -> None:
        """Record pulls from a mapping of pin selections to :class:`PullState` or its string value.

        Keys may be individual pins, tuples of pins, or CLI pin specifications.
        For example: :py:`assembly.use_pulls({"A0:3": "high", "B0": "float"})`.

        Raises
        ------
        ValueError
            If a pin specification or a pull state string is not valid.
        TypeError
            If a key is not a pin selection, or a state is not a :class:`PullState` or a string.
        """
        for pins, state in pulls.items():
            match pins:
                case tuple():
                    if not all(isinstance(pin, GlasgowPin) for pin in pins):
                        raise TypeError(f"cannot use {pins!r} as a selection of pins")
                case GlasgowPin():
                    pins = (pins,)
                case str():
                    pins = GlasgowPin.parse(pins)
                case _:
                    raise TypeError(f"cannot use {pins!r} as a selection of pins; expected a "
                                    f"GlasgowPin, a tuple of pins, or a pin specification")
            match state:
                case PullState():
                    pass
                case str():
                    state = PullState(state)
                case _:
                    raise TypeError(f"cannot use {state!r} as a pull state; expected a "
                                    f"PullState or one of 'float', 'high', 'low'")
            for pin in pins:
                self.set_pin_pull(pin, state)

    @abstractmethod
    async def configure_ports(self) -> None:
        """Apply recorded voltage and pull requests to the device.

        Simulation does not configure physical electrical properties.
        """
        pass
