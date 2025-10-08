from amaranth import *
from amaranth.lib import wiring, stream, fifo
from amaranth.lib.wiring import In, Out


__all__ = [
    "stream_put", "stream_get", "stream_assert"
    "StreamBuffer", "Queue", "AsyncQueue", "SkidBuffer",
]


async def stream_put(ctx, stream, payload):
    ctx.set(stream.payload, payload)
    ctx.set(stream.valid, 1)
    await ctx.tick().until(stream.ready)
    ctx.set(stream.valid, 0)


async def stream_get(ctx, stream):
    ctx.set(stream.ready, 1)
    payload, = await ctx.tick().sample(stream.payload).until(stream.valid)
    ctx.set(stream.ready, 0)
    return payload


async def stream_get_maybe(ctx, stream):
    ctx.set(stream.ready, 1)
    _, _, payload, stream_valid = await ctx.tick().sample(stream.payload, stream.valid)
    ctx.set(stream.ready, 0)
    if stream_valid:
        return payload
    else:
        return None


async def stream_assert(ctx, stream, expected):
    value = await stream_get(ctx, stream)
    for key, expected_value in expected.items():
        assert value[key] == expected_value, \
            f"payload.{key}: {value[key]!r} != {expected_value!r}"


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


class Queue(wiring.Component):
    def __init__(self, *, shape, depth, buffered=True):
        self._shape = shape
        self._depth = depth
        self._buffered = buffered

        super().__init__({
            "i": In(stream.Signature(shape)),
            "o": Out(stream.Signature(shape)),
            "level": Out(range(depth + 1))
        })

    def elaborate(self, platform):
        m = Module()

        fifo_cls = fifo.SyncFIFOBuffered if self._buffered else fifo.SyncFIFO
        m.submodules.inner = inner = fifo_cls(
            width=Shape.cast(self._shape).width,
            depth=self._depth
        )
        m.d.comb += [
            inner.w_data.eq(self.i.payload),
            inner.w_en.eq(self.i.valid),
            self.i.ready.eq(inner.w_rdy),
            self.o.payload.eq(inner.r_data),
            self.o.valid.eq(inner.r_rdy),
            inner.r_en.eq(self.o.ready),
            self.level.eq(inner.level),
        ]

        return m


class AsyncQueue(wiring.Component):
    def __init__(self, *, shape, depth, i_domain="sync", o_domain="sync"):
        self._shape = shape
        self._depth = depth
        self._i_domain = i_domain
        self._o_domain = o_domain

        super().__init__({
            "i": In(stream.Signature(shape)),
            "o": Out(stream.Signature(shape)),
        })

    def elaborate(self, platform):
        m = Module()

        m.submodules.inner = inner = fifo.AsyncFIFO(
            width=Shape.cast(self._shape).width,
            depth=self._depth,
            w_domain=self._i_domain,
            r_domain=self._o_domain,
        )
        m.d.comb += [
            inner.w_data.eq(self.i.payload),
            inner.w_en.eq(self.i.valid),
            self.i.ready.eq(inner.w_rdy),
            self.o.payload.eq(inner.r_data),
            self.o.valid.eq(inner.r_rdy),
            inner.r_en.eq(self.o.ready),
        ]

        return m


class SkidBuffer(wiring.Component):
    def __init__(self, shape, depth):
        self._shape = shape
        self._depth = depth

        super().__init__({
            "i": In(stream.Signature(shape)),
            "o": Out(stream.Signature(shape)),
        })

    def elaborate(self, platform):
        m = Module()

        m.submodules.skid = skid = Queue(shape=self._shape, depth=self._depth, buffered=False)

        m.d.comb += skid.i.payload.eq(self.i.payload)
        m.d.comb += skid.i.valid.eq(self.i.valid & (~self.o.ready | skid.o.valid))
        with m.If(skid.o.valid):
            wiring.connect(m, wiring.flipped(self.o), skid.o)
        with m.Else():
            wiring.connect(m, wiring.flipped(self.o), wiring.flipped(self.i))

        return m
