from amaranth import *
from amaranth.lib import enum, data, wiring, stream, io
from amaranth.lib.wiring import In, Out, connect, flipped

from .ports import PortGroup
from .iostream import IOStream


__all__ = ["QSPIMode", "QSPIEnframer", "QSPIDeframer", "QSPIController"]


class QSPIMode(enum.Enum, shape=3):
    Dummy = 0
    PutX1 = 1
    GetX1 = 2
    PutX2 = 3
    GetX2 = 4
    PutX4 = 5
    GetX4 = 6
    Swap  = 7 # normal SPI


class QSPIEnframer(wiring.Component):
    def __init__(self, *, chip_count=1):
        assert chip_count >= 1

        super().__init__({
            "octets": In(stream.Signature(data.StructLayout({
                "chip": range(1 + chip_count),
                "mode": QSPIMode,
                "data": 8,
            }))),
            "frames": Out(stream.Signature(data.StructLayout({
                "port": data.StructLayout({
                    "io0": data.StructLayout({
                        "o":  1,
                        "oe": 1,
                    }),
                    "io1": data.StructLayout({
                        "o":  1,
                        "oe": 1,
                    }),
                    "io2": data.StructLayout({
                        "o":  1,
                        "oe": 1,
                    }),
                    "io3": data.StructLayout({
                        "o":  1,
                        "oe": 1,
                    }),
                    "cs":  data.StructLayout({
                        "o":  chip_count,
                        "oe": 1,
                    }),
                }),
                "i_en": 1,
                "meta": QSPIMode,
            }))),
        })

    def elaborate(self, platform):
        m = Module()

        cycle = Signal(range(8))
        m.d.comb += self.frames.valid.eq(self.octets.valid)
        with m.If(self.octets.valid & self.frames.ready):
            with m.Switch(self.octets.p.mode):
                with m.Case(QSPIMode.PutX1, QSPIMode.GetX1, QSPIMode.Swap):
                    m.d.comb += self.octets.ready.eq(cycle == 7)
                with m.Case(QSPIMode.PutX2, QSPIMode.GetX2):
                    m.d.comb += self.octets.ready.eq(cycle == 3)
                with m.Case(QSPIMode.PutX4, QSPIMode.GetX4):
                    m.d.comb += self.octets.ready.eq(cycle == 1)
                with m.Case(QSPIMode.Dummy):
                    m.d.comb += self.octets.ready.eq(cycle == 0)
            m.d.sync += cycle.eq(Mux(self.octets.ready, 0, cycle + 1))

        rev_data = self.octets.p.data[::-1] # MSB first
        with m.Switch(self.octets.p.mode):
            with m.Case(QSPIMode.PutX1, QSPIMode.Swap):
                m.d.comb += self.frames.p.port.io0.o.eq(rev_data.word_select(cycle, 1))
                m.d.comb += self.frames.p.port.io0.oe.eq(0b1)
                m.d.comb += self.frames.p.i_en.eq(self.octets.p.mode == QSPIMode.Swap)
            with m.Case(QSPIMode.GetX1):
                m.d.comb += self.frames.p.port.io0.oe.eq(0b1)
                m.d.comb += self.frames.p.i_en.eq(1)
            with m.Case(QSPIMode.PutX2):
                m.d.comb += Cat(self.frames.p.port.io1.o,
                                self.frames.p.port.io0.o).eq(rev_data.word_select(cycle, 2))
                m.d.comb += Cat(self.frames.p.port.io1.oe,
                                self.frames.p.port.io0.oe).eq(0b11)
            with m.Case(QSPIMode.GetX2):
                m.d.comb += self.frames.p.i_en.eq(1)
            with m.Case(QSPIMode.PutX4):
                m.d.comb += Cat(self.frames.p.port.io3.o,
                                self.frames.p.port.io2.o,
                                self.frames.p.port.io1.o,
                                self.frames.p.port.io0.o).eq(rev_data.word_select(cycle, 4))
                m.d.comb += Cat(self.frames.p.port.io3.oe,
                                self.frames.p.port.io2.oe,
                                self.frames.p.port.io1.oe,
                                self.frames.p.port.io0.oe).eq(0b1111)
            with m.Case(QSPIMode.GetX4):
                m.d.comb += self.frames.p.i_en.eq(1)
        m.d.comb += self.frames.p.port.cs.o.eq((1 << self.octets.p.chip)[1:])
        m.d.comb += self.frames.p.port.cs.oe.eq(1)
        m.d.comb += self.frames.p.meta.eq(self.octets.p.mode)

        return m


