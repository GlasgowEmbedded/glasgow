from amaranth import *
from amaranth.lib import wiring, stream, fifo
from amaranth.lib.wiring import In, Out


__all__ = ["stream_get", "stream_put", "StreamBuffer", "StreamFIFO"]


async def stream_get(ctx, stream):
    ctx.set(stream.ready, 1)
    payload, = await ctx.tick().sample(stream.payload).until(stream.valid)
    ctx.set(stream.ready, 0)
    return payload


async def stream_put(ctx, stream, payload):
    ctx.set(stream.payload, payload)
    ctx.set(stream.valid, 1)
    await ctx.tick().until(stream.ready)
    ctx.set(stream.valid, 0)


class StreamBuffer(wiring.Component):
    def __init__(self, shape):
        self._shape = shape
        super().__init__({
            "i": In(stream.Signature(shape)),
            "o": Out(stream.Signature(shape)),
        })

    def elaborate(self, platform):
        m = Module()

        with m.If(self.o.ready | ~self.o.valid):
            m.d.comb += self.i.ready.eq(1)
            m.d.sync += self.o.valid.eq(self.i.valid)
            m.d.sync += self.o.payload.eq(self.i.payload)

        return m


class StreamFIFO(wiring.Component):
    def __init__(self, *, shape, depth, w_domain="sync", r_domain="sync", buffered=True):
        self._shape = shape
        self._depth = depth
        self._w_domain = w_domain
        self._r_domain = r_domain
        self._buffered = buffered

        if w_domain == r_domain:
            super().__init__({
                "w": In(stream.Signature(shape)),
                "r": Out(stream.Signature(shape)),
                "level": Out(range(depth + 1))
            })
        else:
            super().__init__({
                "w": In(stream.Signature(shape)),
                "r": Out(stream.Signature(shape)),
            })

    def elaborate(self, platform):
        m = Module()

        if self._r_domain == self._w_domain:
            fifo_cls = fifo.SyncFIFOBuffered if self._buffered else fifo.SyncFIFO
            m.submodules.inner = inner = DomainRenamer(self._r_domain)(fifo_cls(
                width=Shape.cast(self._shape).width,
                depth=self._depth
            ))
            m.d.comb += self.level.eq(inner.level)
        else:
            fifo_cls = fifo.AsyncFIFOBuffered if self._buffered else fifo.AsyncFIFO
            m.submodules.inner = inner = fifo_cls(
                width=Shape.cast(self._shape).width,
                depth=self._depth,
                w_domain=self._w_domain,
                r_domain=self._r_domain,
            )

        m.d.comb += [
            inner.w_data.eq(self.w.payload),
            inner.w_en.eq(self.w.valid),
            self.w.ready.eq(inner.w_rdy),
            self.r.payload.eq(inner.r_data),
            self.r.valid.eq(inner.r_rdy),
            inner.r_en.eq(self.r.ready),
        ]

        return m
