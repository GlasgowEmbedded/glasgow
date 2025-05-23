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
from amaranth.lib import wiring, stream, io
from amaranth.lib.wiring import In, Out, connect, flipped

from .stream import StreamFIFO


__all__ = ["FX2Crossbar"]


_PACKET_SIZE = 512


class _INFIFO(wiring.Component):
    """
    A FIFO with a sideband flag indicating whether the FIFO has enough data to read from it yet.
    This FIFO may be used for packetizing the data read from the FIFO when there is no particular
    framing available to optimize the packet boundaries.
    """

    w: In(stream.Signature(8))
    r: Out(stream.Signature(8))
    flush: In(1)

    # This is a model of the IN FIFO buffer in the FX2. Keep in mind that it is legal to assert
    # PKTEND together with SLWR, and in that case PKTEND takes priority. Also, note that this
    # model must be reset on Set Configuration and Set Interface requests.
    queued:   Out(range(_PACKET_SIZE + 1))
    complete: Out(1) # one FX2 FIFO buffer full
    pending:  Out(1) # PKTEND requested
    flushed:  In(1)  # PKTEND asserted

    def elaborate(self, platform):
        m = Module()

        connect(m, flipped(self.r), flipped(self.w))

        pending = Signal()
        with m.If(self.flushed):
            m.d.sync += self.queued.eq(0)
            # If we sent a maximum-size packet, we still need a ZLP afterwards.
            with m.If(self.queued < _PACKET_SIZE):
                m.d.sync += pending.eq(0)
        with m.Elif(self.r.valid & self.r.ready):
            m.d.sync += [
                self.queued.eq(self.queued + 1),
                pending.eq(1)
            ]

        m.d.comb += [
            self.complete.eq(self.queued >= _PACKET_SIZE),
            self.pending.eq(pending & self.flush),
        ]

        return m


class _OUTFIFO(wiring.Component):
    """
    A FIFO with a skid buffer in front of it. This FIFO may be fed from a pipeline that
    reacts to the ``w.ready`` flag with a latency up to the skid buffer depth, and writes
    will not be lost.

    Note that the ``w`` interface does not conform to the usual stream invariants as a result.
    """

    w: In(stream.Signature(8))
    r: Out(stream.Signature(8))

    def __init__(self, skid_depth):
        self._skid_depth = skid_depth

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.skid = skid = StreamFIFO(shape=8, depth=self._skid_depth, buffered=False)

        m.d.comb += skid.w.payload.eq(self.w.payload)
        m.d.comb += skid.w.valid.eq(self.w.valid & (~self.r.ready | skid.r.valid))
        with m.If(skid.r.valid):
            connect(m, flipped(self.r), skid.r)
        with m.Else():
            connect(m, flipped(self.r), flipped(self.w))

        return m


