import types
from amaranth import *

from ...support.logging import *
from .. import AccessDemultiplexer, AccessDemultiplexerInterface


class SimulationDemultiplexer(AccessDemultiplexer):
    async def claim_interface(self, applet, mux_interface, args, pull_low=set(), pull_high=set()):
        return SimulationDemultiplexerInterface(self.device, applet, mux_interface)


@types.coroutine
def _fifo_read(fifo):
    assert (yield fifo.r.valid)
    value = (yield fifo.r.payload)
    yield fifo.r.ready.eq(1)
    yield
    yield fifo.r.ready.eq(0)
    yield
    return value


@types.coroutine
def _fifo_write(fifo, data):
    assert (yield fifo.w.ready)
    yield fifo.w.payload.eq(data)
    yield fifo.w.valid.eq(1)
    yield
    yield fifo.w.valid.eq(0)
    yield


class SimulationDemultiplexerInterface(AccessDemultiplexerInterface):
    def __init__(self, device, applet, mux_interface):
        super().__init__(device, applet)

        self._in_fifo  = mux_interface.in_fifo
        self._out_fifo = mux_interface.out_fifo

    async def cancel(self):
        pass

    async def reset(self):
        pass

    @types.coroutine
    def read(self, length=None):
        data = []
        if length is None:
            while (yield self._in_fifo.r.valid):
                data.append((yield from _fifo_read(self._in_fifo)))
        else:
            while len(data) < length:
                self.logger.trace("FIFO: need %d bytes", length - len(data))
                while not (yield self._in_fifo.r.valid):
                    yield
                data.append((yield from _fifo_read(self._in_fifo)))

        data = bytes(data)
        self.logger.trace("FIFO: read <%s>", dump_hex(data))
        return data

    @types.coroutine
    def write(self, data):
        data = bytes(data)
        self.logger.trace("FIFO: write <%s>", dump_hex(data))

        for byte in data:
            while not (yield self._out_fifo.w.ready):
                yield
            yield from _fifo_write(self._out_fifo, byte)

    async def flush(self):
        pass
