from typing import Literal
from amaranth import *
from amaranth.lib import enum, data, wiring, stream
from amaranth.lib.wiring import In, Out, connect, flipped

from .ports import PortGroup
from .iostream import IOStreamer


__all__ = ["Mode", "Operation", "Enframer", "Deframer", "Controller"]


class Mode(enum.IntEnum, shape=2):
    IdleLow_SampleRising   = 0 # CPOL=0, CPHA=0
    IdleLow_SampleFalling  = 1 # CPOL=0, CPHA=1
    IdleHigh_SampleFalling = 2 # CPOL=1, CPHA=0
    IdleHigh_SampleRising  = 3 # CPOL=1, CPHA=1

    @classmethod
    def from_cpol_cpha(cls, cpol: Literal[0, 1], cpha: Literal[0, 1]):
        return cls(cpol << 1 | cpha)

    @property
    def is_idle_low(self) -> bool:
        return (self == self.IdleLow_SampleRising or self == self.IdleLow_SampleFalling)

    @property
    def is_idle_high(self) -> bool:
        return (self == self.IdleHigh_SampleFalling or self == self.IdleHigh_SampleRising)

    @property
    def is_rising(self) -> bool:
        return (self == self.IdleLow_SampleRising or self == self.IdleHigh_SampleRising)

    @property
    def is_falling(self) -> bool:
        return (self == self.IdleLow_SampleFalling or self == self.IdleHigh_SampleFalling)

    @property
    def cpol(self) -> Literal[0, 1]:
        return int(self.is_idle_high)

    @property
    def cpha(self) -> Literal[0, 1]:
        return int(self.is_falling ^ self.is_idle_high)


class Operation(enum.Enum, shape=2):
    Idle = 0
    Put  = 1
    Get  = 2
    Swap = 3


class Sample(data.Struct):
    oper: Operation
    half: 1


class Enframer(wiring.Component):
    def __init__(self, ports, *, chip_count=None):
        super().__init__({
            "octets":  In(stream.Signature(data.StructLayout({
                "chip": range(1 + (chip_count or len(ports.cs))),
                "mode": Mode,
                "oper": Operation,
                "data": 8,
            }))),
            "frames":  Out(IOStreamer.i_signature(ports, ratio=2, meta_layout=Sample)),
            "divisor": In(16)
        })

    def elaborate(self, platform):
        m = Module()

        is_rising = (self.octets.p.mode
            .matches(Mode.IdleLow_SampleRising, Mode.IdleHigh_SampleRising))
        is_idle_high = (self.octets.p.mode
            .matches(Mode.IdleHigh_SampleFalling, Mode.IdleHigh_SampleRising))

        timer = Signal.like(self.divisor)
        cycle = Signal(range(8))

        for n in range(2):
            m.d.comb += self.frames.p.port.cs.o[n].eq((1 << self.octets.p.chip)[1:])
        m.d.comb += self.frames.p.port.cs.oe.eq(1)

        rev_data = self.octets.p.data[::-1] # MSB first
        with m.Switch(self.octets.p.oper):
            with m.Case(Operation.Put, Operation.Swap):
                for n in range(2):
                    m.d.comb += self.frames.p.port.copi.o[n].eq(rev_data.word_select(cycle, 1))
                m.d.comb += self.frames.p.port.copi.oe.eq(0b1)
            with m.Case(Operation.Get):
                m.d.comb += self.frames.p.port.copi.oe.eq(0b1)

        # When no chip is selected, keep clock in the idle state. The only supported `oper`
        # in this case is `SPIMode.Dummy`, which should be used to deassert CS# at the end of
        # a transfer.
        with m.If(self.octets.p.chip):
            m.d.comb += self.frames.p.port.sck.o[0].eq((timer * 2 >  self.divisor) ^ ~is_rising)
            m.d.comb += self.frames.p.port.sck.o[1].eq((timer * 2 >= self.divisor) ^ ~is_rising)
        with m.Else():
            for n in range(2):
                m.d.comb += self.frames.p.port.sck.o[n].eq(is_idle_high)
        m.d.comb += self.frames.p.port.sck.oe.eq(1)

        with m.If(timer == (self.divisor + 1) >> 1):
            with m.Switch(self.octets.p.oper):
                with m.Case(Operation.Get, Operation.Swap):
                    m.d.comb += self.frames.p.meta.oper.eq(self.octets.p.oper)
                    m.d.comb += self.frames.p.meta.half.eq(~self.divisor[0])

        m.d.comb += self.frames.valid.eq(self.octets.valid)
        with m.If(self.frames.valid & self.frames.ready):
            with m.If(timer == self.divisor):
                with m.Switch(self.octets.p.oper):
                    with m.Case(Operation.Put, Operation.Get, Operation.Swap):
                        m.d.comb += self.octets.ready.eq(cycle == 7)
                    with m.Case(Operation.Idle):
                        m.d.comb += self.octets.ready.eq(cycle == 0)
                m.d.sync += cycle.eq(Mux(self.octets.ready, 0, cycle + 1))
                m.d.sync += timer.eq(0)
            with m.Else():
                m.d.sync += timer.eq(timer + 1)

        return m


