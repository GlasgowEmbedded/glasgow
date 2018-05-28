# Synchronous FIFO timings reference:
# http://www.cypress.com/file/138911/download#page=53

# All timings in ns referenced to positive edge of non-inverted IFCLK.
# "Int" means IFCLK sourced by FX2, "Ext" means IFCLK sourced by FPGA.
#
#                       Int Period  Ext Period
# IFCLK                 >20.83      >20.83 <200
# IFCLK (48 MHz)                20.83
# IFCLK (30 MHz)                33.33
#
#                       Int S/H     Ext S/H
# SLRD                  18.7/0.0    12.7/3.7
# SLWR                  10.4/0.0    12.1/3.6
# PKTEND                14.6/0.0    8.6/2.5
# FIFOADR                     25.0/10.0
# FIFODATA              9.2/0.0     3.2/4.5
#
#                       Int Setup   Ext Setup
# IFCLK->FLAG           9.5         13.5
# IFCLK->FIFODATA       11.0        15.0
# SLOE->FIFODATA                10.5
# FIFOADR->FLAG                 10.7
# FIFOADR->FIFODATA             14.3

from migen import *
from migen.genlib.fsm import *
from migen.genlib.fifo import _FIFOInterface, AsyncFIFO, SyncFIFOBuffered


__all__ = ['FX2Arbiter']


class _DummyFIFO(Module, _FIFOInterface):
    pass


class FX2Arbiter(Module):
    """
    FX2 FIFO bus master.

    Shuttles data between FX2 and FIFOs in bursts.

    The arbiter supports up to four FIFOs organized as ``OUT, OUT, IN, IN``.
    FIFOs that are never requested are not implemented and behave as if they
    are never readable or writable.
    """
    def __init__(self, fx2):
        self.fx2 = fx2

        self.out_fifos = Array([_DummyFIFO(width=8, depth=0) for _ in range(2)])
        self. in_fifos = Array([_DummyFIFO(width=8, depth=0) for _ in range(2)])
        self.early_in  = Array([True for _ in range(2)])

    def do_finalize(self):
        fx2  = self.fx2
        addr = Signal(2)
        data = TSTriple(8)
        sloe = Signal()
        slrd = Signal()
        slwr = Signal()
        pend = Signal()
        rdy  = Signal(4)
        self.comb += [
            fx2.fifoadr.eq(addr),
            rdy.eq(fx2.flag & Cat([fifo.writable for fifo in self.out_fifos] +
                                  [fifo.readable for fifo in self.in_fifos])),
            self.out_fifos[addr[0]].din.eq(data.i),
            data.o.eq(self.in_fifos[addr[0]].dout),
            fx2.sloe.eq(~sloe),
            fx2.slrd.eq(~slrd),
            fx2.slwr.eq(~slwr),
            fx2.pktend.eq(~pend),
        ]
        self.specials += \
            data.get_tristate(fx2.fd)

        # Calculate the address of the next ready FIFO in a round robin process.
        naddr = Signal(2)
        naddr_c = {}
        for addr_v in range(2**addr.nbits):
            for rdy_v in range(2**rdy.nbits):
                for offset in range(2**addr.nbits):
                    naddr_v = (addr_v + offset) % 2**addr.nbits
                    if rdy_v & (1 << naddr_v):
                        break
                else:
                    naddr_v = (addr_v + 1) % 2**addr.nbits
                naddr_c[rdy_v|(addr_v<<rdy.nbits)] = naddr.eq(naddr_v)
        self.comb += Case(Cat(rdy, addr), naddr_c)

        self.submodules.fsm = FSM(reset_state="NEXT")
        # SLOE to FIFODATA setup: 1 cycle
        # FIFOADR to FIFODATA setup: 2 cycles
        self.fsm.act("NEXT",
            NextValue(addr, naddr),
            If(rdy,
                NextState("SETUP")
            )
        )
        self.fsm.act("SETUP",
            If(addr[1],
                NextValue(sloe, 0),
                NextState("SETUP-IN")
            ).Else(
                NextValue(data.oe, 0),
                NextState("SETUP-OUT")
            )
        )
        self.fsm.act("SETUP-IN",
            NextValue(data.oe, 1),
            NextState("XFER-IN")
        )
        self.fsm.act("SETUP-OUT",
            NextValue(sloe, 1),
            NextState("XFER-OUT")
        )
        self.fsm.act("XFER-IN",
            If(rdy & (1 << addr),
                slwr.eq(1),
                self.in_fifos[addr[0]].re.eq(1)
            ).Else(
                pend.eq(self.early_in[addr[0]]),
                NextState("NEXT")
            )
        )
        self.fsm.act("XFER-OUT",
            If(rdy & (1 << addr),
                slrd.eq(1),
                self.out_fifos[addr[0]].we.eq(1)
            ).Else(
                NextState("NEXT")
            )
        )

    def _make_fifo(self, arbiter_side, logic_side, cd_logic, depth):
        if cd_logic is None:
            fifo = SyncFIFOBuffered(8, depth)
        else:
            assert isinstance(cd_logic, ClockDomain)

            fifo = ClockDomainsRenamer({
                arbiter_side: "sys",
                logic_side:   "logic",
            })(AsyncFIFO(8, depth))

            fifo.clock_domains.cd_logic = ClockDomain()
            self.comb += fifo.cd_logic.clk.eq(cd_logic.clk)
            if cd_logic.rst is not None:
                self.comb += fifo.cd_logic.rst.eq(cd_logic.rst)

        self.submodules += fifo
        return fifo

    def get_out_fifo(self, n, depth=512, clock_domain=None):
        assert 0 <= n < 2
        assert isinstance(self.out_fifos[n], _DummyFIFO)

        fifo = self._make_fifo(arbiter_side="write", logic_side="read",
                               cd_logic=clock_domain, depth=depth)
        self.out_fifos[n] = fifo
        return fifo

    def get_in_fifo(self, n, depth=512, early_in=True, clock_domain=None):
        assert 0 <= n < 2
        assert isinstance(self.in_fifos[n], _DummyFIFO)

        fifo = self._make_fifo(arbiter_side="read", logic_side="write",
                               cd_logic=clock_domain, depth=depth)
        self.in_fifos[n] = fifo
        self.early_in[n] = early_in
        return fifo
