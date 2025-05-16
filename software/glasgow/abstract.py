from abc import ABCMeta, abstractmethod
from typing import Any, Optional, Generator
from dataclasses import dataclass
import re
import logging

from amaranth import *
from amaranth.lib import stream, io

from .gateware.ports import PortGroup


__all__ = [
    "GlasgowPin",
    "AbstractRORegister", "AbstractRWRegister",
    "AbstractInPipe", "AbstractOutPipe", "AbstractInOutPipe",
    "AbstractAssembly"
]


@dataclass(frozen=True)
class GlasgowPin:
    port:   str
    number: int
    invert: bool = False

    @classmethod
    def parse(cls, value) -> list['GlasgowPin']:
        result = []
        for clause in value.split(","):
            if clause == "-":
                pass
            elif m := re.match(r"^([A-Z])([0-9]+)(#)?$", clause):
                port, number, invert = m.group(1), int(m.group(2)), bool(m.group(3))
                result.append(cls(port=port, number=number, invert=invert))
            elif m := re.match(r"^([A-Z])([0-9]+):([0-9]+)(#)?$", clause):
                port, pin_first, pin_last, invert = \
                    m.group(1), int(m.group(2)), int(m.group(3)), bool(m.group(4))
                if pin_last >= pin_first:
                    for number in range(pin_first, pin_last + 1, +1):
                        result.append(cls(port=port, number=number, invert=invert))
                else:
                    for number in range(pin_first, pin_last - 1, -1):
                        result.append(cls(port=port, number=number, invert=invert))
            else:
                raise ValueError(f"{clause!r} is not a valid pin")
        return result

    @property
    def _legacy_number(self):
        match self.port:
            case "A": return 0 + self.number
            case "B": return 8 + self.number
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


class AbstractInOutPipe(AbstractInPipe, AbstractOutPipe):
    pass


class AbstractAssembly(metaclass=ABCMeta):
    DEFAULT_FIFO_DEPTH = 512

    @property
    @abstractmethod
    def sys_clk_period(self) -> float: # TODO: migrate to `amaranth.hdl.Period`
        pass

    @abstractmethod
    def add_applet(self, applet: Any, *, logger: logging.Logger) -> Generator[None, None, None]:
        pass

    @abstractmethod
    def add_submodule(self, elaboratable, *, name=None) -> Elaboratable:
        pass

    @abstractmethod
    def add_platform_pin(self, pin_name: str, port_name: str) -> io.PortLike:
        pass

    def add_port(self, pins: GlasgowPin | list[GlasgowPin] | str | None, name: str) -> io.PortLike:
        match pins:
            case None:
                return None
            case str():
                return self.add_port(GlasgowPin.parse(pins), name)
            case list():
                port = None
                for idx, pin in enumerate(pins):
                    pin_port = self.add_port(pin, f"{name}[{idx}]")
                    if port is None:
                        port  = pin_port
                    else:
                        port += pin_port
                return port
            case GlasgowPin(port, number, invert):
                port = self.add_platform_pin(f"{port}{number}", name)
                return ~port if invert else port
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