class Deframer(wiring.Component):
    def __init__(self, ports):
        super().__init__({
            "frames": In(IOStreamer.o_signature(ports, ratio=2, meta_layout=Sample)),
            "octets": Out(stream.Signature(data.StructLayout({
                "data": 8,
            }))),
        })

    def elaborate(self, platform):
        m = Module()

        shreg = Signal(8)
        with m.Switch(self.frames.p.meta.oper):
            half = self.frames.p.meta.half
            with m.Case(Operation.Get, Operation.Swap):
                m.d.comb += self.octets.p.data.eq(Cat(self.frames.p.port.cipo.i[half], shreg))

        cycle = Signal(range(8))
        m.d.comb += self.frames.ready.eq(1)
        with m.If(self.frames.valid & (self.frames.p.meta.oper != Operation.Idle)):
            with m.Switch(self.frames.p.meta.oper):
                with m.Case(Operation.Get, Operation.Swap):
                    m.d.comb += self.octets.valid.eq(cycle == 7)
            m.d.comb += self.frames.ready.eq(~self.octets.valid | self.octets.ready)
            with m.If(self.frames.ready):
                m.d.sync += shreg.eq(self.octets.p.data)
                m.d.sync += cycle.eq(Mux(self.octets.valid, 0, cycle + 1))

        return m


class Controller(wiring.Component):
    def __init__(self, ports, *, offset=0, chip_count=None):
        assert chip_count is None or len(ports.cs) <= chip_count
        assert len(ports.cs)   >= 1
        assert len(ports.sck)  == 1
        assert len(ports.copi) == 1
        assert len(ports.cipo) == 1

        self._ports = PortGroup(
            cs   = ~ports.cs  .with_direction("o"),
            sck  =  ports.sck .with_direction("o"),
            copi =  ports.copi.with_direction("o"),
            cipo =  ports.cipo.with_direction("i"),
        )
        self._offset = offset
        self._chip_count = chip_count or len(ports.cs)

        super().__init__({
            "i_stream": In(stream.Signature(data.StructLayout({
                "chip": range(1 + self._chip_count),
                "mode": Mode,
                "oper": Operation,
                "data": 8
            }))),
            "o_stream": Out(stream.Signature(data.StructLayout({
                "data": 8
            }))),
            "divisor": In(16),
        })

    def elaborate(self, platform):
        m = Module()

        m.submodules.enframer = enframer = Enframer(ports=self._ports, chip_count=self._chip_count)
        connect(m, enframer=enframer.octets, controller=flipped(self.i_stream))
        m.d.comb += enframer.divisor.eq(self.divisor)

        m.submodules.io_streamer = io_streamer = \
            IOStreamer(self._ports, ratio=2, offset=self._offset, meta_layout=Sample, init={
                "cs":  {"o": 0, "oe": 1}, # deselected
            })
        connect(m, io_streamer=io_streamer.i, enframer=enframer.frames)

        m.submodules.deframer = deframer = Deframer(ports=self._ports)
        connect(m, deframer=deframer.frames, io_streamer=io_streamer.o)

        connect(m, controller=flipped(self.o_stream), deframer=deframer.octets)

        return m
