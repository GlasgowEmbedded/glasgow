from amaranth import *
from amaranth.lib import enum, data, wiring, stream, io
from amaranth.lib.wiring import In, Out, connect, flipped

from .ports import PortGroup
from .iostream import IOStreamer


__all__ = ["Mode", "Enframer", "Deframer", "Controller"]


class Mode(enum.Enum, shape=3):
    Dummy = 0
    PutX1 = 1
    GetX1 = 2
    PutX2 = 3
    GetX2 = 4
    PutX4 = 5
    GetX4 = 6
    Swap  = 7 # normal SPI


class Sample(data.Struct):
    mode: Mode
    half: 1


class Enframer(wiring.Component):
    def __init__(self, ports, *, chip_count=None):
        super().__init__({
            "octets":  In(stream.Signature(data.StructLayout({
                "chip": range(1 + (chip_count or len(ports.cs))),
                "mode": Mode,
                "data": 8,
            }))),
            "frames":  Out(IOStreamer.i_signature(ports, ratio=2, meta_layout=Sample)),
            "divisor": In(16)
        })

    def elaborate(self, platform):
        m = Module()

        timer = Signal.like(self.divisor)
        cycle = Signal(range(8))

        for n in range(2):
            m.d.comb += self.frames.p.port.cs.o[n].eq((1 << self.octets.p.chip)[1:])
        m.d.comb += self.frames.p.port.cs.oe.eq(1)

        rev_data = self.octets.p.data[::-1] # MSB first
        with m.Switch(self.octets.p.mode):
            with m.Case(Mode.PutX1, Mode.Swap):
                for n in range(2):
                    m.d.comb += self.frames.p.port.io0.o[n].eq(rev_data.word_select(cycle, 1))
                m.d.comb += self.frames.p.port.io0.oe.eq(0b1)
            with m.Case(Mode.GetX1):
                m.d.comb += self.frames.p.port.io0.oe.eq(0b1)
            with m.Case(Mode.PutX2):
                for n in range(2):
                    m.d.comb += Cat(self.frames.p.port.io1.o[n],
                                    self.frames.p.port.io0.o[n]).eq(rev_data.word_select(cycle, 2))
                m.d.comb += Cat(self.frames.p.port.io1.oe,
                                self.frames.p.port.io0.oe).eq(0b11)
            with m.Case(Mode.PutX4):
                for n in range(2):
                    m.d.comb += Cat(self.frames.p.port.io3.o[n],
                                    self.frames.p.port.io2.o[n],
                                    self.frames.p.port.io1.o[n],
                                    self.frames.p.port.io0.o[n]).eq(rev_data.word_select(cycle, 4))
                m.d.comb += Cat(self.frames.p.port.io3.oe,
                                self.frames.p.port.io2.oe,
                                self.frames.p.port.io1.oe,
                                self.frames.p.port.io0.oe).eq(0b1111)

        # When no chip is selected, keep clock in the idle state. The only supported `mode`
        # in this case is `QSPIMode.Dummy`, which should be used to deassert CS# at the end of
        # a transfer.
        with m.If(self.octets.p.chip):
            m.d.comb += self.frames.p.port.sck.o[0].eq(timer * 2 >  self.divisor)
            m.d.comb += self.frames.p.port.sck.o[1].eq(timer * 2 >= self.divisor)
        m.d.comb += self.frames.p.port.sck.oe.eq(1)

        with m.If(timer == (self.divisor + 1) >> 1):
            with m.Switch(self.octets.p.mode):
                with m.Case(Mode.GetX1, Mode.GetX2, Mode.GetX4, Mode.Swap):
                    m.d.comb += self.frames.p.meta.mode.eq(self.octets.p.mode)
                    m.d.comb += self.frames.p.meta.half.eq(~self.divisor[0])

        m.d.comb += self.frames.valid.eq(self.octets.valid)
        with m.If(self.frames.valid & self.frames.ready):
            with m.If(timer == self.divisor):
                with m.Switch(self.octets.p.mode):
                    with m.Case(Mode.PutX1, Mode.GetX1, Mode.Swap):
                        m.d.comb += self.octets.ready.eq(cycle == 7)
                    with m.Case(Mode.PutX2, Mode.GetX2):
                        m.d.comb += self.octets.ready.eq(cycle == 3)
                    with m.Case(Mode.PutX4, Mode.GetX4):
                        m.d.comb += self.octets.ready.eq(cycle == 1)
                    with m.Case(Mode.Dummy):
                        m.d.comb += self.octets.ready.eq(cycle == 0)
                m.d.sync += cycle.eq(Mux(self.octets.ready, 0, cycle + 1))
                m.d.sync += timer.eq(0)
            with m.Else():
                m.d.sync += timer.eq(timer + 1)

        return m