class QSPIDeframer(wiring.Component): # meow :3
    def __init__(self):
        super().__init__({
            "frames": In(stream.Signature(data.StructLayout({
                "port": data.StructLayout({
                    "io0": data.StructLayout({
                        "i":  1,
                    }),
                    "io1": data.StructLayout({
                        "i":  1,
                    }),
                    "io2": data.StructLayout({
                        "i":  1,
                    }),
                    "io3": data.StructLayout({
                        "i":  1,
                    }),
                }),
                "meta": QSPIMode,
            }))),
            "octets": Out(stream.Signature(data.StructLayout({
                "data": 8,
            }))),
        })

    def elaborate(self, platform):
        m = Module()

        cycle = Signal(range(8))
        m.d.comb += self.frames.ready.eq(~self.octets.valid | self.octets.ready)
        with m.If(self.frames.valid):
            with m.Switch(self.frames.p.meta):
                with m.Case(QSPIMode.GetX1, QSPIMode.Swap):
                    m.d.comb += self.octets.valid.eq(cycle == 7)
                with m.Case(QSPIMode.GetX2):
                    m.d.comb += self.octets.valid.eq(cycle == 3)
                with m.Case(QSPIMode.GetX4):
                    m.d.comb += self.octets.valid.eq(cycle == 1)
            with m.If(self.frames.ready):
                m.d.sync += cycle.eq(Mux(self.octets.valid, 0, cycle + 1))

        data_reg = Signal(8)
        with m.Switch(self.frames.p.meta):
            with m.Case(QSPIMode.GetX1, QSPIMode.Swap): # note: samples IO1
                m.d.comb += self.octets.p.data.eq(Cat(self.frames.p.port.io1.i, data_reg))
            with m.Case(QSPIMode.GetX2):
                m.d.comb += self.octets.p.data.eq(Cat(self.frames.p.port.io0.i,
                                                      self.frames.p.port.io1.i, data_reg))
            with m.Case(QSPIMode.GetX4):
                m.d.comb += self.octets.p.data.eq(Cat(self.frames.p.port.io0.i,
                                                      self.frames.p.port.io1.i,
                                                      self.frames.p.port.io2.i,
                                                      self.frames.p.port.io3.i, data_reg))
        with m.If(self.frames.valid & self.frames.ready):
            m.d.sync += data_reg.eq(self.octets.p.data)

        return m


# FIXME: needs new name and location
class Downscaler(wiring.Component):
    def __init__(self, payload_shape, *, divisor_width=16):
        super().__init__({
            "divisor": In(divisor_width),

            # FIXME: i_stream/o_stream or fast/slow? [io]_stream has opposite meaning of IOStream
            "fast": In(stream.Signature(payload_shape)),
            "slow": Out(stream.Signature(payload_shape)),
        })

    def elaborate(self, platform):
        m = Module()

        timer = Signal.like(self.divisor)
        with m.If((timer == 0) | (timer == 1)):
            m.d.comb += self.slow.valid.eq(self.fast.valid)
            m.d.comb += self.fast.ready.eq(self.slow.ready)
            with m.If(self.fast.valid & self.slow.ready):
                m.d.sync += timer.eq(self.divisor)
        with m.Else():
            m.d.sync += timer.eq(timer - 1)

        m.d.comb += self.slow.payload.eq(self.fast.payload)

        return m


