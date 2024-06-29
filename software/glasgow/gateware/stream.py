from amaranth import *
from amaranth.lib import wiring, stream, fifo
from amaranth.lib.wiring import In, Out


class Queue(wiring.Component):
    def __init__(self, shape, *, depth):
        self._shape = shape
        self._depth = depth

        super().__init__({
            "write": In(stream.Signature(shape)),
            "read": Out(stream.Signature(shape)),
        })

    @property
    def w(self):
        return self.write

    @property
    def r(self):
        return self.read

    def elaborate(self, platform):
        m = Module()

        m.submodules.fifo = inner = fifo.SyncFIFOBuffered(
            width=Shape.cast(self._shape).width, depth=self._depth)
        wiring.connect(m, wiring.flipped(self.write), inner.w_stream)
        wiring.connect(m, wiring.flipped(self.read), inner.r_stream)

        return m


class AsyncQueue(wiring.Component):
    def __init__(self, shape, *, depth, w_domain="write", r_domain="read"):
        self._shape = shape
        self._depth = depth
        self._w_domain = w_domain
        self._r_domain = r_domain

        super().__init__({
            "write": In(stream.Signature(shape)),
            "read": Out(stream.Signature(shape)),
        })

    @property
    def w(self):
        return self.write

    @property
    def r(self):
        return self.read

    def elaborate(self, platform):
        m = Module()

        m.submodules.fifo = inner = fifo.AsyncFIFO(
            width=Shape.cast(self._shape).width, depth=self._depth,
            w_domain=self._w_domain, r_domain=self._r_domain)
        wiring.connect(m, wiring.flipped(self.write), inner.w_stream)
        wiring.connect(m, wiring.flipped(self.read), inner.r_stream)

        return m
