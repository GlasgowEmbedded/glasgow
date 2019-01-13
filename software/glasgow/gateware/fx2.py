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
from migen.genlib.cdc import MultiReg
from migen.genlib.fifo import _FIFOInterface, AsyncFIFO, SyncFIFO, SyncFIFOBuffered
from migen.genlib.resetsync import AsyncResetSynchronizer


__all__ = ["FX2Arbiter"]


class _DummyFIFO(Module, _FIFOInterface):
    def __init__(self, width):
        super().__init__(width, 0)

        self.submodules.fifo = _FIFOInterface(width, 0)


class _FIFOWithOverflow(Module, _FIFOInterface):
    def __init__(self, fifo, overflow_depth=2):
        _FIFOInterface.__init__(self, fifo.width, fifo.depth)

        self.submodules.fifo     = fifo
        self.submodules.overflow = overflow = SyncFIFO(fifo.width, overflow_depth)

        self.dout     = fifo.dout
        self.re       = fifo.re
        self.readable = fifo.readable

        ###

        self.comb += [
            If(overflow.readable,
                fifo.din.eq(overflow.dout),
                fifo.we.eq(1),
                overflow.re.eq(fifo.writable)
            ),
            If(fifo.writable & ~overflow.readable,
                fifo.din.eq(self.din),
                fifo.we.eq(self.we),
                self.writable.eq(fifo.writable)
            ).Else(
                overflow.din.eq(self.din),
                overflow.we.eq(self.we),
                self.writable.eq(overflow.writable)
            )
        ]


class _FIFOWithFlush(Module, _FIFOInterface):
    def __init__(self, fifo, asynchronous=False, auto_flush=True):
        _FIFOInterface.__init__(self, fifo.width, fifo.depth)

        self.submodules.fifo = fifo

        self.dout     = fifo.dout
        self.re       = fifo.re
        self.readable = fifo.readable
        self.din      = fifo.din
        self.we       = fifo.we
        self.writable = fifo.writable

        self.flush    = Signal(reset=auto_flush)
        if asynchronous:
            self._flush_s  = Signal()
            self.specials += MultiReg(self.flush, self._flush_s, reset=auto_flush)
        else:
            self._flush_s  = self.flush

        self.flushed  = Signal()
        self.queued   = Signal()
        self._pending = Signal()
        self.sync += [
            If(self.flushed,
                self._pending.eq(0)
            ).Elif(self.readable & self.re,
                self._pending.eq(1)
            ),
            self.queued.eq(self._flush_s & self._pending)
        ]


class _RegisteredTristate(Module):
    def __init__(self, io):

        self.oe = Signal()
        self.o  = Signal.like(io)
        self.i  = Signal.like(io)

        def get_bit(signal, bit):
            return signal[bit] if signal.nbits > 0 else signal

        for bit in range(io.nbits):
            self.specials += \
                Instance("SB_IO",
                    # PIN_INPUT_REGISTERED|PIN_OUTPUT_REGISTERED_ENABLE_REGISTERED
                    p_PIN_TYPE=C(0b110100, 6),
                    io_PACKAGE_PIN=get_bit(io, bit),
                    i_OUTPUT_ENABLE=self.oe,
                    i_INPUT_CLK=ClockSignal(),
                    i_OUTPUT_CLK=ClockSignal(),
                    i_D_OUT_0=get_bit(self.o, bit),
                    # The FX2 output valid window starts well after (5.4 ns past) the iCE40 input
                    # capture window for the rising edge. However, the input capture for
                    # the falling edge is just right.
                    # See https://github.com/whitequark/Glasgow/issues/89 for details.
                    o_D_IN_1=get_bit(self.i, bit),
                )