class _FX2Bus(wiring.Component):
    flag: Out(4)
    addr: In(2)
    data: In(io.Buffer.Signature("io", 8))
    sloe: In(1)
    slrd: In(1)
    slwr: In(1)
    pend: In(1)

    addr_p: Out(2)
    slrd_p: Out(1)

    # When an operation is pipelined that may or may not change flags, it is useful to
    # invalidate--artificially negate--the corresponding flag until the operation completes.
    # The nrdy signals are delayed by _FX2Bus in the same way as other pipelined signals,
    # and an output bit is active while any corresponding bit in the pipeline is still active.
    nrdy_i: In(4)
    nrdy_o: Out(4)

    def __init__(self, pads):
        self.pads = pads

        super().__init__()

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
        m.submodules.fifoadr = fifoadr = io.FFBuffer("o", self.pads.fifoadr)
        m.submodules.sloe    = sloe    = io.FFBuffer("o", self.pads.sloe)
        m.submodules.slrd    = slrd    = io.FFBuffer("o", self.pads.slrd)
        m.submodules.slwr    = slwr    = io.FFBuffer("o", self.pads.slwr)
        m.submodules.pktend  = pktend  = io.FFBuffer("o", self.pads.pktend)
        m.submodules.fd      = fd      = io.DDRBuffer("io", self.pads.fd)
        m.submodules.flag    = flag    = io.DDRBuffer("i", self.pads.flag)
        m.d.comb += [
            fifoadr.o.eq(self.addr),
            sloe.o.eq(~self.sloe),
            slrd.o.eq(~self.slrd),
            slwr.o.eq(~self.slwr),
            pktend.o.eq(~self.pend),
            self.data.i.eq(fd.i[1]),
            fd.o[0].eq(self.data.o),
            fd.o[1].eq(self.data.o),
            fd.oe.eq(self.data.oe),
            self.flag.eq(flag.i[1]),
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


class FX2Crossbar(wiring.Component):
    """FX2 bus to FIFO crossbar.

    The crossbar addresses four FX2 endpoints: two ``OUT`` followed by two ``IN``, in this order.
    On the FPGA side, it provides one stream per endpoint, instantiating only a minimal amount of
    logic necessary to coordinate the transfers. The FIFOs must be instantiated externally to
    the crossbar.
    """

    in_eps: Out(wiring.Signature({
        "data":  In(stream.Signature(8)),
        "flush": In(1),
        "reset": In(1, reset=1),
    })).array(2)
    out_eps: Out(wiring.Signature({
        "data":  Out(stream.Signature(8)),
        "reset": In(1, reset=1),
    })).array(2)

    def __init__(self, pads):
        self._pads = pads

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.bus = bus = _FX2Bus(self._pads)

        in_fifos = Array([_INFIFO() for _ in self. in_eps])
        for idx, (in_fifo, in_ep) in enumerate(zip(in_fifos, self.in_eps)):
            m.submodules[ f"in_fifo_{idx}"] = ResetInserter(in_ep.reset)(in_fifo)
            connect(m, in_fifo.w, flipped(in_ep.data))
            m.d.comb += in_fifo.flush.eq(in_ep.flush)

        out_fifos = Array([_OUTFIFO(skid_depth=3) for _ in self.out_eps])
        for idx, (out_fifo, out_ep) in enumerate(zip(out_fifos, self.out_eps)):
            m.submodules[f"out_fifo_{idx}"] = ResetInserter(out_ep.reset)(out_fifo)
            connect(m, out_fifo.r, flipped(out_ep.data))

        rdy = Signal(4)
        m.d.comb += [
            rdy.eq(Cat([fifo.w.ready                for fifo in out_fifos] +
                       [fifo.r.valid | fifo.pending for fifo in  in_fifos]) &
                   bus.flag &
                   ~bus.nrdy_o),
        ]

        sel_flag     = bus.flag.bit_select(bus.addr, 1)
        sel_in_fifo  =  in_fifos[bus.addr  [0]]
        sel_out_fifo = out_fifos[bus.addr_p[0]]
        m.d.comb += [
            bus.data.o.eq(sel_in_fifo.r.payload),
            sel_out_fifo.w.payload.eq(bus.data.i),
        ]

        with m.If(bus.addr[1]):
            m.d.comb += [
                sel_in_fifo.r.ready.eq(bus.slwr),
                sel_in_fifo.flushed.eq(bus.pend),
                bus.nrdy_i.eq(Cat(C(0b00, 2), (bus.slwr | bus.pend) << bus.addr[0])),
            ]
        with m.Else():
            m.d.comb += [
                sel_out_fifo.w.valid.eq(bus.slrd_p & sel_flag),
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
                with m.If(~sel_in_fifo.complete & sel_in_fifo.r.valid):
                    m.d.comb += bus.slwr.eq(1)
                with m.Elif(sel_in_fifo.complete | sel_in_fifo.pending):
                    m.d.comb += bus.pend.eq(1)
                    m.next = "SWITCH"
                with m.Else():
                    m.next = "SWITCH"

            with m.State("OUT-XFER"):
                with m.If(sel_flag & sel_out_fifo.w.ready):
                    m.d.comb += bus.slrd.eq(1)
                with m.Else():
                    m.next = "SWITCH"

        return m
