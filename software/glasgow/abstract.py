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
from amaranth.lib import io

from glasgow.support import logging
from glasgow.gateware.ports import PortGroup
from glasgow.gateware import octoram


__all__ = [
    "ClockingError", "VoltageConflictError",
    "PullState", "GlasgowPort", "GlasgowVio", "GlasgowSupply", "GlasgowPin", "GlasgowAnalog",
    "glasgow_ports",
    "AbstractRORegister", "AbstractRWRegister", "ClockDivisor", "DRAMOptions",
    "AbstractInPipe", "AbstractOutPipe", "AbstractInOutPipe",
    "AbstractAssembly"
]


class ClockingError(Exception):
    pass


class PullState(enum.Enum):
    Float = "float"
    High  = "high"
    Low   = "low"

    def enabled(self) -> bool:
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
    def parse(cls, value) -> dict[GlasgowPort, GlasgowVio]:
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

    def __str__(self):
        if self.sense is not None:
            return f"S{self.sense}"
        if self.value is not None:
            return f"{self.value:.2f}"
        assert False


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
    port:   GlasgowPort
    number: int
    invert: bool = False

    def __init__(self, port: GlasgowPort, number: int, *, invert=False):
        assert GlasgowPort(port) != GlasgowPort.ALL
        object.__setattr__(self, "port", GlasgowPort(port))
        object.__setattr__(self, "number", int(number))
        object.__setattr__(self, "invert", bool(invert))

    @classmethod
    def parse(cls, value: str) -> tuple[GlasgowPin]:
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
    def _legacy_number(self):
        match self.port:
            case GlasgowPort.A: return  0 + self.number
            case GlasgowPort.B: return  8 + self.number
            case GlasgowPort.C: return 16 + self.number
            case GlasgowPort.D: return 24 + self.number
            case _: assert False

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

    def __init__(self, port: GlasgowPort, nodes: Nodes, *, invert=False):
        assert GlasgowPort(port) != GlasgowPort.ALL
        object.__setattr__(self, "port", GlasgowPort(port))
        object.__setattr__(self, "nodes", self.Nodes(nodes))
        object.__setattr__(self, "invert", bool(invert))

    @overload
    @classmethod
    def parse(cls, value: str, *, optional: Literal[True]) -> GlasgowAnalog | None:
        pass

    @classmethod
    def parse(cls, value: str, *, optional: Literal[False] = False) -> GlasgowAnalog:
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
    consumed by :py:`GlasgowAppletArguments.add_ports_arguments` and
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
    @property
    @abstractmethod
    def shape(self) -> Shape:
        pass

    @abstractmethod
    async def get(self) -> Any:
        pass

    def __await__(self):
        return self.get().__await__()


class AbstractRWRegister(AbstractRORegister):
    @abstractmethod
    async def set(self, value: Any):
        pass


class ClockDivisor:
    # This wrapper assumes the divisor register has no "dead codes", i.e. 0 corresponds to
    # the output period being the same as the reference period, 1 to reference period divided
    # by 2, 2 to reference period divided by 3, and so on.

    def __init__(self, logger: logging.Logger, register: AbstractRWRegister, *,
                 ref_period: float, tolerance: float, round_mode: Literal["floor", "nearest"],
                 name: str):
        self._logger     = logger
        self._register   = register
        self._ref_period = ref_period
        self._tolerance  = tolerance
        self._round_mode = round_mode
        self._name       = name

    def _round(self, value: float):
        match self._round_mode:
            case "floor":   return math.ceil(value)
            case "nearest": return round(value)
            case _:         assert False

    async def get_frequency(self) -> int:
        divisor = await self._register.get()
        return self._round(1 / ((divisor + 1) * self._ref_period))

    async def set_frequency(self, requested: int):
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
    size: int | None = None

    r_buffer_size: int | None = None
    w_buffer_size: int | None = None


class AbstractInPipe(metaclass=ABCMeta):
    @property
    @abstractmethod
    def readable(self) -> int | None:
        pass

    @abstractmethod
    async def recv(self, length) -> memoryview:
        pass

    @abstractmethod
    async def recv_until(self, delimiter: bytes) -> bytes:
        pass

    @abstractmethod
    async def reset(self):
        pass

    @abstractmethod
    async def detach(self) -> tuple[int, None]:
        pass


class AbstractOutPipe(metaclass=ABCMeta):
    @property
    @abstractmethod
    def writable(self) -> int | None:
        pass

    @abstractmethod
    async def send(self, data: Buffer):
        pass

    @abstractmethod
    async def flush(self):
        pass

    @abstractmethod
    async def reset(self):
        pass

    @abstractmethod
    async def detach(self) -> tuple[None, int]:
        pass


