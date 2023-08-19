# Overview
# --------
#
# The FX2 has four FIFOs, but only one at a time may be selected to be read (for OUT FIFOs) or
# written (for IN FIFOs). To achieve high transfer rates when more than one stream of data is used
# (bidirectional channel, two one-directional channels, and so on), the FPGA has its own FIFOs that
# mirror the FX2 FIFOs. The FX2 crossbar switch is the gateware that coordinates transfers between
# these FIFOs, up to eight total depending on application requirements.
#
# Timing issues
# -------------
#
# The FX2 can work in asynchronous or synchronous FIFO mode. The asynchronous mode is a bit of
# a relic; the maximum throughput is much lower as well, so it's not useful. The synchronous mode
# can source or accept a clock, and timings change based on this.
#
# Using fast parallel synchronous interfaces on an FPGA is a bit tricky. It is never safe to
# drive a bus with combinatorial logic directly, or drive combinatorial logic from a bus, because
# the timing relationship is neither defined (the inferred logic depth may vary, and placement
# further affects it) nor easily enforced (it's quite nontrivial to define the right timing
# constraints, if the toolchain allows it at all).
#
# The way to make things work is use a register placed inside the FPGA I/O buffer and clocked by
# a global clock network; this makes timings consistent regardless of inferred logic or placement,
# and the I/O buffer is qualified by only two main properties: clock-to-output delay, and input
# capture window. Unfortunately, this adds pipelining, which complicates feedback. For example, if
# the FPGA is asserting a write strobe and waiting for a full flag to go high, it will observe
# the flag as high one cycle late, by which point the FIFO has overflowed, and it would take
# another cycle for the write strobe to deassert; if the flag went high for just one cycle, then
# a spurious write will also happen after the overflow.
#
# Worse yet, the combination of the FX2 and iCE40 FPGA creates another hazard. The input capture
# window of the FPGA is long before the signals output by the FX2 are valid, and to counteract
# this, we have to add a delay--in practice this means using DDR inputs and capturing on negative
# clock edge. However, doing that alone would effectively halve our maximum frequency, so it's
# necessary to re-register the input in fabric. That adds another cycle of latency.
#
# The FX2 has a way to compensate for one cycle of latency, the INFM1 and OEP1 FIFO configuration
# bits. Unfortunately, this is not enough. Not only there are three cycles of latency total, but
# this feature does not help avoiding FIFO overflows at all. For IN FIFOs, if the full flag goes
# high one cycle before the full condition, and the FPGA-side FIFO is empty, the FX2-side FIFO
# looks full (so if the crossbar switches to a different FIFO, it wouldn't try to fill it again),
# but the packet in that FIFO is incomplete and not sent (so it'll never become non-full again).
# For OUT FIFOs, the empty flag and the data are aligned in time, but when the FPGA-side FIFO
# becomes full and the FPGA deasserts the read strobe, it's too late, as up to one more byte is
# already in the FPGA input register. Similarly, if the empty flag is asserted for just one cycle,
# and the crossbar switches to another FIFO pair, the tail end of the read strobe would cause
# a spurious read.
#
# Handling pipelining
# -------------------
#
# This unintentional pipelining is handled in two ways, different for IN and OUT FIFOs. The core
# of the difference is that the FPGA controls the FX2-side IN FIFO, but the host controls
# the OUT FIFO.
#
# For IN FIFOs, the solution is to track the FIFO level on the FPGA using a counter. This creates
# a "perfect" full flag on the FPGA, and simplifies other things as well, such as ZLP generation.
# (More on that later.)
#
# The host may explicitly purge the FX2-side FIFOs in some circumstances, e.g. changing the USB
# configuration or interface altsetting, which would require resetting the IN level counter, but
# this requires resetting the FPGA-side FIFO contents anyway, so it already has to be coordinated
# via some out-of-band mechanism.
#
# For OUT FIFOs, the solution is to use an skid buffer--a very small additional FIFO in front
# of the normal large FPGA-side FIFO to absorb any writes that may happen after the strobe was
# deasserted. (A naive approach would be to compare the FPGA-side FIFO level to get an "almost
# full" marker, but this does not work if that FIFO is used to bridge clock domains, and in any
# case it would result in more logic.)
#
# Moreover, for correct results, the FIFO address (the index of the FX2 FIFO in use) and read
# strobe must be synchronized to the data valid flag (i.e. inverse of empty flag) and the data;
# that is, the FIFO address and read strobe must be delayed by 3 cycles and used to select and
# enable writes to the FPGA-side FIFO. Essentially, the FPGA-side FIFO should be driven by
# the control signals as seen by the FX2, because only then the FX2 outputs are meaningful.
#
# Once the control signals that indicate FX2's state are appropriately received, generated or
# regenerated, the purpose of the rest of the crossbar is only to provide stimulus to the FX2,
# i.e. switch between addresses and generate read, write and packet end strobes.
#
# Handling packetization
# ----------------------
#
# There is one more concern that needs to be handled by the crossbar. The FIFOs provided on
# the FPGA are a byte-oriented abstraction; they have no inherent packet boundaries. However, USB
# is a packet-oriented bus. Therefore, for IN FIFOs, the crossbar has to insert packet boundaries,
# and because bulk endpoints place no particular requirements on when the host controller will poll
# them, the choices made during packetization have a major impact on performance. (For OUT FIFOs,
# the host inserts packet boundaries, and since no particular guarantees are provided by the FX2
# as to behavior of the empty flag between packets, it doesn't make sense to expose a packet-
# oriented interface to the rest of FPGA gateware, as it would be very asymmetric.)
#
# To provide control over IN packet boundaries, the crossbar uses a flush flag. If it has been
# asserted, and the FX2-side FIFO has an incomplete packet in it, and the FPGA-side FIFO is empty,
# the FX2 is instructed to send the incomplete packet as-is.
#
# To achieve the highest throughput, it is necessary to send long packets, since the FX2 only has
# up to 4 buffers per packet (in 2-endpoint mode; 2 buffers in 4-endpoint mode), and the longer
# the packets are, the higher is the FX2-side buffer utilization. However, this is only taking
# the FX2 and USB protocol into account. If we consider the host controller and OS as well, it
# becomes apparent that it is necessary to send maximum length packets.
#
# To understand the reason for this, consider that an application has to provide the OS with
# a buffer to fill with data read from the USB device. This buffer has to be a multiple of
# the maximum packet size; if more data is returned, the extra data is discarded and an error
# is indicated. However, what happens if less data is returned? In that case, the OS returns
# the buffer to the application immediately. This can dramatically reduce performance: if
# the application queues 10 8192-byte buffers, and the device returns 512 byte maximum-length
# packets, then 160 packets can be received. However, if the device returns 511 byte packets,
# then only 10 packets will be received!
#
# Unfortunately, if a device returns (for example) a single maximum-length packet and then stops,
# then the OS will hold onto the buffer, assuming that there is more data to come; this will appear
# as a hang. To indicate to the OS that there really is no more data, a zero-length packet needs
# to be generated. This is where the IN FIFO level counter comes in handy as well.
#
# Addendum: FX2 Synchronous FIFO timings summary
# ----------------------------------------------
#
# Based on: http://www.cypress.com/file/138911/download#page=53
#
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

