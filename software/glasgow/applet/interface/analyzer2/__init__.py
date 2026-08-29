# Unusually for Glasgow gateware, this applet uses a fixed-size, 32-bit data path. This is done
# because the analyzer is designed for interfacing with external software, some of which may be
# written in a way that makes complex and generic bitwise transformations unreasonably difficult.
#
# **Read the protocol documentation for this applet first; it contains important background info.**
# Note that the units used in the protocol are words, but the implementation uses bytes instead.
# (This is because the implementation has to manipulate a mixture of 32-bit, 16-bit, and 8-bit
# quantities.)
#
# The analyzer applet can be broken into a few functional units:
#  * The pin sampler unit acquires data and packs it into 32-bit words.
#  * The basic trigger unit analyzes the incoming data and injects the trigger marker when trigger
#    condition matches or a trigger is forced; it also injects discard markers as appropriate.
#  * The circuit breaker unit handles overflow conditions. There are two types of overflow
#    conditions: caused by insufficient writer bandwidth, and caused by insufficient reader
#    bandwidth.
#  * The writer and reader units write and read words to/from RAM, respectively. They maintain
#    an internal address counter that automatically wraps to the beginning of any received DRAM
#    memory range, including non-power-of-2 sized ranges or ranges with minimal alignment.
#  * The write flow control unit ensures that the writer unit does not overwrite still-unread data
#    by throttling the writer if an conservative estimation of queue size exceeds DRAM region size.
#  * The read flow control unit ensures that the reader unit does not read still-unwritten data.
#    It is also responsible for responding to trigger, discard, and overflow events, and capping
#    the queue size by the configured prolog size during the pre-trigger phase.
#
# The approach taken to handling flow control and overflows is that the sampling pipeline is never
# reset for any reason. This is done because the memory controller is only reset by the applet
# domain reset, and since in-flight transactions cannot be cancelled, partial reset of the analyzer
# core is not viable. This restriction makes it non-viable to use `ResetInserter` as a quick and
# cheap way to synchronize state after configuration updates; instead, pipeline is flushed by e.g.
# sample rate changes. To do this, the sampling end of the pipeline gains a second input: a stream
# of _events_, such as trigger arming or pipeline flushing.
#
# Overflows deserve special attention. There is *some* point in the pipeline at which data must
# be lost; this point cannot be after the moment that the first word is submitted to the memory
# controller (or it will become difficult to impossible to accurately record the event); and there
# must be a way to recover from this without resetting the entire applet (which will e.g. crash
# PulseView). They are handled with a sticky overflow state in the circuit breaker that stops all
# further sampling (see below for reasoning behind that), which is reset by the interrupt event.
#
# A core concept in the logic analyzer implementation is that of a *block*: a continuous sequence
# of words containing data samples that is terminated by a marker. A block terminated by a *normal*
# marker can be treated as contiguous with the following block. More interestingly, a block that is
# terminated with an *abnormal* (trigger, discard, or overflow) marker contains a barrier: writes
# can only proceed past the barrier once its function is acknowledged. For example, a block ending
# with a trigger marker will cause further writes to be paused until the trigger FSM can issue
# a read of all data contained in the queue buffer. If the writer proceeded past this point before
# the trigger FSM had a chance to do that, the wrong amount of prolog samples would be captured.
#
# Blocks terminated with an abnormal marker must be rare events since they instantaneously decrease
# the bandwidth. E.g. if each word coming out of the trigger unit has the overflow marker, it will
# cause a sequence of 1-word blocks to be written. This is much less efficient than the ordinarily
# sized blocks (at time of writing, 128-word) and it will quickly lock up the bus at higher sample
# rates. This is why the overflow condition is sticky and reset only by a pipeline flush.

import re
import sys
import struct
import asyncio
import argparse
from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
from functools import reduce
from array import array

from amaranth import *
from amaranth.utils import ceil_log2, exact_log2
from amaranth.lib import enum, data, wiring, stream, io, memory
from amaranth.lib.wiring import In, Out, flipped

from glasgow.support import logging
from glasgow.support.endpoint import endpoint, ServerEndpoint
from glasgow.gateware import octoram, cobs
from glasgow.gateware.stream import Queue, StreamBuffer
from glasgow.abstract import AbstractAssembly, DRAMOptions, GlasgowPin
from glasgow.applet import GlasgowAppletV2, GlasgowAppletError


__all__ = [
    "DataFormat", "DigitalFormat", "DigitalTrigger", "AnalyzerError", "SampleBlock",
    "AnalyzerInterface",
]


class Marker(enum.Enum, shape=3):
    """Block metadata classifier."""

    Normal = 0b000
    """No special meaning."""

    Discard = 0b001
    """Any samples accumulated for the prolog must be discarded."""

    Trigger = 0b100
    """The word contains a trigger match at :py:`offset`."""

    Overflow = 0b010
    """Samples arrived faster than they could be processed.

    This marker is imprecise: an overflow may be detected a few samples earlier or later than it
    occurs due to CDC delays.
    """

    Complete = 0b110
    """The last requested sample has been provided."""


class Trailer(data.Struct):
    """Block metadata.

    The trailer is a single byte appended after the last word in a COBS frame containing the data
    substream. It indicates the special nature of the last word in a block of sample data. It is
    also used throughout the acquisition pipeline to monitor exceptional conditions.
    """

    offset: 5
    marker: Marker

    @property
    def abnormal(self) -> Value:
        return self.marker != Marker.Normal


class DataFormat(metaclass=ABCMeta):
    """Base class for data format descriptions."""

    @property
    @abstractmethod
    def fourcc(self) -> int:
        """FourCC identifier of this format."""


@dataclass(frozen=True)
class DigitalFormat(DataFormat):
    """Data words with digital samples only."""

    width:  int
    """Size of each sample, in bits."""

    stride: int
    """Distance between sample LSBs, in bits."""

    @classmethod
    def for_width(cls, width: int):
        return cls(width=width, stride=1 << ceil_log2(width))

    def __post_init__(self):
        assert 1 <= self.width  <= 32
        assert 1 <= self.stride <= 32

    @property
    def fourcc(self) -> int:
        return int.from_bytes(b"\0\0DI", "little") | self.width | (self.stride << 8)