class QSPIController(wiring.Component):
    def __init__(self, ports, *, chip_count=1, use_ddr_buffers=False):
        assert len(ports.sck) == 1 and ports.sck.direction in (io.Direction.Output, io.Direction.Bidir)
        assert len(ports.io) == 4 and ports.io.direction == io.Direction.Bidir

        self._ports = ports
        self._ddr = use_ddr_buffers

        super().__init__({
            "divisor": In(16),

            "o_octets": In(stream.Signature(data.StructLayout({
                "chip": range(1 + chip_count),
                "mode": QSPIMode,
                "data": 8
            }))),
            "i_octets": Out(stream.Signature(data.StructLayout({
                "data": 8
            }))),
        })

    def elaborate(self, platform):
        ratio = (2 if self._ddr else 1)

        m = Module()

        m.submodules.iostream = iostream = IOStream(PortGroup(
            sck=self._ports.sck,
            io0=self._ports.io[0],
            io1=self._ports.io[1],
            io2=self._ports.io[2],
            io3=self._ports.io[3],
            cs=~self._ports.cs,
        ), init={
            "sck": {"o": 1, "oe": 1}, # Motorola "Mode 3" with clock idling high
            "cs":  {"o": 0, "oe": 1}, # deselected
        }, ratio=ratio, meta_layout=QSPIMode)

        m.submodules.downscaler = downscaler = Downscaler(iostream.o_stream.payload.shape(),
            divisor_width=len(self.divisor))
        connect(m, downscaler=downscaler.slow, iostream=iostream.o_stream)
        m.d.comb += downscaler.divisor.eq(self.divisor)

        m.submodules.enframer = enframer = QSPIEnframer()
        connect(m, controller=flipped(self.o_octets), enframer=enframer.octets)

        m.submodules.deframer = deframer = QSPIDeframer()
        connect(m, controller=flipped(self.i_octets), deframer=deframer.octets)

        phase = Signal()
        with m.If(self._ddr & (self.divisor == 0)): # special case: transfer each cycle
            m.d.sync += phase.eq(1)
        with m.Elif(iostream.o_stream.valid): # half-transfer or less each cycle
            m.d.sync += phase.eq(~phase)
        with m.If(enframer.frames.p.port.cs.o.any()):
            if self._ddr:
                m.d.comb += downscaler.fast.p.port.sck.o.eq(Cat(~phase, phase))
            else:
                m.d.comb += downscaler.fast.p.port.sck.o.eq(phase)
        with m.Else():
            m.d.comb += downscaler.fast.p.port.sck.o.eq(C(1).replicate(ratio))
        m.d.comb += [
            downscaler.fast.p.port.sck.oe.eq(1),
            downscaler.fast.p.port.io0.o.eq(enframer.frames.p.port.io0.o.replicate(ratio)),
            downscaler.fast.p.port.io1.o.eq(enframer.frames.p.port.io1.o.replicate(ratio)),
            downscaler.fast.p.port.io2.o.eq(enframer.frames.p.port.io2.o.replicate(ratio)),
            downscaler.fast.p.port.io3.o.eq(enframer.frames.p.port.io3.o.replicate(ratio)),
            downscaler.fast.p.port.cs.o.eq(enframer.frames.p.port.cs.o.replicate(ratio)),
            downscaler.fast.p.port.io0.oe.eq(enframer.frames.p.port.io0.oe),
            downscaler.fast.p.port.io1.oe.eq(enframer.frames.p.port.io1.oe),
            downscaler.fast.p.port.io2.oe.eq(enframer.frames.p.port.io2.oe),
            downscaler.fast.p.port.io3.oe.eq(enframer.frames.p.port.io3.oe),
            downscaler.fast.p.port.cs.oe.eq(enframer.frames.p.port.cs.oe),
            downscaler.fast.p.i_en.eq(enframer.frames.p.i_en & phase),
            downscaler.fast.p.meta.eq(enframer.frames.p.meta),
            downscaler.fast.valid.eq(enframer.frames.valid),
            enframer.frames.ready.eq(downscaler.fast.ready & phase),
        ]

        m.d.comb += [
            deframer.frames.p.port.io0.i.eq(iostream.i_stream.p.port.io0.i[0]),
            deframer.frames.p.port.io1.i.eq(iostream.i_stream.p.port.io1.i[0]),
            deframer.frames.p.port.io2.i.eq(iostream.i_stream.p.port.io2.i[0]),
            deframer.frames.p.port.io3.i.eq(iostream.i_stream.p.port.io3.i[0]),
            deframer.frames.p.meta.eq(iostream.i_stream.p.meta),
            deframer.frames.valid.eq(iostream.i_stream.valid),
            iostream.i_stream.ready.eq(deframer.frames.ready),
        ]

        return m
