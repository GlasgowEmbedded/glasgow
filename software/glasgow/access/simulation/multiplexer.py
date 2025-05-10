from amaranth import *
from amaranth.lib import io

from ...gateware.stream import StreamFIFO
from .. import AccessMultiplexer, AccessMultiplexerInterface


class _FIFOReadPort:
    def __init__(self, fifo):
        self.stream = fifo.r
        self.r_data = fifo.r.payload
        self.r_rdy  = fifo.r.valid
        self.r_en   = fifo.r.ready


class _FIFOWritePort:
    def __init__(self, fifo, auto_flush):
        self.stream = fifo.w
        self.w_data = fifo.w.payload
        self.w_en   = fifo.w.valid
        self.w_rdy  = fifo.w.ready
        self.flush  = Signal(init=auto_flush)


class SimulationMultiplexer(AccessMultiplexer):
    def __init__(self):
        self._ifaces = []

    def elaborate(self, platform):
        m = Module()
        m.submodules += self._ifaces
        return m

    def set_analyzer(self, analyzer):
        assert False

    def claim_interface(self, applet, args, with_analyzer=False):
        assert not with_analyzer

        self._ifaces.append(iface := SimulationMultiplexerInterface(applet))
        return iface


class SimulationMultiplexerInterface(AccessMultiplexerInterface):
    def __init__(self, applet):
        super().__init__(applet, analyzer=None)

        self.in_fifo   = None
        self.out_fifo  = None
        self.subtarget = None

    def elaborate(self, platform):
        m = Module()

        m.submodules.subtarget = self.subtarget
        if self.in_fifo is not None:
            m.submodules.in_fifo = self.in_fifo
        if self.out_fifo is not None:
            m.submodules.out_fifo = self.out_fifo

        return m

    def get_pin_name(self, pin):
        return str(pin)

    def get_port_impl(self, pin, *, name):
        return io.SimulationPort("io", 1, name=name)

    def get_in_fifo(self, depth=512, auto_flush=True):
        assert self.in_fifo is None

        self.in_fifo = StreamFIFO(shape=8, depth=depth)
        return _FIFOWritePort(self.in_fifo, auto_flush)

    def get_out_fifo(self, depth=512):
        assert self.out_fifo is None

        self.out_fifo = StreamFIFO(shape=8, depth=depth)
        return _FIFOReadPort(self.out_fifo)

    def add_subtarget(self, subtarget):
        assert self.subtarget is None

        self.subtarget = subtarget
        return subtarget
