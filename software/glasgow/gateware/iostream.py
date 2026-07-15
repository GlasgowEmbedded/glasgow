from amaranth import *
from amaranth.lib import data, wiring, stream, io
from amaranth.lib.wiring import In, Out
from amaranth.vendor import SiliconBluePlatform, LatticePlatform

from glasgow.hardware.platform import ecp5
from glasgow.gateware.stream import SkidBuffer


__all__ = ["IOStreamer", "HalfRateIOStreamer"]


def _i_signature(ports, *, ratio=1, meta_layout=0, always_valid=False, always_ready=False):
    return stream.Signature(data.StructLayout({
        "port": data.StructLayout({
            name: data.StructLayout({
                "o":  data.ArrayLayout(len(port), ratio),
                "oe": 1
            })
            for name, port in ports
            if port.direction in (io.Direction.Output, io.Direction.Bidir)
        }),
        "meta": meta_layout
    }), always_valid=always_valid, always_ready=always_ready)


def _o_signature(ports, *, ratio=1, meta_layout=0, always_valid=False, always_ready=False):
    return stream.Signature(data.StructLayout({
        "port": data.StructLayout({
            name: data.StructLayout({
                "i": data.ArrayLayout(len(port), ratio)
            })
            for name, port in ports
            if port.direction in (io.Direction.Input, io.Direction.Bidir)
        }),
        "meta": meta_layout
    }), always_valid=always_valid, always_ready=always_ready)


class SimulatableDDRBuffer(io.DDRBuffer):
    def elaborate(self, platform):
        if not isinstance(self._port, io.SimulationPort):
            return super().elaborate(platform)

        # At the time of writing Amaranth DDRBuffer doesn't allow for simulation, this implements
        # ICE40 semantics for simulation.
        m = Module()

        m.submodules.io_buffer = io_buffer = io.Buffer(self.direction, self.port)

        if self.direction is not io.Direction.Output:
            m.domains.i_domain_n = cd_i_domain_n = ClockDomain(local=True)
            m.d.comb += cd_i_domain_n.clk.eq(~ClockSignal(self.i_domain))
            i_ff_pos = Signal.like(io_buffer.i, reset_less=True)
            i_ff_neg = Signal.like(io_buffer.i, reset_less=True)
            i_ff_out = Signal.like(self.i,      reset_less=True)
            m.d[self.i_domain] += i_ff_pos.eq(io_buffer.i)
            m.d.i_domain_n     += i_ff_neg.eq(io_buffer.i)
            m.d[self.i_domain] += i_ff_out.eq(Cat(i_ff_pos, i_ff_neg))
            m.d.comb           += self.i.eq(i_ff_out)

        if self.direction is not io.Direction.Input:
            m.domains.o_domain_n = cd_o_domain_n = ClockDomain(local=True)
            m.d.comb += cd_o_domain_n.clk.eq(~ClockSignal(self.o_domain))
            o_1_ff   = Signal.like(self.o[1], reset_less=True)
            o_ff_pos = Signal.like(self.o[0], reset_less=True)
            o_ff_neg = Signal.like(self.o[1], reset_less=True)
            m.d[self.o_domain] += o_1_ff  .eq(self.o[1])
            m.d[self.o_domain] += o_ff_pos.eq(self.o[0]  ^ o_ff_neg)
            m.d.o_domain_n     += o_ff_neg.eq(o_1_ff     ^ o_ff_pos)
            m.d.comb           += io_buffer.o.eq(o_ff_pos ^ o_ff_neg)

            oe_ff = Signal(reset_less=True)
            m.d[self.o_domain] += oe_ff.eq(self.oe)
            m.d.comb           += io_buffer.oe.eq(oe_ff)

        return m


