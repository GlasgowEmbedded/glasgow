from amaranth import *
from amaranth.lib import enum, data, wiring, stream, io
from amaranth.lib.wiring import In, Out

from glasgow.gateware.ports import PortGroup


__all__ = ["IOStream"]


@staticmethod
def _iter_parts(port, *args):
    if isinstance(port, io.PortLike):
        yield args
    if isinstance(port, PortGroup):
        for name in port.__dict__:
            yield tuple(arg[name] for arg in args)


@staticmethod
def _map_parts(port, fn):
    if isinstance(port, io.PortLike):
        return fn(port)
    if isinstance(port, PortGroup):
        return data.StructLayout(
            {name: fn(sub_port) for name, sub_port in port.__dict__.items()})
    assert False


class IOStream(wiring.Component):
    """I/O buffer to stream adapter.

    This adapter instantiates I/O buffers for a port (FF or DDR) and connects them to a pair of
    streams, one for the outputs of the buffers and one for the inputs. Whenever an `o_stream`
    transfer occurs, the state of the output is updated _t1_ cycles later; if `o_stream.p.i_en`
    is set, then _t2_ cycles later, a payload with the data captured at the same time as
    the outputs were updated appears on `i_stream.p.i`.

    Arbitrary ancillary data may be provided with `o_stream` transfers via `o_stream.p.meta`,
    and this data will be relayed back as `i_stream.p.meta` with the output-to-input latency
    of the buffer. Higher-level protocol engines can use this data to indicate how the inputs
    must be processed without needing counters or state machines on a higher level to match
    the latency (and, usually, without needing any knowledge of the latency at all).

    On reset, output ports have their drivers enabled, and bidirectional ports have them disabled.
    All of the signals are deasserted, which could be a low or a high level depending on the port
    polarity.
    """

    @staticmethod
    def o_stream_signature(port, /, *, ratio=1, meta_layout=0):
        return stream.Signature(data.StructLayout({
            "port": _map_parts(port, lambda port: data.StructLayout({
                "o":  data.ArrayLayout(len(port), ratio),
                "oe": 1,
            })),
            "i_en": 1,
            "meta": meta_layout,
        }))

    @staticmethod
    def i_stream_signature(port, /, *, ratio=1, meta_layout=0):
        return stream.Signature(data.StructLayout({
            "port": _map_parts(port, lambda port: data.StructLayout({
                "i":  data.ArrayLayout(len(port), ratio),
            })),
            "meta": meta_layout,
        }))

    def __init__(self, port, /, *, init=None, ratio=1, meta_layout=0):
        assert isinstance(port, (io.PortLike, PortGroup))
        assert ratio in (1, 2)

        self._port  = port
        self._init  = init
        self._ratio = ratio

        super().__init__({
            "o_stream": In(self.o_stream_signature(port, ratio=ratio, meta_layout=meta_layout)),
            "i_stream": Out(self.i_stream_signature(port, ratio=ratio, meta_layout=meta_layout)),
        })

    def elaborate(self, platform):
        m = Module()

        if self._ratio == 1:
            buffer_cls, latency = io.FFBuffer, 2
        if self._ratio == 2:
            # FIXME: should this be 2 or 3? the latency differs between i[0] and i[1]
            buffer_cls, latency = io.DDRBuffer, 3

        if isinstance(self._port, io.PortLike):
            m.submodules.buffer = buffer = buffer_cls("io", self._port)
        if isinstance(self._port, PortGroup):
            buffer = {}
            for name, sub_port in self._port.__dict__.items():
                m.submodules[f"buffer_{name}"] = buffer[name] = buffer_cls("io", sub_port)

        o_latch = Signal(_map_parts(self._port, lambda port: data.StructLayout({
            "o":  len(port),
            "oe": 1,
        })), init=self._init)
        with m.If(self.o_stream.valid & self.o_stream.ready):
            for latch_parts, stream_parts in _iter_parts(self._port, o_latch, self.o_stream.p.port):
                # FIXME: needs amaranth-lang/amaranth#1418
                m.d.sync += latch_parts.o.eq(stream_parts.o[self._ratio-1])
                m.d.sync += latch_parts.oe.eq(stream_parts.oe)
            for buffer_parts, stream_parts in _iter_parts(self._port, buffer, self.o_stream.p.port):
                m.d.comb += buffer_parts.o.eq(stream_parts.o)
                m.d.comb += buffer_parts.oe.eq(stream_parts.oe)
        with m.Else():
            for buffer_parts, latch_parts in _iter_parts(self._port, buffer, o_latch):
                m.d.comb += buffer_parts.o.eq(latch_parts.o.replicate(self._ratio))
                m.d.comb += buffer_parts.oe.eq(latch_parts.oe)

        def delay(value, name):
            for stage in range(latency):
                next_value = Signal.like(value, name=f"{name}_{stage}")
                m.d.sync += next_value.eq(value)
                value = next_value
            return value

        i_en = delay(self.o_stream.valid & self.o_stream.ready &
                     self.o_stream.p.i_en, name="i_en")
        meta = delay(self.o_stream.p.meta, name="meta")

        # This skid buffer is organized as a shift register to avoid any uncertainties associated
        # with the use of an async read memory. On platforms that have LUTRAM, this implementation
        # may be slightly worse than using LUTRAM, and may have to be revisited in the future.
        skid = Array(Signal(self.i_stream.payload.shape(), name=f"skid_{stage}")
                     for stage in range(1 + latency))
        for skid_parts, buffer_parts in _iter_parts(self._port, skid[0].port, buffer):
            m.d.comb += skid_parts.i.eq(buffer_parts.i)
        m.d.comb += skid[0].meta.eq(meta)

        skid_at = Signal(range(1 + latency))
        with m.If(i_en & ~self.i_stream.ready):
            # m.d.sync += Assert(skid_at != latency)
            m.d.sync += skid_at.eq(skid_at + 1)
            for n_shift in range(latency):
                m.d.sync += skid[n_shift + 1].eq(skid[n_shift])
        with m.Elif((skid_at != 0) & self.i_stream.ready):
            m.d.sync += skid_at.eq(skid_at - 1)

        m.d.comb += self.i_stream.payload.eq(skid[skid_at])
        m.d.comb += self.i_stream.valid.eq(i_en | (skid_at != 0))
        m.d.comb += self.o_stream.ready.eq(self.i_stream.ready & (skid_at == 0))

        return m