class AbstractInOutPipe(AbstractInPipe, AbstractOutPipe):
    @abstractmethod
    async def detach(self) -> tuple[int, int]:
        pass


class AbstractAssembly(metaclass=ABCMeta):
    DEFAULT_FIFO_DEPTH = 512

    # Logger for the applet currently being assembled (if any). For internal use only.
    _logger: logging.Logger | None = None

    @property
    @abstractmethod
    def sys_clk_period(self) -> float: # TODO: migrate to `amaranth.hdl.Period`
        pass

    @contextmanager
    @abstractmethod
    def add_applet(self, applet: Any) -> Generator[None]:
        pass

    @abstractmethod
    def add_submodule[E: Elaboratable](self, elaboratable: E, *, name: str | None = None) -> E:
        pass

    @abstractmethod
    def add_platform_pin(self, pin: GlasgowPin, port_name: str) -> io.PortLike:
        pass

    def add_port(self, pins: GlasgowPin | tuple[GlasgowPin] | str | None,
            name: str) -> io.PortLike | None:
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
            case (io.SimulationPort() | io.SingleEndedPort()) as port:
                return port
            case _:
                raise TypeError(f"cannot add a port for object {pins!r}")

    def add_port_group(self, **ports) -> PortGroup:
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
        :py:`GlasgowSupply` (see :py:`GlasgowAppletArguments.add_ports_arguments`). :py:`args`
        provides a value for each field, either as parsed command line arguments or as a mapping:
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
    def add_ro_register(self, signal) -> AbstractRORegister:
        pass

    @abstractmethod
    def add_rw_register(self, signal) -> AbstractRWRegister:
        pass

    def add_clock_divisor(self, signal, ref_period: float, *, tolerance: float | None = None,
            round_mode: Literal["floor", "nearest"] = "floor", name: str) -> ClockDivisor:
        if not isinstance(signal.shape(), Shape):
            raise TypeError(f"signal must have a plain shape, not {signal.shape()!r}")
        if tolerance is None:
            tolerance = 1e-2 # assume the clock doesn't need to be very accurate and 1% is enough
        assert self._logger is not None
        return ClockDivisor(self._logger, self.add_rw_register(signal),
                            ref_period=ref_period, tolerance=tolerance, round_mode=round_mode,
                            name=name)

    @abstractmethod
    def add_in_pipe(self, in_stream, *, in_flush=C(0),
            fifo_depth=None, buffer_size=None) -> AbstractInPipe:
        pass

    @abstractmethod
    def add_out_pipe(self, out_stream, *,
            fifo_depth=None, buffer_size=None) -> AbstractOutPipe:
        pass

    @abstractmethod
    def add_inout_pipe(self, in_stream, out_stream, *, in_flush=C(0),
            in_fifo_depth=None, in_buffer_size=None,
            out_fifo_depth=None, out_buffer_size=None) -> AbstractInOutPipe:
        pass

    @abstractmethod
    def add_dynamic_memory(self, options=DRAMOptions()) -> tuple[octoram.Signature, range]:
        pass

    @abstractmethod
    def add_indicator(self, signal: Signal, *, name: str):
        pass

    @abstractmethod
    def set_port_voltage(self, port: GlasgowPort, vio: GlasgowVio, *,
                         limits: tuple[float, float] | None = None):
        """Request the voltage of :py:`port`.

        If :py:`limits` is given, it is the inclusive range of voltages in volts that the pins on
        the port may safely be driven at. A voltage that is only known once the device is
        running, such as one that follows the sense input of a port, is checked against it then.
        """

    @abstractmethod
    def set_pin_pull(self, pin: GlasgowPin, state: PullState):
        pass

    def use_voltage(self, ports: Mapping[GlasgowPort | str, GlasgowVio | float]):
        for port, vio_desc in ports.items():
            port = GlasgowPort(port)
            match vio_desc:
                case GlasgowVio() as vio:
                    pass
                case float():
                    vio = GlasgowVio(vio_desc)
                case _:
                    assert False
            self.set_port_voltage(port, vio)

    def use_pulls(self, pulls: Mapping[tuple[GlasgowPin] | GlasgowPin | str, PullState | str]):
        for pins, state in pulls.items():
            match pins:
                case tuple():
                    pass
                case GlasgowPin():
                    pins = [pins]
                case str():
                    pins = GlasgowPin.parse(pins)
                case _:
                    assert False
            match state:
                case PullState():
                    pass
                case str():
                    state = PullState(state)
                case _:
                    assert False
            for pin in pins:
                self.set_pin_pull(pin, state)

    @abstractmethod
    async def configure_ports(self):
        pass
