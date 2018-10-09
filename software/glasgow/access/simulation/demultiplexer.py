import asyncio
from migen import *

from .. import AccessDemultiplexer, AccessDemultiplexerInterface


class SimulationDemultiplexer(AccessDemultiplexer):
    async def claim_interface(self, applet, mux_interface, args):
        return SimulationDemultiplexerInterface(self.device, applet, mux_interface)


class SimulationDemultiplexerInterface(AccessDemultiplexerInterface):
    def __init__(self, device, applet, mux_interface):
        super().__init__(device, applet)

        self._in_fifo  = mux_interface.in_fifo
        self._out_fifo = mux_interface.out_fifo

    @asyncio.coroutine
    def reset(self):
        pass

    @asyncio.coroutine
    def read(self, length=None):
        data = []
        if length is None:
            while (yield self._in_fifo.readable):
                data.append((yield from self._in_fifo.read()))
        else:
            while len(data) < length:
                self.logger.trace("FIFO: need %d bytes", length - len(data))
                while not (yield self._in_fifo.readable):
                    yield
                data.append((yield from self._in_fifo.read()))

        data = bytes(data)
        self.logger.trace("FIFO: read <%s>", data.hex())
        return data

    @asyncio.coroutine
    def write(self, data):
        data = bytes(data)
        self.logger.trace("FIFO: write <%s>", data.hex())

        for byte in data:
            while not (yield self._out_fifo.writable):
                yield
            yield from self._out_fifo.write(byte)

    @asyncio.coroutine
    def flush(self):
        pass
