import asyncio
from migen import *

from .. import AccessDemultiplexer, AccessDemultiplexerInterface


class SimulationDemultiplexer(AccessDemultiplexer):
    def claim_interface(self, applet, mux_interface, args, timeout=None, async=False):
        return SimulationDemultiplexerInterface(self.device, applet, mux_interface, timeout, async)


class SimulationDemultiplexerInterface(AccessDemultiplexerInterface):
    def __init__(self, device, applet, mux_interface, timeout, async):
        super().__init__(device, applet)

        self._mux = mux_interface
        self.in_fifo  = mux_interface.in_fifo
        self.out_fifo = mux_interface.out_fifo

    def has_buffered_data(self):
        return False

    @asyncio.coroutine
    def read(self, length):
        data = []
        if length is None:
            while (yield self.in_fifo.readable):
                data.append((yield from self.in_fifo.read()))
        else:
            while len(data) < length:
                while not (yield self.in_fifo.readable):
                    yield
                data.append((yield from self.in_fifo.read()))

        data = bytes(data)
        self.logger.trace("FIFO: read <%s>", data.hex())
        return data

    @asyncio.coroutine
    def write(self, data):
        data = bytes(data)
        self.logger.trace("FIFO: write <%s>", data.hex())

        for byte in data:
            while not (yield self.out_fifo.writable):
                yield
            yield from self.out_fifo.write(byte)

    def flush(self):
        pass
