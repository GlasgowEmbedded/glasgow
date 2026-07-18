from amaranth import *
from amaranth.lib import data, wiring, stream, io
from amaranth.lib.wiring import In, Out

from .stream import SkidBuffer


__all__ = ["IOStreamer"]


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
    def __init__(self, ports, *, ratio=1, offset=0, meta_layout=0,
                 i_domain="sync", o_domain="sync"):
        assert i_domain == o_domain or meta_layout == 0

        self._ports    = ports
        self._ratio    = ratio
        self._offset   = offset
        self._i_domain = i_domain
        self._o_domain = o_domain

        super().__init__({
            "i": In(stream.Signature(data.StructLayout({
                "port": data.StructLayout({
                    name: data.StructLayout({
                        "o":  data.ArrayLayout(len(port), ratio),
                        "oe": 1
                    })
                    for name, port in ports
                    if port.direction in (io.Direction.Output, io.Direction.Bidir)
                }),
                "meta": meta_layout,
            }), always_valid=True, always_ready=True)),
            "o": Out(stream.Signature(data.StructLayout({
                "port": data.StructLayout({
                    name: data.StructLayout({
                        "i": data.ArrayLayout(len(port), ratio),
                    })
                    for name, port in ports
                    if port.direction in (io.Direction.Input, io.Direction.Bidir)
                }),
                "meta": meta_layout,
            }), always_valid=True, always_ready=True))
        })

    @property
    def ratio(self):
        return self._ratio

    @property
    def latency(self):
        match self._ratio:
            case 1: latency = 1
            case 2: latency = 2
            case _: assert False
        return latency + -(self._offset // -self._ratio) # ceiling division

    def elaborate(self, platform):
        m = Module()

        match self._ratio:
            case 1: buffer_cls = io.FFBuffer
            case 2: buffer_cls = SimulatableDDRBuffer

        for name, port in self._ports:
            i_domain = o_domain = None
            if port.direction in (io.Direction.Input, io.Direction.Bidir):
                i_domain = self._i_domain
            if port.direction in (io.Direction.Output, io.Direction.Bidir):
                o_domain = self._o_domain
            m.submodules[name] = buffer = buffer_cls(port.direction, port,
                i_domain=i_domain, o_domain=o_domain)
            if port.direction in (io.Direction.Output, io.Direction.Bidir):
                m.d.comb += buffer.o.eq(self.i.p.port[name].o)
                m.d.comb += buffer.oe.eq(self.i.p.port[name].oe)
            if port.direction in (io.Direction.Input, io.Direction.Bidir):
                match self._ratio, self._offset:
                    case 1, _:
                        m.d.comb += self.o.p.port[name].i.eq(buffer.i)
                    case 2, offset if offset % self._ratio == 0:
                        m.d.comb += self.o.p.port[name].i.eq(buffer.i)
                    case 2, offset if offset % self._ratio == 1:
                        m.d[self._i_domain] += self.o.p.port[name].i[0].eq(buffer.i[1])
                        m.d.comb += self.o.p.port[name].i[1].eq(buffer.i[0])
                    case _, _:
                        raise NotImplementedError(
                            f"Unsupported ratio {self._ratio} and offset {self._offset}")

        meta = self.i.p.meta
        for n in range(self.latency):
            reg = Signal.like(self.o.p.meta, name=f"meta_{n}")
            m.d.sync += reg.eq(meta)
            meta = reg
        m.d.comb += self.o.p.meta.eq(meta)

        return m


class IOStreamer(wiring.Component):
    @staticmethod
    def i_signature(ports, *, ratio=1, meta_layout=0):
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
        }))

    @staticmethod
    def o_signature(ports, *, ratio=1, meta_layout=0):
        return stream.Signature(data.StructLayout({
            "port": data.StructLayout({
                name: data.StructLayout({
                    "i": data.ArrayLayout(len(port), ratio)
                })
                for name, port in ports
                if port.direction in (io.Direction.Input, io.Direction.Bidir)
            }),
            "meta": meta_layout
        }))

    def __init__(self, ports, *, ratio=1, offset=0, init=None, meta_layout=0):
        assert ratio in (1, 2), "IOStreamer supports SDR and DDR I/O only"

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
            SkidBuffer(self.o.payload.shape(), depth=io_buffer.latency)

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