from amaranth import *
from amaranth.lib.cdc import FFSynchronizer, ResetSynchronizer
from amaranth.lib.fifo import FIFOInterface, AsyncFIFO, SyncFIFO, SyncFIFOBuffered
from amaranth.lib.io import Pin


__all__ = ["FX2Crossbar"]


class _OUTFIFO(Elaboratable, FIFOInterface):
    """
    A FIFO with a skid buffer in front of it. This FIFO may be fed from a pipeline that
    reacts to the ``w_rdy`` flag with a latency up to the skid buffer depth, and writes
    will not be lost.
    """
    def __init__(self, inner, skid_depth):
        super().__init__(width=inner.width, depth=inner.depth, fwft=True)

        self.inner = inner
        self.skid  = skid  = SyncFIFO(width=inner.width, depth=skid_depth)

        self.r_data   = inner.r_data
        self.r_en     = inner.r_en
        self.r_rdy    = inner.r_rdy

    def elaborate(self, platform):
        m = Module()

        m.submodules.inner = inner = self.inner
        m.submodules.skid = skid = self.skid

        with m.If(skid.r_rdy):
            m.d.comb += [
                inner.w_data.eq(skid.r_data),
                inner.w_en.eq(1),
                skid.r_en.eq(inner.w_rdy)
            ]

        with m.If(inner.w_rdy & ~skid.r_rdy):
            m.d.comb += [
                inner.w_data.eq(self.w_data),
                inner.w_en.eq(self.w_en),
                self.w_rdy.eq(inner.w_rdy)
            ]
        with m.Else():
            m.d.comb += [
                skid.w_data.eq(self.w_data),
                skid.w_en.eq(self.w_en),
                self.w_rdy.eq(skid.w_rdy)
            ]

        return m