class _FX2Bus(Module):
    def __init__(self, pads):
        self.submodules.fifoadr_t = _RegisteredTristate(pads.fifoadr)
        self.submodules.flag_t    = _RegisteredTristate(pads.flag)
        self.submodules.fd_t      = _RegisteredTristate(pads.fd)
        self.submodules.sloe_t    = _RegisteredTristate(pads.sloe)
        self.submodules.slrd_t    = _RegisteredTristate(pads.slrd)
        self.submodules.slwr_t    = _RegisteredTristate(pads.slwr)
        self.submodules.pktend_t  = _RegisteredTristate(pads.pktend)


class FX2Arbiter(Module):
    """
    FX2 FIFO bus master.

    Shuttles data between FX2 and FIFOs in bursts.

    The arbiter supports up to four FIFOs organized as ``OUT, OUT, IN, IN``.
    FIFOs that are never requested are not implemented and behave as if they
    are never readable or writable.
    """
    def __init__(self, pads):
        self.submodules.bus = _FX2Bus(pads)

        self.out_fifos = Array([_FIFOWithOverflow(_DummyFIFO(width=8))
                                for _ in range(2)])
        self. in_fifos = Array([_FIFOWithFlush(_DummyFIFO(width=8))
                                for _ in range(2)])

    def do_finalize(self):
        bus  = self.bus
        flag = Signal(4)
        addr = Signal(2)
        data = TSTriple(8)
        fdoe = Signal()
        sloe = Signal()
        slrd = Signal()
        slwr = Signal()
        pend = Signal()
        rdy  = Signal(4)
        self.comb += [
            bus.fifoadr_t.oe.eq(1),
            bus.fifoadr_t.o.eq(addr),
            flag.eq(bus.flag_t.i),
            rdy.eq(Cat([fifo.fifo.writable          for fifo in self.out_fifos] +
                       [fifo.readable | fifo.queued for fifo in self. in_fifos]) &
                   flag),
            self.out_fifos[addr[0]].din.eq(bus.fd_t.i),
            self.in_fifos[addr[0]].flushed.eq(pend),
            bus.fd_t.o.eq(self.in_fifos[addr[0]].dout),
            bus.fd_t.oe.eq(fdoe),
            bus.sloe_t.oe.eq(1),
            bus.sloe_t.o.eq(~sloe),
            bus.slrd_t.oe.eq(1),
            bus.slrd_t.o.eq(~slrd),
            bus.slwr_t.oe.eq(1),
            bus.slwr_t.o.eq(~slwr),
            bus.pktend_t.oe.eq(1),
            bus.pktend_t.o.eq(~pend),
        ]

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
            NextValue(sloe, 0),
            NextValue(fdoe, 0),
            NextValue(addr, naddr),
            If(rdy,
                NextState("DRIVE")
            )
        )
        self.fsm.act("DRIVE",
            If(addr[1],
                NextValue(fdoe, 1),
            ).Else(
                NextValue(sloe, 1),
            ),
            NextState("SETUP")
        )
        self.fsm.act("SETUP",
            If(addr[1],
                NextState("SETUP-IN")
            ).Else(
                NextState("SETUP-OUT")
            )
        )
        self.fsm.act("SETUP-IN",
            NextState("XFER-IN")
        )
        self.fsm.act("XFER-IN",
            If(flag.part(addr, 1) & self.in_fifos[addr[0]].readable,
                self.in_fifos[addr[0]].re.eq(1),
                slwr.eq(1)
            ).Elif(~flag.part(addr, 1) & ~self.in_fifos[addr[0]].readable,
                # The ~FULL flag went down, and it goes down one sample earlier than the actual
                # FULL condition. So we have one more byte free. However, the FPGA-side FIFO
                # became empty simultaneously.
                #
                # If we schedule the next FIFO right now, the ~FULL flag will never come back down,
                # so disregard the fact that the FIFO is streaming just for this corner case,
                # and commit a packet one byte shorter than the complete FIFO.
                #
                # This shouldn't cause any problems.
                NextState("PKTEND-IN")
            ).Elif(flag.part(addr, 1) & self.in_fifos[addr[0]].queued,
                # The FX2-side FIFO is not full yet, but the flush flag is asserted.
                # Commit the short packet.
                NextState("PKTEND-IN")
            ).Else(
                # Either the FPGA-side FIFO is empty, or the FX2-side FIFO is full, or the flush
                # flag is not asserted.
                # FX2 automatically commits a full FIFO, so we don't need to do anything here.
                NextState("NEXT")
            )
        )
        self.fsm.act("PKTEND-IN",
            # See datasheet "Slave FIFO Synchronous Packet End Strobe Parameters" for
            # an explanation of why this is asserted one cycle after the last SLWR pulse.
            pend.eq(1),
            NextState("NEXT")
        )
        self.fsm.act("SETUP-OUT",
            slrd.eq(1),
            NextState("XFER-OUT")
        )
        self.fsm.act("XFER-OUT",
            self.out_fifos[addr[0]].we.eq(flag.part(addr, 1)),
            If(rdy.part(addr, 1),
                slrd.eq(self.out_fifos[addr[0]].fifo.writable),
            ).Else(
                NextState("NEXT")
            )
        )

    def _make_fifo(self, arbiter_side, logic_side, cd_logic, reset, depth, wrapper):
        if cd_logic is None:
            fifo = wrapper(SyncFIFOBuffered(8, depth))

            if reset is not None:
                fifo = ResetInserter()(fifo)
                fifo.comb += fifo.reset.eq(reset)
        else:
            assert isinstance(cd_logic, ClockDomain)

            fifo = wrapper(ClockDomainsRenamer({
                arbiter_side: "arbiter",
                logic_side:   "logic",
            })(AsyncFIFO(8, depth)))

            # Note that for the reset to get asserted AND deasserted, the logic clock domain must
            # have a running clock. This is because, while AsyncResetSynchronizer is indeed
            # asynchronous, the registers in the FIFO logic clock domain reset synchronous
            # to the logic clock, as this is how Migen handles clock domain reset signals.
            #
            # If the logic clock domain does not have a single clock transition between assertion
            # and deassertion of FIFO reset, and the FIFO has not been empty at the time when
            # reset has been asserted, stale data will be read from the FIFO after deassertion.
            #
            # This can lead to all sorts of framing issues, and is rather unfortunate, but at
            # the moment I do not know of a way to fix this, since Migen does not support
            # asynchronous resets.
            fifo.clock_domains.cd_arbiter = ClockDomain(reset_less=reset is None)
            fifo.clock_domains.cd_logic   = ClockDomain(reset_less=reset is None)
            fifo.comb += [
                fifo.cd_arbiter.clk.eq(ClockSignal()),
                fifo.cd_logic.clk.eq(cd_logic.clk),
            ]
            if reset is not None:
                fifo.comb += fifo.cd_arbiter.rst.eq(reset)
                fifo.specials += AsyncResetSynchronizer(fifo.cd_logic, reset)

        self.submodules += fifo
        return fifo

    def get_out_fifo(self, n, depth=512, clock_domain=None, reset=None):
        assert 0 <= n < 2
        assert isinstance(self.out_fifos[n].fifo, _DummyFIFO)

        fifo = self._make_fifo(arbiter_side="write",
                               logic_side="read",
                               cd_logic=clock_domain,
                               reset=reset,
                               depth=depth,
                               wrapper=lambda x: _FIFOWithOverflow(x))
        self.out_fifos[n] = fifo
        return fifo

    def get_in_fifo(self, n, depth=512, auto_flush=True, clock_domain=None, reset=None):
        assert 0 <= n < 2
        assert isinstance(self.in_fifos[n].fifo, _DummyFIFO)

        fifo = self._make_fifo(arbiter_side="read",
                               logic_side="write",
                               cd_logic=clock_domain,
                               reset=reset,
                               depth=depth,
                               wrapper=lambda x: _FIFOWithFlush(x,
                                    asynchronous=clock_domain is not None,
                                    auto_flush=auto_flush))
        self.in_fifos[n] = fifo
        return fifo
