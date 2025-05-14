from abc import ABCMeta, abstractmethod
from typing import Any, Optional, Generator
import logging

from amaranth import *
from amaranth.lib import stream, io

from .gateware.ports import PortGroup


__all__ = [
    "AbstractRORegister", "AbstractRWRegister",
    "AbstractInPipe", "AbstractOutPipe", "AbstractInOutPipe",
    "AbstractAssembly"
]


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
    def add_port(self, pin_name) -> io.PortLike:
        pass

    def add_port_group(self, **ports) -> PortGroup:
        return PortGroup(**{
            name: self.add_port(pin_or_pins, name=name) for name, pin_or_pins in ports.items()
        })

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