class _UnimplementedOUTFIFO(FIFOInterface):
    def __init__(self, width):
        super().__init__(width=width, depth=0, fwft=True)

        self.inner = FIFOInterface(width=width, depth=0, fwft=True)


class _INFIFO(Elaboratable, FIFOInterface):
    """
    A FIFO with a sideband flag indicating whether the FIFO has enough data to read from it yet.
    This FIFO may be used for packetizing the data read from the FIFO when there is no particular
    framing available to optimize the packet boundaries.
    """
    def __init__(self, inner, packet_size=512, asynchronous=False, auto_flush=True):
        super().__init__(width=inner.width, depth=inner.depth, fwft=True)

        self.inner = inner
        self.packet_size = packet_size
        self.asynchronous = asynchronous
        self.auto_flush = auto_flush

        self.r_data   = inner.r_data
        self.r_en     = inner.r_en
        self.r_rdy    = inner.r_rdy
        self.w_data   = inner.w_data
        self.w_en     = inner.w_en
        self.w_rdy    = inner.w_rdy

        self.flush = Signal(reset=auto_flush)

        # This is a model of the IN FIFO buffer in the FX2. Keep in mind that it is legal
        # to assert PKTEND together with SLWR, and in that case PKTEND takes priority.
        # This model is placed in the _INFIFO so that it is reset together with the FIFO itself,
        # which happens on Set Configuration and Set Interface requests.
        self.queued   = Signal(range(1 + packet_size))
        self.complete = Signal() # one FX2 FIFO buffer full
        self.pending  = Signal() # PKTEND requested
        self.flushed  = Signal() # PKTEND asserted

    def elaborate(self, platform):
        m = Module()

        m.submodules.inner = self.inner

        if self.asynchronous:
            _flush_s = Signal()
            m.submodules += FFSynchronizer(self.flush, _flush_s, reset=self.auto_flush)
        else:
            _flush_s = self.flush

        _pending = Signal()
        with m.If(self.flushed):
            m.d.sync += self.queued.eq(0)
            # If we sent a maximum-size packet, we still need a ZLP afterwards.
            with m.If(self.queued < self.packet_size):
                m.d.sync += _pending.eq(0)
        with m.Elif(self.r_rdy & self.r_en):
            m.d.sync += [
                self.queued.eq(self.queued + 1),
                _pending.eq(1)
            ]

        m.d.comb += [
            self.complete.eq(self.queued >= self.packet_size),
            self.pending.eq(_pending & _flush_s),
        ]

        return m


class _UnimplementedINFIFO(FIFOInterface):
    def __init__(self, width, packet_size=512):
        super().__init__(width=width, depth=0, fwft=True)

        self.inner = FIFOInterface(width=width, depth=0, fwft=True)

        self.flush    = Signal()
        self.flush_s  = Signal()

        self.queued   = Signal(range(1 + packet_size))
        self.complete = Signal()
        self.pending  = Signal()
        self.flushed  = Signal()


class _AsyncFIFOWrapper(Elaboratable, FIFOInterface):
    def __init__(self, inner, cd_logic, reset):
        super().__init__(width=inner.width, depth=inner.depth, fwft=True)

        self.inner = inner
        self.cd_logic = cd_logic
        self.reset = reset

        self.r_data   = inner.r_data
        self.r_en     = inner.r_en
        self.r_rdy    = inner.r_rdy
        self.w_data   = inner.w_data
        self.w_en     = inner.w_en
        self.w_rdy    = inner.w_rdy

    def elaborate(self, platform):
        m = Module()

        m.submodules.inner = self.inner

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
        cd_crossbar = ClockDomain(reset_less=self.reset is None, local=True)
        cd_logic    = ClockDomain(reset_less=self.reset is None, local=True)
        m.d.comb += [
            cd_crossbar.clk.eq(ClockSignal()),
            cd_logic.clk.eq(self.cd_logic.clk),
        ]
        if self.reset is not None:
            m.d.comb += cd_crossbar.rst.eq(self.reset)
            m.submodules += ResetSynchronizer(self.reset, domain="logic")

        m.domains.logic = cd_logic
        m.domains.crossbar = cd_crossbar

        return m