class PinSampler(wiring.Component):
    """Pin sampling and rate conversion.

    Samples pins at an interval specified by a divisor and packs them into 32-bit words according
    to the configured stride. For sampling at rates faster than the ``sync`` clock of the main
    instrument logic, this unit can be placed in a different clock domain.
    """

    CONTROL_SHAPE = data.StructLayout({
        "divisor": 24,
    })

    STATUS_SHAPE = data.StructLayout({
        "overflow": 1,
    })

    control: In(CONTROL_SHAPE)
    status: Out(STATUS_SHAPE)

    o_samples: Out(stream.Signature(data.StructLayout({
        "data": 32,
    })))

    def __init__(self, *, format: DigitalFormat, pins: io.PortLike):
        self._format = format
        self._pins   = pins

        assert len(self._pins) == self._format.width

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.i_buf = i_buf = io.FFBuffer("i", self._pins)

        sample = Signal()
        offset = Signal(range(32 // self._format.stride))
        with m.If(sample):
            m.d.sync += offset.eq(offset + 1)
            m.d.sync += self.o_samples.p.data.word_select(offset, self._format.stride).eq(i_buf.i)
            m.d.sync += self.o_samples.valid.eq(offset == (32 // self._format.stride) - 1)
        with m.Else():
            m.d.sync += self.o_samples.valid.eq(0)

        # Not supposed to ever happen; however, the output stream here (and the streams of
        # the trigger unit as well) are not `always_ready=True` to allow for a CDC queue to be
        # inserted. A correctly sized queue in a properly clocked domain won't ever cause
        # an overflow here, so this check only protects against faulty clocking.
        with m.If(self.o_samples.valid & ~self.o_samples.ready):
            m.d.sync += self.status.overflow.eq(1)

        timer = Signal.like(self.control.divisor)
        with m.If(timer == 0):
            m.d.comb += sample.eq(1)
            m.d.sync += timer.eq(self.control.divisor)
        with m.Else():
            m.d.sync += timer.eq(timer - 1)

        return m


class Event(enum.Enum, shape=3):
    """Pipeline event.

    Indicates an exceptional condition within the acqiusition pipeline.
    """

    Normal = 0
    """No exceptional condition."""

    Interrupt = 1
    """Interrupt acquisition and discard all previous samples."""

    ForceTrig = 2
    """Force trigger match on next examined sample."""

    EnableTrig = 3
    """Enable trigger unit until the next match."""

    DisableTrig = 4
    """Disable trigger unit."""


class BasicTrigger(wiring.Component):
    """Edge- or level-based triggering.

    Inserts trigger events when a packed input sample matches the corresponding condition.
    When multiple conditions are configured, they are combined using logical OR.

    The marker input stream allows injecting exceptional conditions into the pipeline. This is
    intended for handling three primary cases: forced trigger, sampler overflow, and discarding
    stale data on configuration change.
    """

    class Condition(data.Struct):
        active:  1
        level:   1
        value:   1
        anyedge: 1

    CONTROL_SHAPE = data.ArrayLayout(Condition, 32)

    STATUS_SHAPE = data.StructLayout({
        "enabled": 1,
    })

    control: In(CONTROL_SHAPE)
    status: Out(STATUS_SHAPE)

    i_events: In(stream.Signature(Event))
    i_samples: In(stream.Signature(data.StructLayout({
        "data": 32,
    })))

    o_samples: Out(stream.Signature(data.StructLayout({
        "data": 32,
        "meta": Trailer,
    })))

    def __init__(self, *, format: DigitalFormat):
        self._format = format

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        has_match = Signal()

        last_sample = Signal.like(self.i_samples.p.data)
        with m.If(0):
            pass
        prev_sample = last_sample
        for offset in range(0, len(self.i_samples.p.data), self._format.stride):
            curr_sample = self.i_samples.p.data.bit_select(offset, self._format.width)
            for curr_bit, prev_bit, cond_bit in zip(curr_sample, prev_sample, self.control):
                with m.Elif(cond_bit.active &
                    (cond_bit.anyedge | (cond_bit.value == curr_bit)) &
                    (cond_bit.level | (curr_bit != prev_bit))
                ):
                    m.d.comb += has_match.eq(1)
                    m.d.comb += self.o_samples.p.meta.offset.eq(offset)
            prev_sample = curr_sample
        with m.If(self.i_samples.valid & self.i_samples.ready):
            m.d.sync += last_sample.eq(curr_sample)

        # Ensure `marker` and `enabled` only change when the output stream isn't valid or has just
        # completed a transfer; this allows combinationally including them in the payload without
        # violating stream rules.
        marker = Signal(Marker)
        enabled = Signal()
        with m.If(self.o_samples.valid & self.o_samples.ready): # on output transfer:
            m.d.sync += marker.eq(Marker.Normal) # remove transmitted marker
            with m.If((self.o_samples.p.meta.marker == Marker.Trigger) |
                      (self.o_samples.p.meta.marker == Marker.Discard)): # disarm trigger
                m.d.sync += enabled.eq(0)
        with m.If(~self.o_samples.valid | self.o_samples.ready): # if output can change:
            with m.If(self.o_samples.p.meta.marker == Marker.Normal): # without overwriting marker:
                m.d.comb += self.i_events.ready.eq(1)
                with m.If(self.i_events.valid): # apply new marker
                    with m.Switch(self.i_events.payload):
                        with m.Case(Event.EnableTrig):
                            m.d.sync += enabled.eq(1)
                        with m.Case(Event.DisableTrig):
                            m.d.sync += enabled.eq(0)
                        with m.Case(Event.ForceTrig):
                            m.d.sync += marker.eq(Marker.Trigger)
                        with m.Case(Event.Interrupt):
                            m.d.sync += marker.eq(Marker.Discard)

        m.d.comb += [
            self.o_samples.p.data.eq(self.i_samples.p.data),
            self.o_samples.valid.eq(self.i_samples.valid),
            self.i_samples.ready.eq(self.o_samples.ready),
        ]
        with m.If(marker != Marker.Normal):
            m.d.comb += self.o_samples.p.meta.marker.eq(marker)
        with m.Elif(enabled & has_match):
            m.d.comb += self.o_samples.p.meta.marker.eq(Marker.Trigger)

        m.d.comb += self.status.enabled.eq(enabled)

        return m


class CircuitBreaker(wiring.Component):
    i_samples: In(stream.Signature(data.StructLayout({
        "data": 32,
        "meta": Trailer,
    }), always_ready=True))
    o_samples: Out(stream.Signature(data.StructLayout({
        "data": 32,
        "meta": Trailer,
    })))

    def elaborate(self, platform):
        m = Module()

        with m.FSM() as fsm:
            with m.State("Passthrough"):
                overflow = Signal()

                with m.If(~self.o_samples.valid | self.o_samples.ready):
                    m.d.sync += self.o_samples.valid.eq(self.i_samples.valid)
                    m.d.sync += self.o_samples.payload.eq(self.i_samples.payload)
                    with m.If(overflow):
                        m.d.sync += self.o_samples.p.meta.marker.eq(Marker.Overflow)
                        m.d.sync += self.o_samples.p.meta.offset.eq(0)
                with m.Elif(self.i_samples.valid):
                    # Report overflow on the next sample, without tearing the payload.
                    m.d.sync += overflow.eq(1)

                with m.If(self.o_samples.valid & self.o_samples.ready &
                        (self.o_samples.p.meta.marker == Marker.Overflow)):
                    # Once overflow is reported, wait for the pipeline to flush.
                    m.d.sync += overflow.eq(0)
                    m.next = "Wait-for-Discard"

            with m.State("Wait-for-Discard"):
                with m.If(self.i_samples.valid & (self.i_samples.p.meta.marker == Marker.Discard)):
                    # This swallows the discard marker; however, since we've discarded all
                    # preceding samples since the overflow, the effect is the same anyway.
                    m.next = "Passthrough"

        return m


class Arbiter(wiring.Component):
    """Buffering DRAM arbiter.

    Buffers data being written or read so that the DRAM is only accessed in bursts. This is
    necessary to avoid the reader blocking the writer due to lack of readiness, as well as
    to respect the CS# active period requirements of the DRAM.

    The data buffer is not a part of this component; rather, the async FIFO instantiated within
    the assembly (which is necessary for CDC) is also used for buffering data.
    """

    dram: Out(octoram.Signature())

    w_cmd: In(stream.Signature(data.StructLayout({
        "addr": 32,
        "size": range(2048), # multiple of 2; not allowed to cross 2K boundaries
    })))
    w_data: In(stream.Signature(data.ArrayLayout(8, 2)))

    r_cmd: In(stream.Signature(data.StructLayout({
        "addr": 32,
        "size": range(2048), # multiple of 2; not allowed to cross 2K boundaries
    })))
    r_data: Out(stream.Signature(data.ArrayLayout(8, 2)))

    def __init__(self, *, queue_bytes: int, burst_bytes: int):
        self._queue_bytes = queue_bytes
        self._burst_bytes = burst_bytes

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        # Empirically determined.
        cmd_buffer_depth = 2

        # Write handling

        m.submodules.w_cmd_buffer = w_cmd_buffer = Queue.shaped_like(self.w_cmd,
            depth=cmd_buffer_depth)
        wiring.connect(m, flipped(self.w_cmd), w_cmd_buffer.i)

        m.d.comb += [
            self.dram.w_data.p[0].data.eq(self.w_data.p[0]),
            self.dram.w_data.p[1].data.eq(self.w_data.p[1]),
            self.dram.w_data.valid.eq(self.w_data.valid),
            self.w_data.ready.eq(self.dram.w_data.ready),
        ]

        w_data_incr = Signal(1)
        w_data_decr = Signal.like(self.dram.commands.p.size)
        w_data_level = Signal(range(self._queue_bytes))
        with m.If(self.w_data.valid & self.w_data.ready):
            m.d.comb += w_data_incr.eq(1)
        with m.If(self.dram.commands.valid & self.dram.commands.ready):
            with m.If(self.dram.commands.p.type == octoram.Command.WriteMemRow):
                m.d.comb += w_data_decr.eq(self.dram.commands.p.size)
        m.d.sync += w_data_level.eq(w_data_level + w_data_incr - w_data_decr)

        # Read handling

        m.submodules.r_cmd_buffer = r_cmd_buffer = Queue.shaped_like(self.r_cmd,
            depth=cmd_buffer_depth)
        wiring.connect(m, flipped(self.r_cmd), r_cmd_buffer.i)

        m.d.comb += [
            self.r_data.p[0].eq(self.dram.r_data.p[0]),
            self.r_data.p[1].eq(self.dram.r_data.p[1]),
            self.r_data.valid.eq(self.dram.r_data.valid),
            self.dram.r_data.ready.eq(self.r_data.ready),
        ]

        r_data_incr = Signal.like(self.dram.commands.p.size)
        r_data_decr = Signal(1)
        r_data_level = Signal(range(self._queue_bytes))
        r_data_space = self._queue_bytes - r_data_level
        with m.If(self.r_data.valid & self.r_data.ready):
            m.d.comb += r_data_decr.eq(1)
        with m.If(self.dram.commands.valid & self.dram.commands.ready):
            with m.If(self.dram.commands.p.type == octoram.Command.ReadMemRow):
                m.d.comb += r_data_incr.eq(self.dram.commands.p.size)
        m.d.sync += r_data_level.eq(r_data_level + r_data_incr - r_data_decr)

        # Command handling

        m.submodules.cmd_buffer = cmd_buffer = StreamBuffer.shaped_like(self.dram.commands)
        wiring.connect(m, cmd_buffer.o, flipped(self.dram.commands))

        # Uses `cmd_buffer` to avoid violating stream rules on the output.
        with m.If(w_cmd_buffer.o.valid & (w_data_level >= (w_cmd_buffer.o.p.size >> 1))):
            m.d.comb += [
                cmd_buffer.i.p.type.eq(octoram.Command.WriteMemRow),
                cmd_buffer.i.p.addr.eq(w_cmd_buffer.o.p.addr),
                cmd_buffer.i.p.size.eq(w_cmd_buffer.o.p.size >> 1),
                cmd_buffer.i.valid.eq(1),
                w_cmd_buffer.o.ready.eq(cmd_buffer.i.ready),
            ]
        with m.Elif(r_cmd_buffer.o.valid & (r_data_space >= (r_cmd_buffer.o.p.size >> 1))):
            m.d.comb += [
                cmd_buffer.i.p.type.eq(octoram.Command.ReadMemRow),
                cmd_buffer.i.p.addr.eq(r_cmd_buffer.o.p.addr),
                cmd_buffer.i.p.size.eq(r_cmd_buffer.o.p.size >> 1),
                cmd_buffer.i.valid.eq(1),
                r_cmd_buffer.o.ready.eq(cmd_buffer.i.ready),
            ]

        return m


class Writer(wiring.Component):
    """Writer unit.

    Writes 4-byte packed samples to memory in bursts. Essentially a specialized write-combining
    cache. Outputs blocks (ranges of bytes with an optional trigger) once the write is committed
    to memory; the trigger, if active, is always at the last sample of the block.
    """

    STATUS_SHAPE = data.StructLayout({
        "pointer": 32,
        "lockup":  1,
    })

    status: Out(STATUS_SHAPE)

    w_cmd: Out(stream.Signature(data.StructLayout({
        "addr": 32,
        "size": range(2048),
    })))
    w_data: Out(stream.Signature(data.ArrayLayout(8, 2)))

    i_samples: In(stream.Signature(data.StructLayout({
        "data": data.ArrayLayout(8, 4),
        "meta": Trailer,
    })))
    o_blocks: Out(stream.Signature(data.StructLayout({
        "size": 10, # 4-byte multiple
        "meta": Trailer,
    })))

    def __init__(self, *, dram_range: range, burst_bytes: int):
        assert dram_range.start % burst_bytes == 0
        assert dram_range.stop % burst_bytes == 0
        assert dram_range.step == 1

        self._dram_range  = dram_range
        self._burst_bytes = 1 << exact_log2(burst_bytes)

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        # Convert 4-byte packed samples into 2-byte memory beats.
        w_enable = Signal()
        w_phase = Signal()
        m.d.comb += [
            self.w_data.p[0].eq(Mux(w_phase, self.i_samples.p.data[2], self.i_samples.p.data[0])),
            self.w_data.p[1].eq(Mux(w_phase, self.i_samples.p.data[3], self.i_samples.p.data[1])),
            self.w_data.valid.eq(w_enable & self.i_samples.valid),
            self.i_samples.ready.eq(w_enable & self.w_data.ready & w_phase),
        ]
        with m.If(self.w_data.valid & self.w_data.ready):
            m.d.sync += w_phase.eq(~w_phase)

        w_curr_size = Signal(range(self._burst_bytes + 1))
        w_curr_addr = Signal(self._dram_range, init=self._dram_range.start)
        w_next_addr = Signal(self._dram_range, init=self._dram_range.start)
        m.d.comb += [
            self.w_cmd.p.size.eq(w_curr_size),
            self.w_cmd.p.addr.eq(w_curr_addr),
        ]
        with m.If(self.w_data.valid & self.w_data.ready):
            m.d.sync += w_curr_size.eq(w_curr_size + 2)
            m.d.sync += w_next_addr.eq(w_next_addr + 2)
        with m.Elif(self.w_cmd.valid & self.w_cmd.ready):
            m.d.sync += w_curr_size.eq(0)
            with m.If(w_next_addr == self._dram_range.stop):
                m.d.sync += w_curr_addr.eq(self._dram_range.start)
                m.d.sync += w_next_addr.eq(self._dram_range.start)
            with m.Else():
                m.d.sync += w_curr_addr.eq(w_next_addr)

        m.d.sync += self.status.pointer.eq(w_curr_addr)

        with m.FSM():
            with m.State("Queue-Data"):
                m.d.comb += w_enable.eq(1)
                with m.If(self.i_samples.valid & self.i_samples.ready):
                    with m.If(self.i_samples.p.meta.abnormal):
                        m.d.sync += self.o_blocks.p.meta.eq(self.i_samples.p.meta)
                        m.next = "Write-Data"
                    with m.Elif((w_next_addr + 2) & (self._burst_bytes - 1) == 0):
                        m.d.sync += self.o_blocks.p.meta.eq(0)
                        m.next = "Write-Data"

            with m.State("Write-Data"):
                m.d.comb += self.w_cmd.valid.eq(1)
                with m.If(self.w_cmd.valid & self.w_cmd.ready):
                    m.d.sync += self.o_blocks.p.size.eq(w_curr_size)
                    m.next = "Report-Block"

            with m.State("Report-Block"):
                m.d.comb += self.o_blocks.valid.eq(1)
                with m.If(self.o_blocks.valid & self.o_blocks.ready):
                    m.next = "Queue-Data"

        lockup_timer = Signal(4, init=15)
        with m.If(self.o_blocks.valid & ~self.o_blocks.ready):
            with m.If(lockup_timer == 0):
                m.d.sync += self.status.lockup.eq(1)
            with m.Else():
                m.d.sync += lockup_timer.eq(lockup_timer - 1)
        with m.Else():
            m.d.sync += lockup_timer.eq(lockup_timer.init)

        return m


class Reader(wiring.Component):
    """Reader unit.

    Reads the contents of the specified ranges from memory.

    If `i_blocks.p.size == 0`, locks up the memory controller.
    """

    r_cmd: Out(stream.Signature(data.StructLayout({
        "addr": 32,
        "size": range(2048),
    })))
    r_data: In(stream.Signature(data.ArrayLayout(8, 2)))

    i_blocks: In(stream.Signature(data.StructLayout({
        "skip": 1,  # whether to read range contents or only advance the pointer
        "size": 16, # 4-byte multiple, non-zero
        "meta": Trailer,
    })))
    o_octets: Out(stream.Signature(data.StructLayout({
        "data": 8,
        "end":  1,
    })))

    def __init__(self, *, dram_range: range, burst_bytes: int):
        assert dram_range.start % burst_bytes == 0
        assert dram_range.stop % burst_bytes == 0
        assert dram_range.step == 1

        self._dram_range  = dram_range
        self._burst_bytes = 1 << exact_log2(burst_bytes)

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        # Queue blocks so that trailers can be inserted as appropriate.
        m.submodules.block_queue = block_queue = StreamBuffer.shaped_like(self.i_blocks)

        with m.FSM(name="octet_fsm"):
            # Convert 2-byte memory beats into output octets.
            with m.State("Data"):
                r_phase = Signal()
                r_count = Signal.like(block_queue.o.p.size)
                m.d.comb += [
                    self.o_octets.p.data.eq(self.r_data.payload[r_phase]),
                    self.o_octets.valid.eq(block_queue.o.valid & self.r_data.valid),
                    self.r_data.ready.eq(block_queue.o.valid & self.o_octets.ready & r_phase),
                ]
                with m.If(self.o_octets.valid & self.o_octets.ready):
                    m.d.sync += r_phase.eq(~r_phase)
                    m.d.sync += r_count.eq(r_count + 1)
                    with m.If(r_count + 1 == block_queue.o.p.size):
                        m.d.sync += r_count.eq(0)
                        with m.If(block_queue.o.p.meta.abnormal):
                            m.next = "Trailer"
                        with m.Else():
                            m.d.comb += block_queue.o.ready.eq(1)

            # Append a trailer and end the stream.
            with m.State("Trailer"):
                m.d.comb += self.o_octets.p.data.eq(block_queue.o.p.meta)
                m.d.comb += self.o_octets.valid.eq(1)
                with m.If(self.o_octets.valid & self.o_octets.ready):
                    m.d.comb += block_queue.o.ready.eq(1)
                    m.next = "End"

            with m.State("End"):
                m.d.comb += self.o_octets.p.end.eq(1)
                m.d.comb += self.o_octets.valid.eq(1)
                with m.If(self.o_octets.valid & self.o_octets.ready):
                    m.next = "Data"

        r_curr_addr = Signal(self._dram_range, init=self._dram_range.start)
        r_curr_size = Signal(range(self._burst_bytes + 1))
        r_full_size = Signal.like(self.i_blocks.p.size)
        m.d.comb += [
            self.r_cmd.p.addr.eq(r_curr_addr),
            self.r_cmd.p.size.eq(r_curr_size),
            block_queue.i.payload.eq(self.i_blocks.payload),
        ]
        with m.If(~self.r_cmd.valid | self.r_cmd.ready):
            with m.If(r_curr_addr + r_curr_size == self._dram_range.stop):
                m.d.sync += r_curr_addr.eq(self._dram_range.start)
            with m.Else():
                m.d.sync += r_curr_addr.eq(r_curr_addr + r_curr_size)

        with m.FSM(name="command_fsm"):
            with m.State("Wait-Block"):
                m.d.sync += r_full_size.eq(0)
                with m.If(self.i_blocks.valid):
                    m.d.comb += block_queue.i.valid.eq(~self.i_blocks.p.skip)
                    with m.If(~block_queue.i.valid | block_queue.i.ready):
                        m.next = "Read-Data"

            with m.State("Read-Data"):
                remainder_bytes  = self.i_blocks.p.size - r_full_size
                next_burst_bytes = self._burst_bytes - (r_curr_addr & (self._burst_bytes - 1))
                with m.If(next_burst_bytes < remainder_bytes):
                    m.d.comb += r_curr_size.eq(next_burst_bytes)
                with m.Elif(remainder_bytes < self._burst_bytes):
                    m.d.comb += r_curr_size.eq(remainder_bytes)
                with m.Else():
                    m.d.comb += r_curr_size.eq(self._burst_bytes)

                m.d.comb += self.r_cmd.valid.eq(~self.i_blocks.p.skip)
                with m.If(~self.r_cmd.valid | self.r_cmd.ready):
                    m.d.sync += r_full_size.eq(r_full_size + r_curr_size)
                    with m.If(r_full_size + r_curr_size == self.i_blocks.p.size):
                        m.d.comb += self.i_blocks.ready.eq(1)
                        m.next = "Wait-Block"

        return m


class WriteControl(wiring.Component):
    """Write flow control unit.

    Has two modes: free-run and budgeted. In free-run mode, no credits are taken or given; writes
    proceed undisturbed. In budgeted mode, credits are given to the writer (one ``writer_ratio``
    per stream transfer) and taken from the reader (one ``reader_ratio`` per stream transfer).
    The amount of outstanding credits is tracked, and must be below ``max_credits`` at all times
    in order for writes to proceed. No writes are allowed if the outstanding credits exceed
    the budget; this will cause the sampling head to detect an overflow condition.

    At the cycle where ``free_run`` goes low, the value of ``prolog_size`` is used as the starting
    amount of outstanding credits. This represents the amount of already written data behind
    the starting address of the writer's next burst that must be preserved for readout.
    """

    def __init__(self, *, writer_shape, reader_shape, writer_ratio: int, reader_ratio: int,
                 max_credits: int):
        self._writer_ratio = writer_ratio
        self._reader_ratio = reader_ratio
        self._max_credits  = max_credits

        super().__init__({
            "i_writer": In(stream.Signature(writer_shape)),
            "o_writer": Out(stream.Signature(writer_shape)),
            "i_reader": In(stream.Signature(reader_shape)),
            "o_reader": Out(stream.Signature(reader_shape)),

            "free_running": In(1),
            "prolog_size":  In(range(max_credits + 1)),
            "credits":      Out(range(max_credits + 1)),
        })

    def elaborate(self, platform):
        m = Module()

        enabled = Signal()
        allow_write = Signal()

        with m.If(~self.o_writer.valid | self.o_writer.ready):
            m.d.sync += allow_write.eq(enabled)

        m.d.comb += [
            self.o_writer.payload.eq(self.i_writer.payload),
            self.o_writer.valid.eq(self.i_writer.valid & allow_write),
            self.i_writer.ready.eq(self.o_writer.ready & allow_write),
            self.o_reader.payload.eq(self.i_reader.payload),
            self.o_reader.valid.eq(self.i_reader.valid),
            self.i_reader.ready.eq(self.o_reader.ready),
        ]

        credits  = self.credits
        credits1 = credits  + Mux(self.o_writer.valid & self.o_writer.ready, self._writer_ratio, 0)
        credits2 = credits1 - Mux(self.o_reader.valid & self.o_reader.ready, self._reader_ratio, 0)

        with m.If(self.free_running):
            m.d.comb += enabled.eq(1)
            m.d.sync += credits.eq(Mux(credits1 < self.prolog_size, credits1, self.prolog_size))
        with m.Else():
            with m.If(credits <= self._max_credits - self._writer_ratio):
                m.d.comb += enabled.eq(1)
            # In principle this should be impossible if the read barriers are respected, but
            # the free-running mode has some funky edge cases which can cause the credits to go
            # negative. Since *under*counting credits is harmless we just clamp it at zero.
            with m.If(credits2 > 0):
                m.d.sync += credits.eq(credits2)

        return m


class ReadControl(wiring.Component):
    """Read flow control unit.

    While the write flow control unit caps the (conservative estimate of) size of the sample queue
    to the size of the DRAM region, it does not function as a barrier: the fact that a credit has
    been issued to write a byte enables the readout of one byte, but actually reading this byte may
    well cause the reader to race ahead of the writer. The read flow control unit implements a read
    barrier and ensures the amount of enqueued samples does not exceed the configured prolog size.
    """

    CONTROL_SHAPE = data.StructLayout({
        "prolog_size": 32, # 4-byte multiple
        "epilog_size": 32, # 4-byte multiple
        "streaming":   1,
    })

    STATUS_SHAPE = data.StructLayout({
        "free_running": 1,
        "triggered":    1,
        "overflow":     1,
        "queue_size":   32,
        "stall_count":  4,
    })

    control: In(CONTROL_SHAPE)
    status: Out(STATUS_SHAPE)

    w_blocks: In(stream.Signature(data.StructLayout({
        "size": 10, # 4-byte multiple
        "meta": Trailer,
    })))
    r_blocks: Out(stream.Signature(data.StructLayout({
        "skip": 1,  # whether to read range contents or only advance the pointer
        "size": 16, # 4-byte multiple, non-zero
        "meta": Trailer,
    })))

    def __init__(self, *, dram_range: range, burst_bytes: int):
        assert dram_range.step == 1
        assert burst_bytes % 4 == 0

        self._dram_range  = dram_range
        self._burst_bytes = burst_bytes

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        queue_size = Signal(self._dram_range)
        m.d.comb += self.status.queue_size.eq(queue_size)
        m.d.sync += queue_size.eq(queue_size
            + Mux(self.w_blocks.valid & self.w_blocks.ready, self.w_blocks.p.size, 0)
            - Mux(self.r_blocks.valid & self.r_blocks.ready, self.r_blocks.p.size, 0))

        # For the most part, the writer unit is expected to write to the DRAM continuously.
        # However, sometimes it must be paused: barriers are required when an accurate measurement
        # of the queue size must happen, e.g. before a trigger or overflow event, to find out how
        # much data can be read out before encountering the event in question.
        #
        # When an abnormal trailer marker is encountered, the block is still consumed so that
        # the next block can be written; the writer is only prevented from progressing afterwards
        # (and so is `queue_size`). This avoids hiccups where it takes a while for the trigger FSM
        # to get to processing the trailer for one reason or another.
        m.submodules.barrier = barrier = StreamBuffer(Trailer)
        m.d.comb += barrier.i.payload.eq(self.w_blocks.p.meta)

        with m.FSM(name="write_fsm"):
            with m.State("Idle"):
                m.d.comb += self.w_blocks.ready.eq(1)
                with m.If(self.w_blocks.valid):
                    with m.If(self.w_blocks.p.meta.abnormal):
                        # This also delays the reaction to the marker by (at least) one cycle,
                        # ensuring `queue_size` is updated.
                        m.d.comb += barrier.i.valid.eq(1)
                        m.next = "Busy"

            with m.State("Busy"):
                with m.If(barrier.i.ready):
                    m.next = "Idle"

        # The reader unit itself has no flow control that would prevent it from overrunning
        # the writer unit. (It will, however, split read requests into smaller bursts to avoid
        # starving the latter.) We have to slice large readout commands (prolog and epilog sizes
        # can be as high as 4 GB, though only the epilog can actually get that large) into smaller
        # chunks that are issued once the queue has enough data in it.
        #
        # Note that even if the burst sizes are the same for the reader unit and the readout
        # control unit, these are not redundant controls, as the readout control unit also
        # ensures that the requests do not cross 2 Kbyte DRAM row boundaries.
        m.submodules.request = request = StreamBuffer(
            data.StructLayout({"skip": 1, "size": 32, "meta": Trailer}))

        # Overflow and discard events require abandoning the current read, which might never be
        # fulfilled. This is difficult to do without introducing a race condition. Note that
        # the `Skip` state is uninterruptible: it quickly completes when there is enough data in
        # the queue, and is only entered when the data is already enqueued in first place.
        interrupt_now = Signal()
        interrupt_reg = Signal()
        m.d.sync += interrupt_reg.eq(interrupt_now)
        interrupt = (interrupt_now & ~interrupt_reg)

        # The read FSM splits a large read request into smaller chunks and schedules these chunks
        # as soon as they are written. In other words, it handles the write barrier.
        residual = Signal.like(request.o.p.size)
        with m.FSM(name="read_fsm"):
            with m.State("Idle"):
                m.d.sync += residual.eq(request.o.p.size)
                with m.If(request.o.valid):
                    m.next = "Loop"

            with m.State("Loop"):
                # Delay completion by one cycle to ensure `queue_size` is updated.
                with m.If(residual == 0):
                    m.d.comb += request.o.ready.eq(1)
                    m.next = "Idle"
                with m.Else():
                    with m.If(self.r_blocks.p.skip):
                        # Skipping is done in large chunks to maximize throughput. Only data that
                        # is already written is skipped; skipping in small chunks (as for reads)
                        # results in lockups when reducing the prolog size by a large amount.
                        m.next = "Skip"
                    with m.Elif(interrupt):
                        m.d.comb += request.o.ready.eq(1)
                        m.next = "Idle"
                    with m.Else():
                        # Reading is done in smaller chunks to minimize write-to-read latency.
                        m.next = "Read"

            with m.State("Skip"):
                m.d.comb += self.r_blocks.p.skip.eq(1)
                m.d.comb += self.r_blocks.valid.eq(queue_size >= self.r_blocks.p.size)
                with m.If(residual > 0x10000 - 2):
                    m.d.comb += self.r_blocks.p.size.eq(0x10000 - 2)
                with m.Else():
                    m.d.comb += self.r_blocks.p.size.eq(residual)
                with m.If(self.r_blocks.valid & self.r_blocks.ready):
                    m.d.sync += residual.eq(residual - self.r_blocks.p.size)
                    m.next = "Loop"

            with m.State("Read"):
                m.d.comb += self.r_blocks.valid.eq(queue_size >= self.r_blocks.p.size)
                m.d.comb += self.r_blocks.p.skip.eq(request.o.p.skip)
                with m.If(residual > self._burst_bytes):
                    m.d.comb += self.r_blocks.p.size.eq(self._burst_bytes)
                with m.Else():
                    m.d.comb += self.r_blocks.p.size.eq(residual)
                    m.d.comb += self.r_blocks.p.meta.eq(request.o.p.meta)
                with m.If(self.r_blocks.valid & self.r_blocks.ready):
                    m.d.sync += residual.eq(residual - self.r_blocks.p.size)
                    m.next = "Loop"
                with m.If(interrupt):
                    m.d.comb += request.o.ready.eq(1)
                    m.next = "Idle"

        # The trigger FSM monitors the markers of just-written blocks and schedules ranges to be
        # processed by the read FSM.
        trigger_meta = Signal(Trailer)
        with m.FSM(name="trigger_fsm") as trigger_fsm:
            with m.State("Free-Run"):
                m.d.comb += [
                    request.i.p.skip.eq(1),
                    request.i.p.size.eq(queue_size - self.control.prolog_size),
                    request.i.valid.eq(queue_size > self.control.prolog_size),
                ]
                with m.If(barrier.o.valid):
                    with m.If(barrier.o.p.marker == Marker.Trigger):
                        with m.If(~request.i.valid | request.i.ready):
                            m.d.comb += barrier.o.ready.eq(1)
                            m.d.sync += trigger_meta.eq(barrier.o.payload)
                            m.next = "Prolog"
                    with m.Elif(barrier.o.p.marker == Marker.Overflow):
                        m.d.sync += self.status.stall_count.eq(self.status.stall_count + 1)
                        m.next = "Overflow"
                    with m.Elif(barrier.o.p.marker == Marker.Discard):
                        m.next = "Discard"

            with m.State("Overflow"):
                m.d.comb += [
                    interrupt_now.eq(1),
                    # Flush the entire remaining queue; these are all of the good samples we've
                    # acquired. This might be more than the prolog plus epilog sizes! The frontend
                    # should be prepared to deal with this. The rationale for this behavior is:
                    # typically, when you hit an overflow condition, you want "as many samples as
                    # is physically feasible", as you're chasing an event at the margin of what
                    # the device is capable of.
                    request.i.p.meta.marker.eq(Marker.Overflow),
                    request.i.p.size.eq(queue_size),
                    request.i.valid.eq(queue_size > 0),
                ]
                with m.If(~request.i.valid | request.i.ready):
                    m.d.comb += barrier.o.ready.eq(1)
                    m.next = "Free-Run"

            with m.State("Discard"):
                m.d.comb += [
                    interrupt_now.eq(1),
                    request.i.p.skip.eq(1),
                    request.i.p.size.eq(queue_size),
                    request.i.valid.eq(queue_size > 0),
                ]
                with m.If(~request.i.valid | request.i.ready):
                    m.d.comb += barrier.o.ready.eq(1)
                    m.next = "Free-Run"

            def post_trigger_barrier():
                with m.If(barrier.o.valid):
                    with m.If(barrier.o.p.marker == Marker.Trigger):
                        m.d.comb += barrier.o.ready.eq(1)
                    with m.Elif(barrier.o.p.marker == Marker.Overflow):
                        m.d.sync += self.status.stall_count.eq(self.status.stall_count + 1)
                        m.next = "Overflow"
                    with m.Elif(barrier.o.p.marker == Marker.Discard):
                        m.next = "Discard"

            with m.State("Prolog"):
                m.d.comb += [
                    request.i.p.meta.eq(trigger_meta),
                    request.i.p.size.eq(queue_size), # (always at least 1 word)
                    request.i.valid.eq(1),
                ]
                with m.If(request.i.valid & request.i.ready):
                    with m.If(self.control.streaming):
                        m.next = "Streaming"
                    with m.Else():
                        m.next = "Epilog"
                post_trigger_barrier()

            with m.State("Streaming"):
                m.d.comb += [
                    request.i.p.size.eq(queue_size),
                    request.i.valid.eq(queue_size > 0),
                ]
                post_trigger_barrier()

            with m.State("Epilog"):
                m.d.comb += [
                    request.i.p.meta.marker.eq(Marker.Complete),
                    request.i.p.size.eq(self.control.epilog_size), # (always at least 1 word)
                    request.i.valid.eq(1),
                ]
                with m.If(request.i.valid & request.i.ready):
                    m.next = "Flush"
                post_trigger_barrier()

            with m.State("Flush"):
                with m.If(request.i.ready):
                    m.next = "Free-Run"
                post_trigger_barrier()

        m.d.comb += [
            self.status.free_running.eq(
                trigger_fsm.ongoing("Free-Run") |
                trigger_fsm.ongoing("Discard")
            ),
            self.status.overflow.eq(
                trigger_fsm.ongoing("Overflow")
            ),
            self.status.triggered.eq(
                trigger_fsm.ongoing("Prolog") |
                trigger_fsm.ongoing("Streaming") |
                trigger_fsm.ongoing("Epilog") |
                trigger_fsm.ongoing("Flush")
            ),
        ]

        return m


class AnalyzerCore(wiring.Component):
    CONTROL_SIGNATURE = wiring.Signature({
        "sampler": Out(PinSampler.CONTROL_SHAPE),
        "trigger": Out(BasicTrigger.CONTROL_SHAPE),
        "readout": Out(ReadControl.CONTROL_SHAPE),
        "events":  Out(stream.Signature(Event)),
    })

    STATUS_SIGNATURE = wiring.Signature({
        "sampler": Out(PinSampler.STATUS_SHAPE),
        "trigger": Out(BasicTrigger.STATUS_SHAPE),
        "writer":  Out(Writer.STATUS_SHAPE),
        "readout": Out(ReadControl.STATUS_SHAPE),
    })

    dram: Out(octoram.Signature())

    control: In(CONTROL_SIGNATURE)
    status: Out(STATUS_SIGNATURE)

    samples: Out(stream.Signature(data.StructLayout({
        "data": 8,
        "end":  1,
    })))

    def __init__(self, *, dram_range: range, burst_bytes: int, queue_bytes: int,
                 data_format: DataFormat, pins: io.PortLike):
        assert isinstance(data_format, DigitalFormat)

        self._dram_range  = dram_range
        self._burst_bytes = burst_bytes
        self._queue_bytes = queue_bytes
        self._data_format = data_format
        self._pins        = pins

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.sampler = sampler = PinSampler(format=self._data_format, pins=self._pins)
        m.d.comb += sampler.control.eq(self.control.sampler)
        m.d.comb += self.status.sampler.eq(sampler.status)

        # ----8<---- insert CDC here to sample at higher speed ----8<----

        m.submodules.trigger = trigger = BasicTrigger(format=self._data_format)
        m.d.comb += trigger.control.eq(self.control.trigger)
        m.d.comb += self.status.trigger.eq(trigger.status)
        wiring.connect(m, flipped(self.control.events), trigger.i_events)
        wiring.connect(m, sampler.o_samples, trigger.i_samples)

        m.submodules.breaker = breaker = CircuitBreaker()
        wiring.connect(m, trigger.o_samples, breaker.i_samples)

        m.submodules.arbiter = arbiter = Arbiter(
            queue_bytes=self._queue_bytes, burst_bytes=self._burst_bytes)
        wiring.connect(m, arbiter.dram, flipped(self.dram))

        m.submodules.writer = writer = Writer(
            dram_range=self._dram_range, burst_bytes=self._burst_bytes)
        wiring.connect(m, arbiter.w_cmd, writer.w_cmd)
        wiring.connect(m, arbiter.w_data, writer.w_data)
        m.d.comb += self.status.writer.eq(writer.status)

        m.submodules.reader = reader = Reader(
            dram_range=self._dram_range, burst_bytes=self._burst_bytes)
        wiring.connect(m, arbiter.r_cmd, reader.r_cmd)
        wiring.connect(m, arbiter.r_data, reader.r_data)

        m.submodules.write_ctrl = write_ctrl = WriteControl(
            writer_shape=writer.i_samples.p.shape(),
            writer_ratio=len(writer.i_samples.p.data),
            reader_shape=reader.o_octets.p.shape(),
            reader_ratio=1,
            max_credits=len(self._dram_range),
        )
        wiring.connect(m, breaker.o_samples, write_ctrl.i_writer)
        wiring.connect(m, write_ctrl.o_writer, writer.i_samples)
        wiring.connect(m, reader.o_octets, write_ctrl.i_reader)

        m.submodules.read_ctrl = read_ctrl = ReadControl(
            dram_range=self._dram_range, burst_bytes=self._burst_bytes)
        wiring.connect(m, writer.o_blocks, read_ctrl.w_blocks)
        wiring.connect(m, read_ctrl.r_blocks, reader.i_blocks)

        m.d.comb += [
            write_ctrl.prolog_size.eq(self.control.readout.prolog_size),
            write_ctrl.free_running.eq(read_ctrl.status.free_running),
            read_ctrl.control.eq(self.control.readout),
            self.status.readout.eq(read_ctrl.status),
        ]

        wiring.connect(m, write_ctrl.o_reader, flipped(self.samples))

        return m


class Command(enum.Enum, shape=8):
    IDENTIFY                = 0b10_000000
    GET_CLK_FREQUENCY       = 0b10_000001
    SET_CLK_DIVISOR         = 0b01_000010
    GET_CLK_DIVISOR         = 0b10_000010
    GET_BUFFER_SIZE         = 0b10_000011
    SET_PROLOG_SIZE         = 0b01_000100
    SET_EPILOG_SIZE         = 0b01_000101
    GET_DATA_FORMAT         = 0b10_000110
    SET_TRIGGER             = 0b01_010000
    GET_TRIGGER             = 0b10_010000
    GET_METADATA            = 0b10_010001
    SYNCHRONIZE             = 0b11_011111

    ARM_TRIGGER             = 0b00_000000
    FORCE_TRIGGER           = 0b00_000001
    DISARM_TRIGGER          = 0b00_000010
    INTERRUPT               = 0b00_000011

    TRIG_BASIC_SET_ACTIVE   = 0b01_100000
    TRIG_BASIC_SET_LEVEL    = 0b01_100001
    TRIG_BASIC_SET_VALUE    = 0b01_100010
    TRIG_BASIC_SET_ANYEDGE  = 0b01_100011


class DigitalTrigger(enum.Enum):
    """Trigger condition for a single digital input."""

    Disabled    = 0b0000
    FallingEdge = 0b0001
    RisingEdge  = 0b0101
    AnyEdge     = 0b1001
    LowLevel    = 0b0011
    HighLevel   = 0b0111


class CommandHandler(wiring.Component):
    command: In(stream.Signature(data.StructLayout({
        "cmd": data.StructLayout({
            "opcode":  5,
            "trigger": 1,
            "has_arg": 1,
            "has_ret": 1,
        }),
        "arg": 32,
    })))
    response: Out(stream.Signature(data.StructLayout({
        "ret": 32,
    })))
    metainfo: Out(stream.Signature(data.StructLayout({
        "data": 8,
        "end":  1,
    })))

    control: Out(AnalyzerCore.CONTROL_SIGNATURE)

    def __init__(self, *, ref_frequency: int, buffer_size: int, data_format: DataFormat,
                 probe_names: list[str] | None = None):
        self._ref_frequency = ref_frequency
        self._buffer_size   = buffer_size
        self._data_format   = data_format
        self._probe_names   = probe_names

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        # The writer bandwidth is "(16 - ε) bits/cycle"; ε is accounting for the small amount of
        # time (the exact value depends on block size) spent in the `Write-Data` and `Report-Block`
        # FSM states. Attempting to set a divisor corresponding to a bandwidth of 32 bits/cycle or
        # anything greater locks up the pipeline where it sends a single word with an overflow
        # trailer every time it is flushed, and no other data can be extracted. Since this is not
        # useful, the divisor is clamped to the minimum value.
        min_divisor_value = max(-1, 2 * self._data_format.stride // 32 - 1) + 1
        max_divisor_value = (1 << len(self.control.sampler.divisor)) - 1

        sampler = Signal(self.control.sampler.shape(), init={
            "divisor": min_divisor_value,
        })
        readout = Signal(self.control.readout.shape(), init={
            "prolog_size": 4,
            "epilog_size": 0,
            "streaming": 1,
        })
        trigger = Signal(self.control.trigger.shape())
        m.d.comb += [
            self.control.sampler.eq(sampler),
            self.control.readout.eq(readout),
            self.control.trigger.eq(trigger),
        ]

        meta_request = stream.Signature(0).create()

        with m.If(self.command.valid):
            with m.If(self.command.p.cmd.has_ret):
                m.d.comb += self.response.valid.eq(1)
                m.d.comb += self.command.ready.eq(self.response.ready)
            with m.Else():
                m.d.comb += self.command.ready.eq(1)

            def publish_event(event: Event):
                m.d.comb += self.control.events.payload.eq(event)
                m.d.comb += self.control.events.valid.eq(1)
                m.d.comb += self.command.ready.eq(self.control.events.ready) # override

            with m.Switch(self.command.p.cmd):
                # Commands (common)
                #
                with m.Case(Command.IDENTIFY):
                    m.d.comb += self.response.p.ret.eq(int.from_bytes(b"GLA0", "little"))

                with m.Case(Command.GET_CLK_FREQUENCY):
                    m.d.comb += self.response.p.ret.eq(self._ref_frequency)

                with m.Case(Command.GET_BUFFER_SIZE):
                    m.d.comb += self.response.p.ret.eq(self._buffer_size >> 2)

                with m.Case(Command.GET_DATA_FORMAT):
                    m.d.comb += self.response.p.ret.eq(self._data_format.fourcc)

                with m.Case(Command.SET_CLK_DIVISOR):
                    with m.If(self.command.p.arg < min_divisor_value):
                        m.d.sync += sampler.divisor.eq(min_divisor_value)
                    with m.Elif(self.command.p.arg > max_divisor_value):
                        m.d.sync += sampler.divisor.eq(max_divisor_value)
                    with m.Else():
                        m.d.sync += sampler.divisor.eq(self.command.p.arg)
                    publish_event(Event.Interrupt)

                with m.Case(Command.GET_CLK_DIVISOR):
                    m.d.comb += self.response.p.ret.eq(sampler.divisor)

                with m.Case(Command.SET_PROLOG_SIZE):
                    with m.If(self.command.p.arg == 0):
                        # Because all data is aligned to 32-bit words before trigger processing
                        # is done, there will be jitter (random offset between the trigger and
                        # the start of the capture) even for input data that is exactly the same
                        # (as long as it's not synchronized to the device clock). To ensure that
                        # accurate trigger position can be reported regardless, we enforce at least
                        # one word of pre-sample captured data is always output.
                        m.d.sync += readout.prolog_size.eq(4)
                    with m.Else():
                        m.d.sync += readout.prolog_size.eq(self.command.p.arg[:30] << 2)

                with m.Case(Command.SET_EPILOG_SIZE):
                    with m.If(self.command.p.arg == 0):
                        # Similar considerations to the ones described above, except for completion
                        # of the capture.
                        m.d.sync += readout.epilog_size.eq(4)
                    with m.Else():
                        m.d.sync += readout.epilog_size.eq(self.command.p.arg[:30] << 2)
                    m.d.sync += readout.streaming.eq(self.command.p.arg[31])

                with m.Case(Command.GET_TRIGGER):
                    m.d.comb += self.response.p.ret.eq(int.from_bytes(b"BASI", "little"))

                with m.Case(Command.SET_TRIGGER):
                    # Reset the trigger condition; we only support one trigger block.
                    m.d.sync += trigger.eq(trigger.as_value().init)

                with m.Case(Command.GET_METADATA):
                    if self._probe_names is not None:
                        m.d.comb += self.response.p.ret.eq(int.from_bytes(b"NAME", "little"))
                        with m.If(meta_request.ready):
                            m.d.comb += [
                                meta_request.valid.eq(1),
                                self.response.valid.eq(1),
                                self.command.ready.eq(self.response.ready)
                            ]
                        with m.Else():
                            m.d.comb += self.command.ready.eq(0)
                    else:
                        m.d.comb += self.response.p.ret.eq(0x00000000)

                with m.Case(Command.SYNCHRONIZE):
                    m.d.comb += self.response.p.ret.eq(self.command.p.arg)

                with m.Case(Command.ARM_TRIGGER):
                    publish_event(Event.EnableTrig)

                with m.Case(Command.FORCE_TRIGGER):
                    publish_event(Event.ForceTrig)

                with m.Case(Command.DISARM_TRIGGER):
                    publish_event(Event.DisableTrig)

                with m.Case(Command.INTERRUPT):
                    publish_event(Event.Interrupt)

                # Commands (basic trigger)
                #
                with m.Case(Command.TRIG_BASIC_SET_ACTIVE):
                    m.d.sync += Cat(trigger[i].active for i in range(32)).eq(self.command.p.arg)

                with m.Case(Command.TRIG_BASIC_SET_LEVEL):
                    m.d.sync += Cat(trigger[i].level for i in range(32)).eq(self.command.p.arg)

                with m.Case(Command.TRIG_BASIC_SET_VALUE):
                    m.d.sync += Cat(trigger[i].value for i in range(32)).eq(self.command.p.arg)

                with m.Case(Command.TRIG_BASIC_SET_ANYEDGE):
                    m.d.sync += Cat(trigger[i].anyedge for i in range(32)).eq(self.command.p.arg)

        if self._probe_names is not None:
            meta_data = b"".join(name.encode() + b"\x00" for name in self._probe_names)
            m.submodules.meta_mem = meta_mem = memory.Memory(
                shape=8, depth=len(meta_data), init=meta_data)

            meta_rdport = meta_mem.read_port()
            m.d.comb += self.metainfo.p.data.eq(meta_rdport.data)

            with m.FSM():
                with m.State("Idle"):
                    m.d.comb += meta_request.ready.eq(1)
                    with m.If(meta_request.ready & meta_request.valid):
                        m.d.sync += meta_rdport.addr.eq(0)
                        m.next = "Read"

                with m.State("Read"):
                    m.next = "Send"

                with m.State("Send"):
                    m.d.comb += self.metainfo.valid.eq(1)
                    with m.If(self.metainfo.valid & self.metainfo.ready):
                        m.d.sync += meta_rdport.addr.eq(meta_rdport.addr + 1)
                        with m.If(meta_rdport.addr == len(meta_data) - 1):
                            m.next = "Done"
                        with m.Else():
                            m.next = "Read"

                with m.State("Done"):
                    m.d.comb += self.metainfo.p.end.eq(1)
                    m.d.comb += self.metainfo.valid.eq(1)
                    with m.If(self.metainfo.valid & self.metainfo.ready):
                        m.next = "Idle"

        return m


class CommandParser(wiring.Component):
    command: Out(stream.Signature(data.StructLayout({
        "cmd": data.StructLayout({
            "opcode":  5,
            "trigger": 1,
            "has_arg": 1,
            "has_ret": 1,
        }),
        "arg": 32,
    })))
    response: In(stream.Signature(data.StructLayout({
        "ret": 32,
    })))

    i_stream: In(stream.Signature(8))
    o_stream: Out(stream.Signature(data.StructLayout({
        "data": 8,
        "end":  1,
    })))

    def elaborate(self, platform):
        m = Module()

        index = Signal(2)

        with m.FSM():
            with m.State("Command"):
                m.d.sync += self.command.p.cmd.eq(self.i_stream.payload)
                m.d.comb += self.i_stream.ready.eq(1)
                with m.If(self.i_stream.valid & self.i_stream.ready):
                    m.next = "Argument"

            with m.State("Argument"):
                with m.If(self.command.p.cmd.has_arg):
                    m.d.sync += self.command.p.arg.word_select(index, 8).eq(self.i_stream.payload)
                    m.d.comb += self.i_stream.ready.eq(1)
                    with m.If(self.i_stream.valid & self.i_stream.ready):
                        m.d.sync += index.eq(index + 1)
                        with m.If(index == 3):
                            with m.If(self.command.p.cmd.has_ret):
                                m.next = "Return"
                            with m.Else():
                                m.next = "Execute"
                with m.Else():
                    with m.If(self.command.p.cmd.has_ret):
                        m.next = "Return"
                    with m.Else():
                        m.next = "Execute"

            with m.State("Execute"):
                m.d.comb += self.command.valid.eq(1)
                with m.If(self.command.valid & self.command.ready):
                    m.next = "Command"

            with m.State("Return"):
                m.d.comb += self.command.valid.eq(1)
                m.d.comb += self.o_stream.p.data.eq(self.response.p.ret.word_select(index, 8))
                m.d.comb += self.o_stream.valid.eq(self.response.valid)
                with m.If(self.o_stream.valid & self.o_stream.ready):
                    m.d.sync += index.eq(index + 1)
                    with m.If(index == 3):
                        m.d.comb += self.response.ready.eq(1)
                        m.next = "End"

            with m.State("End"):
                m.d.comb += self.o_stream.p.end.eq(1)
                m.d.comb += self.o_stream.valid.eq(1)
                with m.If(self.o_stream.valid & self.o_stream.ready):
                    m.next = "Command"

        return m


class OutputMultiplexer(wiring.Component):
    i_stream_cmd: In(stream.Signature(data.StructLayout({
        "data": 8,
        "end":  1,
    })))
    i_stream_data: In(stream.Signature(data.StructLayout({
        "data": 8,
        "end":  1,
    })))
    i_stream_meta: In(stream.Signature(data.StructLayout({
        "data": 8,
        "end":  1,
    })))

    o_stream: Out(stream.Signature(data.StructLayout({
        "data": 8,
        "end":  1,
    })))

    def elaborate(self, platform):
        m = Module()

        # Used to ensure that data substreams are only interrupted at a word boundary.
        data_index = Signal(range(4))

        with m.FSM():
            with m.State("Idle"):
                with m.If(self.i_stream_cmd.valid):
                    m.d.comb += [
                        self.o_stream.p.data.eq(0), # substream 0
                        self.o_stream.valid.eq(1),
                    ]
                    with m.If(self.o_stream.valid & self.o_stream.ready):
                        m.next = "Command"
                with m.Elif(self.i_stream_meta.valid):
                    m.d.comb += [
                        self.o_stream.p.data.eq(2), # substream 2
                        self.o_stream.valid.eq(1),
                    ]
                    with m.If(self.o_stream.valid & self.o_stream.ready):
                        m.next = "Metadata"
                with m.Elif(self.i_stream_data.valid):
                    m.d.comb += [
                        self.o_stream.p.data.eq(1), # substream 1
                        self.o_stream.valid.eq(1),
                    ]
                    with m.If(self.o_stream.valid & self.o_stream.ready):
                        m.d.sync += data_index.eq(0)
                        m.next = "Data"

            with m.State("Command"):
                wiring.connect(m, flipped(self.i_stream_cmd), flipped(self.o_stream))
                with m.If(self.i_stream_cmd.valid & self.i_stream_cmd.ready &
                          self.i_stream_cmd.p.end):
                    m.next = "Idle"

            with m.State("Metadata"):
                wiring.connect(m, flipped(self.i_stream_meta), flipped(self.o_stream))
                with m.If(self.i_stream_meta.valid & self.i_stream_meta.ready &
                          self.i_stream_meta.p.end):
                    m.next = "Idle"

            with m.State("Data"):
                wiring.connect(m, flipped(self.i_stream_data), flipped(self.o_stream))
                with m.If(self.i_stream_data.valid & self.i_stream_data.ready):
                    with m.If(self.i_stream_data.p.end):
                        m.next = "Idle"
                    with m.Else():
                        m.d.sync += data_index.eq(data_index + 1)
                        with m.If(self.i_stream_cmd.valid & (data_index == 3)):
                            m.next = "Data-Interrupt"
                with m.Elif(self.i_stream_cmd.valid & (data_index == 0)):
                    m.next = "Data-Interrupt"

            with m.State("Data-Interrupt"):
                m.d.comb += [
                    # Inject a "continuation" trailer.
                    self.o_stream.p.data.eq(0x00),
                    self.o_stream.valid.eq(1),
                ]
                with m.If(self.o_stream.valid & self.o_stream.ready):
                    m.next = "End"

            with m.State("End"):
                m.d.comb += [
                    self.o_stream.p.end.eq(1),
                    self.o_stream.valid.eq(1),
                ]
                with m.If(self.o_stream.valid & self.o_stream.ready):
                    m.next = "Idle"

        return m


class StatusIndicator(wiring.Component):
    def __init__(self, *, ref_period: float, patterns: dict[str, list[tuple[bool, float]]]):
        self._ref_period = ref_period
        self._patterns   = patterns

        super().__init__({"o": Out(1), **{name: In(1) for name in patterns}})

    def elaborate(self, platform):
        m = Module()

        max_timer_limit = 0
        for states in self._patterns.values():
            for _led_state, led_time in states:
                max_timer_limit = max(max_timer_limit, int(led_time / self._ref_period))

        timer = Signal(range(max_timer_limit + 1))
        with m.FSM():
            patterns = list(self._patterns)
            for pattern, states in self._patterns.items():
                for state_idx, (led_state, led_time) in enumerate(states):
                    next_state_idx = (state_idx + 1) % len(states)
                    with m.State(f"{pattern}_{state_idx}"):
                        m.d.comb += self.o.eq(led_state)
                        with m.If(0):
                            pass
                        for next_pattern in self._patterns:
                            higher_prio = patterns.index(next_pattern) > patterns.index(pattern)
                            with m.Elif(getattr(self, next_pattern) &
                                    (higher_prio | ~getattr(self, pattern))):
                                m.d.sync += timer.eq(0)
                                m.next = f"{next_pattern}_0"
                        with m.Elif(timer == int(led_time / self._ref_period)):
                            m.d.sync += timer.eq(0)
                            m.next = f"{pattern}_{next_state_idx}"
                        with m.Else():
                            m.d.sync += timer.eq(timer + 1)

        return m


class AnalyzerComponent(wiring.Component):
    i_stream: In(stream.Signature(8))
    o_stream: Out(stream.Signature(8))
    o_flush: Out(1)

    indicator:   Out(1)

    status: Out(data.StructLayout({
        "triggered":    1,
        "wr_pointer":   32,
        "queue_size":   32,
        "stall_count":  4,
        # These two outputs indicate failure conditions that should never happen if the design
        # is correct.
        "sampler_fail": 1,
        "writer_fail":  1,
    }))

    def __init__(self, *, pins: io.PortLike, dram_bus: wiring.PureInterface, dram_range: range,
                 burst_bytes: int, queue_bytes: int, ref_frequency: int, ref_period: float,
                 probe_names: list[str] | None = None):
        self._pins          = pins
        self._dram_bus      = dram_bus
        self._dram_range    = dram_range
        self._burst_bytes   = burst_bytes
        self._queue_bytes   = queue_bytes
        self._ref_frequency = ref_frequency
        self._ref_period    = ref_period
        self._probe_names   = probe_names
        self._data_format   = DigitalFormat.for_width(len(self._pins))

        super().__init__()

    @property
    def data_format(self):
        return self._data_format

    def elaborate(self, platform):
        m = Module()

        m.submodules.core = core = AnalyzerCore(
            dram_range=self._dram_range,
            burst_bytes=self._burst_bytes,
            queue_bytes=self._queue_bytes,
            data_format=self._data_format,
            pins=self._pins,
        )
        wiring.connect(m, core.dram, self._dram_bus)
        m.d.comb += [
            self.status.sampler_fail.eq(core.status.sampler.overflow),
            self.status.wr_pointer.eq(core.status.writer.pointer),
            self.status.writer_fail.eq(core.status.writer.lockup),
            self.status.triggered.eq(core.status.readout.triggered),
            self.status.queue_size.eq(core.status.readout.queue_size),
            self.status.stall_count.eq(core.status.readout.stall_count),
        ]

        m.submodules.handler = handler  = CommandHandler(
            ref_frequency=self._ref_frequency,
            buffer_size=len(self._dram_range),
            data_format=self._data_format,
            probe_names=self._probe_names,
        )
        wiring.connect(m, core.control, handler.control)

        m.submodules.parser = parser = CommandParser()
        wiring.connect(m, flipped(self.i_stream), parser.i_stream)
        wiring.connect(m, parser.command, handler.command)
        wiring.connect(m, handler.response, parser.response)

        m.submodules.output_mux = output_mux = OutputMultiplexer()
        wiring.connect(m, parser.o_stream, output_mux.i_stream_cmd)
        wiring.connect(m, handler.metainfo, output_mux.i_stream_meta)
        wiring.connect(m, core.samples, output_mux.i_stream_data)

        m.submodules.cobs_encoder = cobs_encoder = cobs.Encoder()
        wiring.connect(m, output_mux.o_stream, cobs_encoder.i)
        wiring.connect(m, cobs_encoder.o, flipped(self.o_stream))
        m.d.comb += self.o_flush.eq(self.o_stream.payload == 0x00) # flush on COBS frame terminator

        m.submodules.indicator = indicator = StatusIndicator(
            ref_period=self._ref_period,
            patterns={
                # Later patterns have higher priority when multiple are selected.
                "idle":  [(0, 1.95), (1, 0.05)],
                "armed": [(1, 0.05), (0, 0.10), (1, 0.05), (0, 0.80)],
                "busy":  [(1, 0.20), (0, 0.20)],
                "error": [(1, 0.00)],
            }
        )
        m.d.comb += [
            self.indicator.eq(indicator.o),
            indicator.idle.eq(1),
            indicator.armed.eq(core.status.trigger.enabled),
            indicator.busy.eq(core.status.readout.triggered),
            indicator.error.eq(core.status.readout.overflow),
        ]

        return m


class AnalyzerError(GlasgowAppletError):
    pass


@dataclass(kw_only=True)
class SampleBlock:
    """A block of captured sample data."""

    samples: array[int]
    """32-bit words containing sample data.

    Use :meth:`AnalyzerInterface.get_data_format` to determine the meaning of bits within each word.
    """

    marker: Marker
    """Indicator of the special nature of the last word of sample data."""

    offset: int = 0
    """Sub-word location of the marker, as a bit offset from LSB.

    Only meaningful if :py:`marker == Marker.Trigger`.
    """


class AnalyzerInterface:
    _QUEUE_BYTES = 512

    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
                 probes: list[GlasgowPin] | dict[str, GlasgowPin], buffer_size: int | None = None):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        match probes:
            case list():
                probe_pins  = tuple(probes)
                probe_names = None
            case dict():
                probe_pins  = tuple(probes.values())
                probe_names = list(probes.keys())

        ports = assembly.add_port_group(pins=probe_pins)
        dram_bus, dram_range = assembly.add_dynamic_memory(DRAMOptions(
            size=buffer_size,
            r_buffer_size=self._QUEUE_BYTES,
            w_buffer_size=self._QUEUE_BYTES,
        ))
        component = assembly.add_submodule(AnalyzerComponent(
            pins=ports.pins,
            dram_bus=dram_bus,
            dram_range=dram_range,
            burst_bytes=self._QUEUE_BYTES // 4,
            queue_bytes=self._QUEUE_BYTES,
            ref_frequency=int(1 / assembly.sys_clk_period),
            ref_period=assembly.sys_clk_period,
            probe_names=probe_names,
        ))
        self._pipe = assembly.add_inout_pipe(
            component.o_stream, component.i_stream, in_flush=component.o_flush)
        assembly.add_indicator(component.indicator, name="status")

        self._buffer_size = len(dram_range)
        self._data_format = component.data_format
        self._status_reg = assembly.add_ro_register(component.status)

    def _log(self, message: str, *args):
        self._logger.log(self._level, "analyzer: " + message, *args)

    async def _recv_substream(self, index: int) -> tuple[int, bytearray]:
        frame = await self._pipe.recv_until(b"\x00")
        payload = memoryview(cobs.decode(frame[:-1]))
        assert payload[0] == index, f"expected substream {index}"
        data = payload[1:]
        if index != 0:
            self._log("[%d] <%s>", index, logging.dump_hex(data))
        return data

    async def _do_command(self, cmd: Command, arg: int | None = None) -> int | None:
        has_ret = bool(cmd.value & 0x80)
        has_arg = bool(cmd.value & 0x40)
        assert (has_arg is False) == (arg is None)

        if has_arg:
            await self._pipe.send(struct.pack("<BL", cmd.value, arg))
        else:
            await self._pipe.send(struct.pack("<B", cmd.value))
        await self._pipe.flush()
        if has_ret:
            ret, = struct.unpack("<L", await self._recv_substream(0))
        else:
            ret = None

        if has_arg and has_ret:
            self._log("%s(%08x) -> %08x", cmd.name, arg, ret)
        elif has_arg:
            self._log("%s(%08x)", cmd.name, arg)
        elif has_ret:
            self._log("%s -> %08x", cmd.name, ret)
        else:
            self._log("%s", cmd.name)

        return ret

    async def identify(self) -> bytes:
        """Identify the protocol version.

        See the documentation for the :cmd:`IDENTIFY` protocol command.

        Returns :py:`GLA0`.
        """
        fourcc = await self._do_command(Command.IDENTIFY)
        return fourcc.to_bytes(4, "little")

    async def get_probe_names(self) -> None | list[str]:
        """Retrieve the probe names, if any.

        See the documentation for the :cmd:`GET_METADATA` protocol command.

        Returns a list of probe names, or :py:`None` if none were provided. This list is fixed
        for a particular analyzer instance.
        """
        fourcc = await self._do_command(Command.GET_METADATA)
        if fourcc == 0x00000000:
            return None
        elif fourcc == int.from_bytes(b"NAME", "little"):
            metadata = bytes(await self._recv_substream(2))
            return [name.decode() for name in metadata.split(b"\x00")[:-1]]
        else:
            raise AnalyzerError(f"unknown metadata format {fourcc.to_bytes(4, "little")!r}")

    async def get_ref_frequency(self) -> int:
        """Retrieve the reference frequency.

        See the documentation for the :cmd:`GET_CLK_FREQUENCY` protocol command.

        Returns the reference frequency in Hz. This value is fixed for a particular analyzer
        instance.
        """
        return await self._do_command(Command.GET_CLK_FREQUENCY)

    async def get_sampling_rate(self) -> float:
        """Retrieve the configured sample rate.

        See the documentation for the :cmd:`GET_CLK_DIVISOR` protocol command.

        Returns the sampling frequency in Hz. This value can be changed with
        :meth:`set_sampling_rate`.
        """
        ref_freq = await self._do_command(Command.GET_CLK_FREQUENCY)
        divisor  = await self._do_command(Command.GET_CLK_DIVISOR)
        return ref_freq / (divisor + 1)

    async def set_sampling_rate(self, rate: float, *, tolerance=0.05):
        """Configure the sampling rate.

        See the documentation for the :cmd:`SET_CLK_DIVISOR` protocol command.

        Sets the sampling frequency to :py:`rate` Hz.

        Raises
        ------
        AnalyzerError
            If the sample rate achieved via an integer divisor has an error of more than
            :py:`tolerance` (5% by default).
        AnalyzerError
            If the sample rate cannot be achieved because the required data transfer rate exceeds
            available memory bandwidth.
        AnalyzerError
            If the sample rate cannot be achieved because the divisor register is not sufficiently
            wide in this analyzer instance.
        """
        # round to lower divisor -> higher sample rate
        ref_freq = await self._do_command(Command.GET_CLK_FREQUENCY)
        divisor = max(0, int(ref_freq / rate) - 1)
        actual_rate = ref_freq / (divisor + 1)
        if abs(actual_rate - rate) / rate > tolerance:
            raise AnalyzerError(f"requested sampling rate is not achievable "
                f"(closest achievable rate {actual_rate} Hz has error "
                f"exceeding {tolerance * 100:.2f}%)")

        await self._do_command(Command.SET_CLK_DIVISOR, divisor)
        actual_divisor = await self._do_command(Command.GET_CLK_DIVISOR)
        if actual_divisor > divisor:
            raise AnalyzerError(
                "requested sampling rate is not achievable (limited by memory bandwidth)")
        if actual_divisor < divisor:
            raise AnalyzerError(
                "requested sampling rate is not achievable (limited by divisor register size)")

    async def get_buffer_size(self) -> int:
        """Retrieve the size of the sampling buffer.

        See the documentation for the :cmd:`GET_BUFFER_SIZE` protocol command.

        Returns the size of the sampling buffer in 32-bit words. This value is fixed for
        a particular analyzer instance.
        """
        return await self._do_command(Command.GET_BUFFER_SIZE)

    async def set_prolog_size(self, size: int):
        """Configure the size of the prolog.

        See the documentation for the :cmd:`SET_PROLOG_SIZE` protocol command.

        Sets the size of the pre-trigger sampling interval, also known as the prolog, to :py:`size`
        32-bit words. The minimum size of the prolog is 1 word, and the hardware will clamp a size
        of zero words to that minimum value.

        Raises
        ------
        AnalyzerError
            If :py:`size` is negative.
        AnalyzerError
            If :py:`size` is greater than or equal to the sampling buffer size.
        """
        buffer_size = await self.get_buffer_size()
        if not (0 <= size < buffer_size):
            raise AnalyzerError("prolog size must be non-negative and less than buffer size")
        await self._do_command(Command.SET_PROLOG_SIZE, size)

    async def set_epilog_size(self, size: int):
        """Configure the size of the epilog.

        See the documentation for the :cmd:`SET_EPILOG_SIZE` protocol command.

        Sets the size of the post-trigger sampling interval, also known as the epilog, to :py:`size`
        32-bit words. The minimum size of the epilog is 1 word, and the hardware will clamp a size
        of zero words to that minimum value.

        Raises
        ------
        AnalyzerError
            If :py:`size` is negative or too large.
        """
        if not (0 <= size < 0x8000_0000):
            raise AnalyzerError("epilog size must be non-negative")
        await self._do_command(Command.SET_EPILOG_SIZE, size)

    async def use_streaming(self):
        """Configure the epilog to continue indefinitely.

        See the documentation for the :cmd:`SET_EPILOG_SIZE` protocol command.

        Causes the post-trigger sampling interval to extend indefinitely. The sample read-out, in
        this case, is only interrupted by a pipeline overflow or an explicit :meth:`interrupt` call.
        """
        await self._do_command(Command.SET_EPILOG_SIZE, 0x8000_0000)

    async def get_data_format(self) -> DataFormat:
        """Retrieve the format of sample data words.

        See the documentation for the :cmd:`GET_DATA_FORMAT` protocol command.

        Returns a value describing how to interpret the bits in each 32-bit sample word.
        The following data formats exist:

        * :class:`DigitalFormat`
        """
        fourcc = await self._do_command(Command.GET_DATA_FORMAT)
        if fourcc & 0xffff0000 == int.from_bytes(b"\0\0DI", "little"):
            return DigitalFormat(width=(fourcc>>0)&0x1f, stride=(fourcc>>8)&0x1f)
        else:
            # Should not happen unless the RTL is modified.
            raise AnalyzerError(f"unknown data format {fourcc.to_bytes(4, "little")!r}")

    async def use_basic_trigger(self, condition: dict[int, DigitalTrigger]):
        r"""Configure the basic trigger module.

        See the documentation for the :cmd:`SET_TRIGGER`, :cmd:`TRIG_BASIC_SET_ACTIVE`,
        :cmd:`TRIG_BASIC_SET_LEVEL`, :cmd:`TRIG_BASIC_SET_VALUE`, and :cmd:`TRIG_BASIC_SET_ANYEDGE`
        protocol commands.

        Configures the analyzer to trigger when any (logic OR) of the per-probe trigger
        :py:`condition`\ s match the sampled values.
        """
        fourcc = int.from_bytes(b"BASI", "little")
        await self._do_command(Command.SET_TRIGGER, fourcc)
        if fourcc != await self._do_command(Command.GET_TRIGGER):
            # Should not happen unless the RTL is modified.
            raise AnalyzerError("basic trigger not supported")

        active = level = value = anyedge = 0
        for channel, mode in condition.items():
            if not channel < 32:
                raise AnalyzerError(f"channel {channel} does not exist")
            active  |= (1 if mode.value & 1 else 0) << channel
            level   |= (1 if mode.value & 2 else 0) << channel
            value   |= (1 if mode.value & 4 else 0) << channel
            anyedge |= (1 if mode.value & 8 else 0) << channel
        await self._do_command(Command.TRIG_BASIC_SET_ACTIVE,  active)
        await self._do_command(Command.TRIG_BASIC_SET_LEVEL,   level)
        await self._do_command(Command.TRIG_BASIC_SET_VALUE,   value)
        await self._do_command(Command.TRIG_BASIC_SET_ANYEDGE, anyedge)

    async def arm_trigger(self):
        """Enable the trigger module.

        See the documentation for the :cmd:`ARM_TRIGGER` protocol command.

        The trigger module is disabled after it encounters samples matching the configured condition
        and starting the sample read-out process.
        """
        await self._do_command(Command.ARM_TRIGGER)

    async def force_trigger(self):
        """Force a trigger condition to occur.

        See the documentation for the :cmd:`FORCE_TRIGGER` protocol command.

        The trigger module is disabled after starting the sample read-out process.
        """
        await self._do_command(Command.FORCE_TRIGGER)

    async def disarm_trigger(self):
        """Disable the trigger module.

        See the documentation for the :cmd:`ARM_TRIGGER` protocol command.
        """
        await self._do_command(Command.DISARM_TRIGGER)

    async def interrupt(self):
        """Interrupt the sample read-out process and flush pipeline.

        See the documentation for the :cmd:`INTERRUPT` protocol command.
        """
        await self._do_command(Command.INTERRUPT)

    async def read_sample_block(self) -> SampleBlock:
        """Read captured samples.

        See the protocol documentation for the sample data sequences.

        Currently, this function *must* be used to read out all sample data before another command
        will execute correctly. This is a limitation of the Python API.
        """
        words = array("I")
        assert words.itemsize == 4, "array 'I' typecode does not correspond to 32-bit words"
        block_data = await self._recv_substream(1)
        assert len(block_data) % 4 == 1, "received invalid data frame"
        words.frombytes(block_data[:-1])
        if sys.byteorder == "big":
            words.byteswap()
        return SampleBlock(
            samples=words,
            marker=Marker(block_data[-1] >> 5),
            offset=block_data[-1] & 0x1f,
        )

    async def _monitor_queue_size(self):
        old_status = await self._status_reg.get()
        while True:
            await asyncio.sleep(1.0)
            new_status = await self._status_reg.get()
            self._log("status: wr_pointer=%08x queue_size=%08x triggered=%d",
                new_status.wr_pointer, new_status.queue_size, new_status.triggered)

            size_delta = abs(new_status.queue_size - old_status.queue_size)
            if (new_status.triggered and new_status.queue_size > old_status.queue_size and
                    size_delta > 0.1 * self._buffer_size):
                exhausted_in = (self._buffer_size - new_status.queue_size) / size_delta
                self._logger.warning("capture buffer filling up at %.1f MB/s (stall in %.1f s)",
                    size_delta / 1e6, exhausted_in)

            if new_status.stall_count != old_status.stall_count:
                self._logger.error("capture buffer space exhausted")

            if new_status.sampler_fail:
                self._logger.error("BUG: sampler failure; please reproduce and report an issue")
                break
            if new_status.writer_fail:
                self._logger.error("BUG: writer failure; please reproduce and report an issue")
                break

            old_status = new_status


class AnalyzerApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "sample values of digital inputs as they change in time"
    description = """
    Capture values of digital inputs as a time series sequence.

    At the moment, this applet is designed primarily for use with external tools or in script/REPL
    mode. When ran normally, it listens on a TCP port and exposes an open protocol that frontend
    applications like Sigrok can use.

    First, configure the probes and voltage level:

    ::

        glasgow run analyzer2 -V A=3.3 CMD=A0 CLK=A1 DAT=A2:5

    Then, run Sigrok:

    ::

        sigrok-cli -d glasgow:conn=tcp-raw/127.0.0.1/5555 -c samplerate=12m --samples 10000

    Or, run PulseView (you can also configure the connection in the GUI):

    ::

        pulseview -d glasgow:conn=tcp-raw/127.0.0.1/5555
    """
    analyzer_iface: AnalyzerInterface

    @classmethod
    def add_build_arguments(cls, parser: argparse.ArgumentParser, access):
        def probe(arg):
            if m := re.match(r"^(.+)=([A-Z0-9:]+)$", arg):
                probe_name, pin_arg = m[1], m[2]
            else:
                probe_name, pin_arg = None, arg
            match GlasgowPin.parse(pin_arg):
                case ():
                    return []
                case (pin,):
                    return [(probe_name, pin)]
                case pins:
                    return [
                        (f"{probe_name}{index}", pin) if probe_name else (None, pin)
                        for index, pin in enumerate(pins)
                    ]

        def length(arg):
            return int(arg, 0)

        access.add_voltage_argument(parser)
        parser.add_argument(
            "--buffer-size", metavar="SIZE", type=length,
            help="use SIZE bytes for capture buffer (e.g. 0x100000 for 1 MB)")
        parser.add_argument(
            "probes", metavar="PROBES", nargs="+", type=probe,
            help="probe I/O lines PROBES, optionally naming them (e.g.: A0, A0:1, DATA=B0)")

    def build(self, args):
        probe_args = reduce(lambda a, b: a + b, args.probes)
        if any(probe_arg[0] for probe_arg in probe_args):
            probes = {arg[0] or f"{idx}": arg[1] for idx, arg in enumerate(probe_args)} # some named
        else:
            probes = [arg[1] for arg in probe_args] # unnamed only

        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.analyzer_iface = AnalyzerInterface(self.logger, self.assembly,
                probes=probes, buffer_size=args.buffer_size)

    @classmethod
    def add_run_arguments(cls, parser):
        parser.add_argument(
            "--listen", dest="endpoint", metavar="ENDPOINT", type=endpoint, nargs="?",
            default=("tcp", "localhost", 5555),
            help="listen at ENDPOINT, either unix:PATH or tcp:HOST:PORT "
                 "(default: tcp:localhost:5555)"
        )

    async def run(self, args):
        endpoint = await ServerEndpoint("socket", self.logger, args.endpoint)
        async with asyncio.TaskGroup() as group:
            group.create_task(self.analyzer_iface._monitor_queue_size())
            group.create_task(endpoint.attach_to_pipe(self.analyzer_iface._pipe))

    @classmethod
    def tests(cls):
        from . import test
        return test.AnalyzerAppletTestCase