class Deframer(wiring.Component): # meow :3
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
        with m.Switch(self.frames.p.meta.mode):
            half = self.frames.p.meta.half
            with m.Case(Mode.GetX1, Mode.Swap): # note: samples IO1
                m.d.comb += self.octets.p.data.eq(Cat(self.frames.p.port.io1.i[half], shreg))
            with m.Case(Mode.GetX2):
                m.d.comb += self.octets.p.data.eq(Cat(self.frames.p.port.io0.i[half],
                                                      self.frames.p.port.io1.i[half], shreg))
            with m.Case(Mode.GetX4):
                m.d.comb += self.octets.p.data.eq(Cat(self.frames.p.port.io0.i[half],
                                                      self.frames.p.port.io1.i[half],
                                                      self.frames.p.port.io2.i[half],
                                                      self.frames.p.port.io3.i[half], shreg))

        cycle = Signal(range(8))
        m.d.comb += self.frames.ready.eq(1)
        with m.If(self.frames.valid & (self.frames.p.meta.mode != Mode.Dummy)):
            with m.Switch(self.frames.p.meta.mode):
                with m.Case(Mode.GetX1, Mode.Swap):
                    m.d.comb += self.octets.valid.eq(cycle == 7)
                with m.Case(Mode.GetX2):
                    m.d.comb += self.octets.valid.eq(cycle == 3)
                with m.Case(Mode.GetX4):
                    m.d.comb += self.octets.valid.eq(cycle == 1)
            m.d.comb += self.frames.ready.eq(~self.octets.valid | self.octets.ready)
            with m.If(self.frames.ready):
                m.d.sync += shreg.eq(self.octets.p.data)
                m.d.sync += cycle.eq(Mux(self.octets.valid, 0, cycle + 1))

        return m


class Controller(wiring.Component):
    def __init__(self, ports, *, offset=0, chip_count=None):
        assert chip_count is None or len(ports.cs) <= chip_count
        assert len(ports.cs) >= 1 and ports.cs.direction in (io.Direction.Output, io.Direction.Bidir)
        assert len(ports.sck) == 1 and ports.sck.direction in (io.Direction.Output, io.Direction.Bidir)
        assert len(ports.io) == 4 and ports.io.direction == io.Direction.Bidir

        self._ports = PortGroup(
            cs=~ports.cs.with_direction("o"),
            sck=ports.sck.with_direction("o"),
            io0=ports.io[0].with_direction("io"),
            io1=ports.io[1].with_direction("io"),
            io2=ports.io[2].with_direction("io"),
            io3=ports.io[3].with_direction("io"),
        )
        self._offset = offset
        self._chip_count = chip_count or len(ports.cs)

        super().__init__({
            "i_stream": In(stream.Signature(data.StructLayout({
                "chip": range(1 + self._chip_count),
                "mode": Mode,
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
                "sck": {"o": 1, "oe": 1}, # Motorola "Mode 3" with clock idling high
            })
        connect(m, io_streamer=io_streamer.i, enframer=enframer.frames)

        m.submodules.deframer = deframer = Deframer(ports=self._ports)
        connect(m, deframer=deframer.frames, io_streamer=io_streamer.o)

        connect(m, controller=flipped(self.o_stream), deframer=deframer.octets)

        return m