class _FX2Bus(Elaboratable):
    def __init__(self, pads):
        self.flag = Signal(4)
        self.addr = Signal(2)
        self.data = Pin(width=8, dir='io')
        self.sloe = Signal()
        self.slrd = Signal()
        self.slwr = Signal()
        self.pend = Signal()

        self.addr_p = Signal.like(self.addr)
        self.slrd_p = Signal.like(self.slrd)

        # When an operation is pipelined that may or may not change flags, it is useful to
        # invalidate--artificially negate--the corresponding flag until the operation completes.
        # The nrdy signals are delayed by _FX2Bus in the same way as other pipelined signals,
        # and an output bit is active while any corresponding bit in the pipeline is still active.
        self.nrdy_i = Signal.like(self.flag)
        self.nrdy_o = Signal.like(self.flag)

        self.pads = pads

    def elaborate(self, platform):
        m = Module()

        # The FX2 output valid window starts well after (5.4 ns past) the iCE40 input capture
        # window for the rising edge. However, the input capture for the falling edge is
        # just right.
        #
        # For input pins, we use DDR input to capture the FX2 output in the valid window, that is
        # on negedge of system clock. The output pins are SDR, although for bidirectional pins SDR
        # is emulated by using same data on both edges. (Amaranth does not allow different gearbox
        # ratio between input and output buffers.)
        #
        # See https://github.com/GlasgowEmbedded/Glasgow/issues/89 for details.
        m.d.comb += [
            self.pads.flag.i_clk.eq(ClockSignal()),
            self.flag.eq(self.pads.flag.i1),
            self.pads.fifoadr.o_clk.eq(ClockSignal()),
            self.pads.fifoadr.o.eq(self.addr),
            self.pads.fd.o_clk.eq(ClockSignal()),
            self.pads.fd.oe.eq(self.data.oe),
            self.pads.fd.o0.eq(self.data.o),
            self.pads.fd.o1.eq(self.data.o),
            self.pads.fd.i_clk.eq(ClockSignal()),
            self.data.i.eq(self.pads.fd.i1),
            self.pads.sloe.o_clk.eq(ClockSignal()),
            self.pads.sloe.o.eq(~self.sloe),
            self.pads.slrd.o_clk.eq(ClockSignal()),
            self.pads.slrd.o.eq(~self.slrd),
            self.pads.slwr.o_clk.eq(ClockSignal()),
            self.pads.slwr.o.eq(~self.slwr),
            self.pads.pktend.o_clk.eq(ClockSignal()),
            self.pads.pktend.o.eq(~self.pend),
        ]

        # Delay the FX2 bus control signals, taking into account the roundtrip latency.
        addr_r = Signal.like(self.addr)
        slrd_r = Signal.like(self.slrd)
        nrdy_r = Signal.like(self.flag)
        m.d.sync += [
            addr_r.eq(self.addr),
            self.addr_p.eq(addr_r),
            slrd_r.eq(self.slrd),
            self.slrd_p.eq(slrd_r),
            nrdy_r.eq(self.nrdy_i),
            self.nrdy_o.eq(nrdy_r | self.nrdy_i),
        ]

        return m


