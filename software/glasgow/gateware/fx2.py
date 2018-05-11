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
from migen.genlib.fifo import _FIFOInterface, AsyncFIFO, SyncFIFO


__all__ = ['FX2Arbiter']


class _DummyFIFO(Module, _FIFOInterface):
    pass


class FX2Arbiter(Module):
    """
    FX2 FIFO bus master.

    Shuttles data between FX2 and FIFOs in bursts.

    Parameters
    ----------
    out_count, in_count : int
        Amount of implemented OUT and IN FIFOs respectively.
        Unimplemented FIFOs are present but never readable or writable.
    depth : int
        FIFO depth. For highest efficiency, should be a multiple of 512.
    """
    def __init__(self, fx2, out_count=2, in_count=2, depth=512, async=False):
        assert 0 <= out_count <= 2 and 0 <= in_count <= 2

        def make_fifo(is_dummy):
            if is_dummy:
                return _DummyFIFO(8, depth)
            elif async:
                return AsyncFIFO(8, depth)
            else:
                # Do not use FWFT to improve timings.
                return SyncFIFO(8, depth, fwft=False)

        self.out_fifos = Array()
        self. in_fifos = Array()
        fifo_rdys = Array()

        for n in range(2):
            fifo = make_fifo(is_dummy=n > out_count)
            self.out_fifos.append(fifo)
            self.submodules += fifo
            fifo_rdys.append(fifo.writable)

        for n in range(2):
            fifo = make_fifo(is_dummy=n >  in_count)
            self. in_fifos.append(fifo)
            self.submodules += fifo
            fifo_rdys.append(fifo.readable)

        ###

        addr = Signal(2)
        data = TSTriple(8)
        sloe = Signal()
        slrd = Signal()
        slwr = Signal()
        pend = Signal()
        rdy  = Signal(4)
        self.comb += [
            fx2.fifoadr.eq(addr),
            rdy.eq(fx2.flag & Cat(fifo_rdys)),
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
            # 1-cycle latency between re and dout valid
            self.in_fifos[addr[0]].re.eq(1),
            NextValue(slwr, 1),
            NextValue(data.oe, 1),
            NextState("XFER-IN")
        )
        self.fsm.act("SETUP-OUT",
            NextValue(slrd, 1),
            NextValue(sloe, 1),
            NextState("XFER-OUT")
        )
        self.fsm.act("XFER-IN",
            If(rdy & (1 << addr),
                self.in_fifos[addr[0]].re.eq(1)
            ).Else(
                pend.eq(1),
                NextValue(slwr, 0),
                NextState("NEXT")
            )
        )
        self.fsm.act("XFER-OUT",
            If(rdy & (1 << addr),
                self.out_fifos[addr[0]].we.eq(1)
            ).Else(
                NextValue(slrd, 0),
                NextState("NEXT")
            )
        )

    def get_out(self, n):
        return self.out_fifos[n]

    def get_in(self, n):
        return self.in_fifos[n]

    def get_port(self, n):
        return (self.in_fifos[n], self.out_fifos[n])
