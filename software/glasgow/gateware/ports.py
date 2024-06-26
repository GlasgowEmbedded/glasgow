from amaranth import *
from amaranth import tracer
from amaranth.lib import io


__all__ = ["PortGroup"]


class PortGroup:
    """Group of Amaranth library I/O ports.

    This object is a stand-in for the object returned by the Amaranth :py:`platform.request()`
    function, as expected by the I/O cores.
    """
    def __init__(self, **kwargs):
        for name, port in kwargs.items():
            setattr(self, name, port)

    def __setattr__(self, name, value):
        if not name.startswith("_"):
            assert value is None or isinstance(value, io.PortLike)
        object.__setattr__(self, name, value)


# FIXME: needs to be upstream in Amaranth amaranth-lang/amaranth#1417
class SimulationPort(io.PortLike):
    def __init__(self, width, *, invert=False, direction, name=None, src_loc_at=0):
        if name is not None and not isinstance(name, str):
            raise TypeError(f"Name must be a string, not {name!r}")
        if name is None:
            name = tracer.get_var_name(depth=2 + src_loc_at, default="$port")

        if not (isinstance(width, int) and width >= 1):
            raise TypeError(f"Width must be a positive integer, not {width!r}")

        self._i = self._o = self._oe = None
        if direction is not io.Direction.Output:
            self._i = Signal(width, name=f"{name}__i")
        if direction is not io.Direction.Input:
            self._o = Signal(width, name=f"{name}__o")
            self._oe = Signal(width, name=f"{name}__oe",
                              init=~0 if direction is io.Direction.Output else 0)

        if isinstance(invert, bool):
            self._invert = (invert,) * width
        elif isinstance(invert, Iterable):
            self._invert = tuple(invert)
            if len(self._invert) != width:
                raise ValueError(f"Length of 'invert' ({len(self._invert)}) doesn't match "
                                 f"port width ({width})")
            if not all(isinstance(item, bool) for item in self._invert):
                raise TypeError(f"'invert' must be a bool or iterable of bool, not {invert!r}")
        else:
            raise TypeError(f"'invert' must be a bool or iterable of bool, not {invert!r}")

        self._direction = io.Direction(direction)

    @property
    def i(self):
        if self._i is None:
            raise AttributeError(
                "Simulation port with output direction does not have an input signal")
        return self._i

    @property
    def o(self):
        if self._o is None:
            raise AttributeError(
                "Simulation port with input direction does not have an output signal")
        return self._o

    @property
    def oe(self):
        if self._oe is None:
            raise AttributeError(
                "Simulation port with input direction does not have an output enable signal")
        return self._oe

    @property
    def invert(self):
        return self._invert

    @property
    def direction(self):
        return self._direction

    def __len__(self):
        if self._direction is io.Direction.Input:
            return len(self._i)
        if self._direction is io.Direction.Output:
            assert len(self._o) == len(self._oe)
            return len(self._o)
        if self._direction is io.Direction.Bidir:
            assert len(self._i) == len(self._o) == len(self._oe)
            return len(self._i)
        assert False # :nocov:

    def __getitem__(self, key):
        result = object.__new__(type(self))
        result._i  = None if self._i  is None else self._i [key]
        result._o  = None if self._o  is None else self._o [key]
        result._oe = None if self._oe is None else self._oe[key]
        result._invert = self._invert
        result._direction = self._direction
        return result

    def __invert__(self):
        result = object.__new__(type(self))
        result._i = self._i
        result._o = self._o
        result._oe = self._oe
        result._invert = tuple(not invert for invert in self._invert)
        result._direction = self._direction
        return result

    def __add__(self, other):
        if not isinstance(other, SimulationPort):
            return NotImplemented
        direction = self._direction & other._direction
        result = object.__new__(type(self))
        result._i  = None if direction is io.Direction.Output else Cat(self._i,  other._i)
        result._o  = None if direction is io.Direction.Input  else Cat(self._o,  other._o)
        result._oe = None if direction is io.Direction.Input  else Cat(self._oe, other._oe)
        result._invert = self._invert + other._invert
        result._direction = direction
        return result


# FIXME: won't be needed once SimulationPort is in upstream Amaranth amaranth-lang/amaranth#1417
class SimulationPlatform:
    def get_io_buffer(self, buffer):
        if isinstance(buffer.port, SimulationPort):
            m = Module()
            invert = Cat(buffer.port.invert)
            if isinstance(buffer, io.Buffer):
                m.d.comb += [
                    buffer.i.eq(Cat(Mux(buffer.port.oe, o, i)
                                    for o, i in zip(buffer.port.o, buffer.port.i)) ^ invert),
                    buffer.port.o.eq(buffer.o ^ invert),
                    buffer.port.oe.eq(buffer.oe.replicate(len(buffer.port))),
                ]
            elif isinstance(buffer, io.FFBuffer):
                m.d[buffer.i_domain] += [
                    buffer.i.eq(Cat(Mux(buffer.port.oe, o, i)
                                    for o, i in zip(buffer.port.o, buffer.port.i)) ^ invert),
                ]
                m.d[buffer.o_domain] += [
                    buffer.port.o.eq(buffer.o ^ invert),
                    buffer.port.oe.eq(buffer.oe.replicate(len(buffer.port))),
                ]
            else:
                raise NotImplementedError
            return m
        else:
            raise NotImplementedError