class FX2Crossbar(Elaboratable):
    """
    FX2 FIFO bus master.

    Shuttles data between FX2 and FIFOs in bursts.

    The crossbar supports up to four FIFOs organized as ``OUT, OUT, IN, IN``.
    FIFOs that are never requested are not implemented and behave as if they
    are never readable or writable.
    """
    def __init__(self, pads):
        self.bus = _FX2Bus(pads)

        self.out_fifos = Array([_UnimplementedOUTFIFO(width=8)
                                for _ in range(2)])
        self. in_fifos = Array([_UnimplementedINFIFO(width=8)
                                for _ in range(2)])


    def elaborate(self, platform):
        m = Module()

        m.submodules.bus = bus = self.bus

        for n, fifo in enumerate(self.in_fifos):
            if isinstance(fifo, Elaboratable):
                m.submodules[f"in_fifo_{n}"] = fifo
        for n, fifo in enumerate(self.out_fifos):
            if isinstance(fifo, Elaboratable):
                m.submodules[f"out_fifo_{n}"] = fifo

        rdy = Signal(4)
        m.d.comb += [
            rdy.eq(Cat([fifo.inner.w_rdy          for fifo in self.out_fifos] +
                       [fifo.r_rdy | fifo.pending for fifo in self. in_fifos]) &
                   bus.flag &
                   ~bus.nrdy_o),
        ]

        sel_flag     = bus.flag.bit_select(bus.addr, 1)
        sel_in_fifo  = self.in_fifos [bus.addr  [0]]
        sel_out_fifo = self.out_fifos[bus.addr_p[0]]
        m.d.comb += [
            bus.data.o.eq(sel_in_fifo.r_data),
            sel_out_fifo.w_data.eq(bus.data.i),
        ]

        with m.If(bus.addr[1]):
            m.d.comb += [
                sel_in_fifo.r_en.eq(bus.slwr),
                sel_in_fifo.flushed.eq(bus.pend),
                bus.nrdy_i.eq(Cat(C(0b00, 2), (bus.slwr | bus.pend) << bus.addr[0])),
            ]
        with m.Else():
            m.d.comb += [
                sel_out_fifo.w_en.eq(bus.slrd_p & sel_flag),
            ]

        # The FX2 requires the following setup latencies in worst case:
        #   * FIFOADR to FIFODATA: 2 cycles
        #   * SLOE    to FIFODATA: 1 cycle
        with m.FSM() as fsm:
            with m.State("SWITCH"):
                m.d.sync += [
                    bus.sloe.eq(0),
                    bus.data.oe.eq(0),
                ]
                # Calculate the address of the next ready FIFO in a round robin process.
                cases = {}
                with m.Switch(Cat(rdy, bus.addr)):
                    for addr_v in range(2**len(bus.addr)):
                        for rdy_v in range(2**len(rdy)):
                            for offset in range(2**len(bus.addr)):
                                addr_n = (addr_v + offset) % 2**len(bus.addr)
                                if rdy_v & (1 << addr_n):
                                    break
                            else:
                                addr_n = (addr_v + 1) % 2**len(bus.addr)
                            with m.Case(rdy_v|(addr_v<<len(rdy))):
                                m.d.sync += bus.addr.eq(addr_n)
                with m.If(rdy):
                    m.next = "DRIVE"
            with m.State("DRIVE"):
                with m.If(bus.addr[1]):
                    m.d.sync += bus.data.oe.eq(1)
                with m.Else():
                    m.d.sync += bus.sloe.eq(1)
                m.next = "SETUP"
            with m.State("SETUP"):
                with m.If(bus.addr[1]):
                    m.next = "IN-XFER"
                with m.Else():
                    m.next = "OUT-XFER"
            with m.State("IN-XFER"):
                with m.If(~sel_in_fifo.complete & sel_in_fifo.r_rdy):
                    m.d.comb += bus.slwr.eq(1)
                with m.Elif(sel_in_fifo.complete | sel_in_fifo.pending):
                    m.d.comb += bus.pend.eq(1)
                    m.next = "SWITCH"
                with m.Else():
                    m.next = "SWITCH"
            with m.State("OUT-XFER"):
                with m.If(sel_flag & sel_out_fifo.inner.w_rdy):
                    m.d.comb += bus.slrd.eq(1)
                with m.Else():
                    m.next = "SWITCH"

        return m

    def _make_fifo(self, crossbar_side, logic_side, cd_logic, reset, depth, wrapper):
        if cd_logic is None:
            fifo = wrapper(SyncFIFOBuffered(width=8, depth=depth))

            if reset is not None:
                fifo = ResetInserter(reset)(fifo)
        else:
            assert isinstance(cd_logic, ClockDomain)

            raw_fifo = DomainRenamer({
                crossbar_side: "crossbar",
                logic_side:    "logic",
            })(AsyncFIFO(width=8, depth=depth))

            fifo = wrapper(_AsyncFIFOWrapper(raw_fifo, cd_logic, reset))

        return fifo

    def get_out_fifo(self, n, depth=512, clock_domain=None, reset=None):
        assert 0 <= n < 2
        assert isinstance(self.out_fifos[n], _UnimplementedOUTFIFO)

        fifo = self._make_fifo(crossbar_side="write",
                               logic_side="read",
                               cd_logic=clock_domain,
                               reset=reset,
                               depth=depth,
                               wrapper=lambda fifo: _OUTFIFO(fifo,
                                    skid_depth=3))
        self.out_fifos[n] = fifo
        return fifo

    def get_in_fifo(self, n, depth=512, auto_flush=True, clock_domain=None, reset=None):
        assert 0 <= n < 2
        assert isinstance(self.in_fifos[n], _UnimplementedINFIFO)

        fifo = self._make_fifo(crossbar_side="read",
                               logic_side="write",
                               cd_logic=clock_domain,
                               reset=reset,
                               depth=depth,
                               wrapper=lambda fifo: _INFIFO(fifo,
                                    asynchronous=clock_domain is not None,
                                    auto_flush=auto_flush))
        self.in_fifos[n] = fifo
        return fifo
