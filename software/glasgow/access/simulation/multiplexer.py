from amaranth import *
from amaranth.lib.fifo import FIFOInterface, AsyncFIFO, SyncFIFOBuffered

from .. import AccessMultiplexer, AccessMultiplexerInterface


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

        iface = SimulationMultiplexerInterface(applet)
        self._ifaces.append(iface)
        return iface


class _AsyncFIFOWrapper(Elaboratable, FIFOInterface):
    def __init__(self, inner, cd_logic):
        super().__init__(width=inner.width, depth=inner.depth)

        self.inner = inner
        self.cd_logic = cd_logic

        self.r_data   = inner.r_data
        self.r_en     = inner.r_en
        self.r_rdy    = inner.r_rdy
        self.w_data   = inner.w_data
        self.w_en     = inner.w_en
        self.w_rdy    = inner.w_rdy

    def elaborate(self, platform):
        m = Module()

        m.submodules.inner = self.inner

        cd_logic = ClockDomain(reset_less=self.reset is None, local=True)
        m.d.comb += cd_logic.clk.eq(self.cd_logic.clk),
        if self.cd_logic.rst is not None:
            m.d.comb += cd_logic.rst.eq(self.cd_logic.rst),

        m.domains.logic = cd_logic

        return m


class SimulationMultiplexerInterface(AccessMultiplexerInterface):
    def __init__(self, applet):
        super().__init__(applet, analyzer=None)

        self.in_fifo  = None
        self.out_fifo = None
        self._subtargets = []

    def elaborate(self, platform):
        m = Module()

        m.submodules += self._subtargets
        if self.pads is not None:
            m.submodules.pads = self.pads
        if self.in_fifo is not None:
            m.submodules.in_fifo = self.in_fifo
        if self.out_fifo is not None:
            m.submodules.out_fifo = self.out_fifo

        return m

    def get_pin_name(self, pin):
        return str(pin)

    def build_pin_tristate(self, pin, oe, o, i):
        pass

    def _make_fifo(self, crossbar_side, logic_side, cd_logic, depth, wrapper=lambda x: x):
        if cd_logic is None:
            fifo = wrapper(SyncFIFOBuffered(width=8, depth=depth))
        else:
            assert isinstance(cd_logic, ClockDomain)

            raw_fifo = DomainRenamer({
                crossbar_side: "sync",
                logic_side:    "logic",
            })(AsyncFIFO(width=8, depth=depth))
            fifo = wrapper(_AsyncFIFOWrapper(raw_fifo, cd_logic))

        return fifo

    def get_in_fifo(self, depth=512, auto_flush=True, clock_domain=None):
        assert self.in_fifo is None

        self.in_fifo = self._make_fifo(
            crossbar_side="read", logic_side="write", cd_logic=clock_domain, depth=depth)
        self.in_fifo.flush = Signal(reset=auto_flush)
        return self.in_fifo

    def get_out_fifo(self, depth=512, clock_domain=None):
        assert self.out_fifo is None

        self.out_fifo = self._make_fifo(
            crossbar_side="write", logic_side="read", cd_logic=clock_domain, depth=depth)
        return self.out_fifo

    def get_inout_fifo(self, **kwargs):
        return self.get_in_fifo(**kwargs), self.get_out_fifo(**kwargs)

    def add_subtarget(self, subtarget):
        self._subtargets.append(subtarget)
        return subtarget
