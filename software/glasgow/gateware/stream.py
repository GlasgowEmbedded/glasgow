from amaranth import *
from amaranth.lib import data, wiring, stream, fifo, memory
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


class PacketQueue(wiring.Component):
    """A packet queue with a discard function.

    A packet begins with an item that has ``first == 1``, and ends with an item that has
    ``last == 1`` (which may be the same item). Items that are pushed into queue since
    the beginning of a packet are not available until the end of the packet is also pushed.
    If, while a packet is being pushed into the queue, a new packet (indicated by an item
    with ``first == 1``) starts being pushed into the queue, the previous packet is discarded.
    """

    def __init__(self, data_shape, *, data_depth, size_depth):
        self._data_shape = data_shape
        self._data_depth = data_depth
        self._size_depth = size_depth

        super().__init__({
            "i": In(stream.Signature(data.StructLayout({
                "data":  data_shape,
                "first": 1,
                "last":  1,
            }))),
            "o": Out(stream.Signature(data.StructLayout({
                "data":  data_shape,
                "first": 1,
                "last":  1,
            }))),
        })

    def elaborate(self, platform):
        m = Module()

        def incr(addr, size):
            return Mux(addr == size - 1, 0, addr + 1)

        m.submodules.size_queue = size_queue = \
            Queue(shape=range(self._data_depth), depth=self._size_depth)
        m.submodules.data_memory = data_memory = \
            memory.Memory(shape=self._data_shape, depth=self._data_depth, init=[])
        data_write = data_memory.write_port()
        data_read  = data_memory.read_port(transparent_for=(data_write,))

        write_first = Signal(range(self._data_depth))
        write_count = Signal(range(self._data_depth))
        write_incr  = incr(data_write.addr, self._data_depth)

        m.d.comb += data_write.data.eq(self.i.p.data)
        m.d.comb += size_queue.i.payload.eq(write_count)
        with m.If(self.i.valid):
            with m.If(self.i.p.first & (write_count != 0)):
                m.d.sync += data_write.addr.eq(write_first)
                m.d.sync += write_count.eq(0)
            with m.Elif(~self.i.p.last | size_queue.i.ready):
                with m.If(write_incr != data_read.addr):
                    m.d.comb += self.i.ready.eq(1)
                    m.d.comb += data_write.en.eq(1)
                    with m.If(self.i.p.last):
                        m.d.comb += size_queue.i.valid.eq(1)
                        m.d.sync += write_first.eq(write_incr)
                        m.d.sync += data_write.addr.eq(write_incr)
                        m.d.sync += write_count.eq(0)
                    with m.Else():
                        m.d.sync += data_write.addr.eq(write_incr)
                        m.d.sync += write_count.eq(write_count + 1)

        read_addr  = Signal(range(self._data_depth))
        read_count = Signal(range(self._data_depth))
        read_incr  = incr(read_addr, self._data_depth)

        m.d.comb += self.o.p.data.eq(data_read.data)
        m.d.comb += self.o.p.first.eq(read_count == 0)
        m.d.comb += self.o.p.last.eq(read_count == size_queue.o.payload)
        m.d.comb += self.o.valid.eq(size_queue.o.valid)
        with m.If(self.o.valid & self.o.ready):
            with m.If(self.o.p.last):
                m.d.comb += size_queue.o.ready.eq(1)
                m.d.sync += read_count.eq(0)
            with m.Else():
                m.d.sync += read_count.eq(read_count + 1)
            m.d.sync += read_addr.eq(read_incr)
            m.d.comb += data_read.addr.eq(read_incr)
        with m.Else():
            m.d.comb += data_read.addr.eq(read_addr)

        return m
