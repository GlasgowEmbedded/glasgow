from abc import ABCMeta, abstractmethod
from typing import Any, Optional, Generator
from collections.abc import Mapping
from dataclasses import dataclass
import re
import enum
import logging

from amaranth import *
from amaranth.lib import stream, io

from .gateware.ports import PortGroup


__all__ = [
    "PullState", "GlasgowPort", "GlasgowVio", "GlasgowPin",
    "AbstractRORegister", "AbstractRWRegister",
    "AbstractInPipe", "AbstractOutPipe", "AbstractInOutPipe",
    "AbstractAssembly"
]


class PullState(enum.Enum):
    Float = "float"
    High  = "high"
    Low   = "low"

    def enabled(self):
        return self != self.Float

    def __invert__(self):
        match self:
            case self.Float: return self
            case self.High:  return self.Low
            case self.Low:   return self.High

    def __repr__(self):
        return f"{self.__class__.__name__}.{self.name}"

    def __str__(self):
        return self.value


class GlasgowPort(enum.Enum):
    A = "A"
    B = "B"

    def __repr__(self):
        return f"{self.__class__.__name__}.{self.name}"

    def __str__(self):
        return self.value


@dataclass(frozen=True)
class GlasgowVio:
    value: Optional[float]       = None
    sense: Optional[GlasgowPort] = None

    def __init__(self, value:Optional[float]=None, *, sense:Optional[GlasgowPort]=None):
        if value is None and sense is None or value is not None and sense is not None:
            raise ValueError("exactly one of voltage value or a port to be sensed may be present")
        object.__setattr__(self, "value", float(value) if value is not None else None)
        object.__setattr__(self, "sense", GlasgowPort(sense) if sense is not None else None)

    @classmethod
    def parse(cls, value, *, all_ports="AB") -> dict[GlasgowPort, 'GlasgowVio']:
        result = {}
        for clause in value.split(","):
            if m := re.match(r"^([0-9]+(\.[0-9]+)?)$", clause):
                volts = float(m.group(1))
                for port in all_ports:
                    result[GlasgowPort(port)] = GlasgowVio(value=volts)
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


@dataclass(frozen=True)
class GlasgowPin:
    port:   GlasgowPort
    number: int
    invert: bool = False

    def __init__(self, port: GlasgowPort, number: int, *, invert=False):
        object.__setattr__(self, "port", GlasgowPort(port))
        object.__setattr__(self, "number", int(number))
        object.__setattr__(self, "invert", bool(invert))

    @classmethod
    def parse(cls, value) -> tuple['GlasgowPin']:
        result = []
        for clause in value.split(","):
            if clause == "-":
                pass
            elif m := re.match(r"^([A-Z])([0-9]+)(#)?$", clause):
                port, number, invert = GlasgowPort(m.group(1)), int(m.group(2)), bool(m.group(3))
                result.append(cls(port=port, number=number, invert=invert))
            elif m := re.match(r"^([A-Z])([0-9]+):([0-9]+)(#)?$", clause):
                port, pin_first, pin_last, invert = \
                    GlasgowPort(m.group(1)), int(m.group(2)), int(m.group(3)), bool(m.group(4))
                if pin_last >= pin_first:
                    for number in range(pin_first, pin_last + 1, +1):
                        result.append(cls(port=port, number=number, invert=invert))
                else:
                    for number in range(pin_first, pin_last - 1, -1):
                        result.append(cls(port=port, number=number, invert=invert))
            else:
                raise ValueError(f"{clause!r} is not a valid pin")
        return tuple(result)

    @property
    def _legacy_number(self):
        match self.port:
            case GlasgowPort.A: return 0 + self.number
            case GlasgowPort.B: return 8 + self.number
            case _: assert False

    def __str__(self):
        return f"{self.port}{self.number}{'#' if self.invert else ''}"


class AbstractRORegister(metaclass=ABCMeta):
    @abstractmethod
    async def get(self) -> Any:
        pass

    def __await__(self):
        return self.get().__await__()


class AbstractRWRegister(AbstractRORegister):
    @abstractmethod
    async def set(self, value: Any):
        pass


class AbstractInPipe(metaclass=ABCMeta):
    @property
    @abstractmethod
    def readable(self) -> Optional[int]:
        pass

    @abstractmethod
    async def recv(self, length) -> memoryview:
        pass

    @abstractmethod
    async def reset(self):
        pass


class AbstractOutPipe(metaclass=ABCMeta):
    @property
    @abstractmethod
    def writable(self) -> Optional[int]:
        pass

    @abstractmethod
    async def send(self, data: bytes | bytearray | memoryview):
        pass

    @abstractmethod
    async def flush(self):
        pass

    @abstractmethod
    async def reset(self):
        pass


class AbstractInOutPipe(AbstractInPipe, AbstractOutPipe):
    pass


class AbstractAssembly(metaclass=ABCMeta):
    DEFAULT_FIFO_DEPTH = 512

    @property
    @abstractmethod
    def sys_clk_period(self) -> float: # TODO: migrate to `amaranth.hdl.Period`
        pass

    @abstractmethod
    def add_applet(self, applet: Any) -> Generator[None, None, None]:
        pass

    @abstractmethod
    def add_submodule(self, elaboratable, *, name=None) -> Elaboratable:
        pass

    @abstractmethod
    def add_platform_pin(self, pin: GlasgowPin, port_name: str) -> io.PortLike:
        pass

    def add_port(self, pins: GlasgowPin | tuple[GlasgowPin] | str | None, name: str) -> io.PortLike:
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
            case _:
                raise TypeError(f"cannot add a port for object {pins!r}")

    def add_port_group(self, **ports) -> PortGroup:
        return PortGroup(**{name: self.add_port(pins, name) for name, pins in ports.items()})

    @abstractmethod
    def add_ro_register(self, signal) -> AbstractRORegister:
        pass

    @abstractmethod
    def add_rw_register(self, signal) -> AbstractRWRegister:
        pass

    @abstractmethod
    def add_in_pipe(self, in_stream, *, in_flush=C(1),
                    fifo_depth=None, buffer_size=None) -> AbstractInPipe:
        pass

    @abstractmethod
    def add_out_pipe(self, out_stream, *,
                     fifo_depth=None, buffer_size=None) -> AbstractOutPipe:
        pass

    @abstractmethod
    def add_inout_pipe(self, in_stream, out_stream, *, in_flush=C(1),
                       in_fifo_depth=None, in_buffer_size=None,
                       out_fifo_depth=None, out_buffer_size=None) -> AbstractInOutPipe:
        pass

    @abstractmethod
    def use_voltage(self, ports: Mapping[GlasgowPort, GlasgowVio | float]):
        pass

    @abstractmethod
    def use_pulls(self, pulls: Mapping[GlasgowPin | tuple[GlasgowPin] | str, PullState | str]):
        pass

    @abstractmethod
    async def configure_ports(self):
        pass