class StreamIOBuffer(wiring.Component):
    def __init__(self, ports, *, ratio, offset, meta_layout):
        self._ports  = ports
        self._ratio  = ratio
        self._offset = offset

        super().__init__({
            "i": In(_i_signature(ports, ratio=ratio, meta_layout=meta_layout,
                always_valid=True, always_ready=True)),
            "o": Out(_o_signature(ports, ratio=ratio, meta_layout=meta_layout,
                always_valid=True, always_ready=True)),
        })

    @property
    def ratio(self):
        return self._ratio

    def _latency(self, platform):
        match self._ratio, platform:
            case 1, _:
                latency = 1
            case 2, None:
                latency = 2 # simulation; like SiliconBlue
            case 2, SiliconBluePlatform():
                latency = 2 # t1=1, t2=1
            case 2, LatticePlatform():
                latency = 4 # t1=3, t2=1
            case 4, LatticePlatform():
                latency = 6 # t1=3, t2=3
            case _:
                raise NotImplementedError("latency not known for this ratio and platform")
        return latency + -(self._offset // -self._ratio) # ceiling division

    def elaborate(self, platform):
        m = Module()

        match self._ratio, platform:
            case 1, _:
                buffer_cls = io.FFBuffer
            case 2, _:
                buffer_cls = SimulatableDDRBuffer
            case 4, LatticePlatform():
                buffer_cls = ecp5.QDRBuffer
            case _:
                raise NotImplementedError("buffer not implemented for this ratio and platform")

        for name, port in self._ports:
            m.submodules[name] = buffer = buffer_cls(port.direction, port)
            if port.direction in (io.Direction.Output, io.Direction.Bidir):
                m.d.comb += buffer.o.eq(self.i.p.port[name].o)
                m.d.comb += buffer.oe.eq(self.i.p.port[name].oe)
            if port.direction in (io.Direction.Input, io.Direction.Bidir):
                buffer_i = Signal(data.ArrayLayout(len(port), self._ratio))
                m.d.comb += buffer_i.eq(buffer.i) # FFBuffer doesn't use ArrayLayout, normalize

                i_window = Signal(data.ArrayLayout(len(port), self._ratio * 2))
                for idx in range(self._ratio):
                    m.d.sync += i_window[idx].eq(buffer_i[idx])
                    m.d.comb += i_window[self._ratio + idx].eq(buffer_i[idx])

                offset = self._ratio - (self._offset % self._ratio)
                for idx in range(self._ratio):
                    m.d.comb += self.o.p.port[name].i[idx].eq(i_window[offset + idx])

        meta = self.i.p.meta
        for n in range(self._latency(platform)):
            reg = Signal.like(self.o.p.meta, name=f"meta_{n}")
            m.d.sync += reg.eq(meta)
            meta = reg
        m.d.comb += self.o.p.meta.eq(meta)

        return m


class IOStreamer(wiring.Component):
    @staticmethod
    def i_signature(ports, *, ratio=1, meta_layout=0):
        return _i_signature(ports, ratio=ratio, meta_layout=meta_layout)

    @staticmethod
    def o_signature(ports, *, ratio=1, meta_layout=0):
        return _o_signature(ports, ratio=ratio, meta_layout=meta_layout)

    def __init__(self, ports, *, ratio=1, offset=0, init=None, meta_layout=0):
        assert ratio in (1, 2, 4), "IOStreamer supports SDR/DDR/QDR I/O only"

        self._ports  = ports
        self._ratio  = ratio
        self._offset = offset
        self._init   = init

        super().__init__({
            "i":  In(self.i_signature(ports, ratio=ratio, meta_layout=meta_layout)),
            "o": Out(self.o_signature(ports, ratio=ratio, meta_layout=meta_layout)),
        })

    @property
    def ratio(self):
        return self._ratio

    def elaborate(self, platform):
        m = Module()

        meta_layout = data.StructLayout({
            "data":  self.i.p.meta.shape(),
            "valid": 1,
        })

        m.submodules.io_buffer = io_buffer = \
            StreamIOBuffer(self._ports, ratio=self._ratio, offset=self._offset,
                           meta_layout=meta_layout)
        m.submodules.skid_buffer = skid_buffer = \
            SkidBuffer(self.o.payload.shape(), depth=io_buffer._latency(platform))

        latch = Signal(data.StructLayout({
            name: data.StructLayout({
                "o":  len(port),
                "oe": 1
            })
            for name, port in self._ports
            if port.direction in (io.Direction.Output, io.Direction.Bidir)
        }), init=self._init)

        with m.If(skid_buffer.i.ready & self.i.valid):
            m.d.comb += self.i.ready.eq(1)
            m.d.comb += io_buffer.i.p.meta.valid.eq(1)
            for name, port in self._ports:
                if port.direction in (io.Direction.Bidir, io.Direction.Output):
                    m.d.sync += latch[name].o.eq(self.i.p.port[name].o[-1])
                    m.d.sync += latch[name].oe.eq(self.i.p.port[name].oe)

        with m.If(skid_buffer.i.ready & self.i.valid):
            m.d.comb += io_buffer.i.p.port.eq(self.i.p.port)
            m.d.comb += io_buffer.i.p.meta.data.eq(self.i.p.meta)
        with m.Else():
            for name, port in self._ports:
                if port.direction in (io.Direction.Bidir, io.Direction.Output):
                    for n in range(self._ratio):
                        m.d.comb += io_buffer.i.p.port[name].o[n].eq(latch[name].o)
                    m.d.comb += io_buffer.i.p.port[name].oe.eq(latch[name].oe)

        m.d.comb += skid_buffer.i.p.port.eq(io_buffer.o.p.port)
        m.d.comb += skid_buffer.i.p.meta.eq(io_buffer.o.p.meta.data)
        m.d.comb += skid_buffer.i.valid.eq(io_buffer.o.p.meta.valid)

        wiring.connect(m, wiring.flipped(self.o), skid_buffer.o)

        return m


class HalfRateIOStreamer(wiring.Component):
    def __init__(self, ports, *, ratio, offset=0, init=None, meta_layout=0):
        assert ratio in (2, 4), "HalfRateIOStreamer supports DDR and QDR I/O only"

        self._ports  = ports
        self._ratio  = ratio
        self._offset = offset
        self._init   = init
        self._meta_layout = meta_layout

        super().__init__({
            "i":  In(IOStreamer.i_signature(ports, ratio=ratio, meta_layout=meta_layout)),
            "o": Out(IOStreamer.o_signature(ports, ratio=ratio, meta_layout=meta_layout)),
        })

    @property
    def ratio(self):
        return self._ratio

    def elaborate(self, platform):
        m = Module()

        m.submodules.inner = inner = IOStreamer(
            ports=self._ports, ratio=self._ratio//2, offset=self._offset, init=self._init,
            meta_layout=self._meta_layout,
        )

        fst_half = slice(0, 2)
        snd_half = slice(2, 4)

        i_phase = Signal()
        for name, port in self._ports:
            if port.direction in (io.Direction.Bidir, io.Direction.Output):
                m.d.comb += inner.i.p.port[name].o.eq(
                    Mux(i_phase, self.i.p.port[name].o[snd_half], self.i.p.port[name].o[fst_half]))
                m.d.comb += inner.i.p.port[name].oe.eq(self.i.p.port[name].oe)
        m.d.comb += inner.i.p.meta.eq(self.i.p.meta)

        m.d.comb += inner.i.valid.eq(self.i.valid)
        with m.If(inner.i.valid & inner.i.ready):
            m.d.sync += i_phase.eq(~i_phase)
            m.d.comb += self.i.ready.eq(i_phase)

        o_phase = Signal()
        for name, port in self._ports:
            if port.direction in (io.Direction.Bidir, io.Direction.Input):
                with m.If(inner.o.valid & ~o_phase):
                    m.d.sync += self.o.p.port[name].i[fst_half].eq(inner.o.p.port[name].i)
                m.d.comb += self.o.p.port[name].i[snd_half].eq(inner.o.p.port[name].i)
        m.d.comb += self.o.p.meta.eq(inner.o.p.meta)

        m.d.comb += inner.o.ready.eq(~o_phase | self.o.ready)
        m.d.comb += self.o.valid.eq(inner.o.valid & o_phase)
        with m.If(inner.o.valid & inner.o.ready):
            m.d.sync += o_phase.eq(~o_phase)

        return m
