from amaranth import *
from amaranth.lib import wiring, stream
from amaranth.lib.wiring import In, Out


__all__ = ["stream_get", "stream_put", "StreamBuffer"]


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
