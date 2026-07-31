# The analyzer applet can be broken into a few functional units:
#  * The trigger units analyzes the incoming data and generates the trigger signal.
#  * The packer units converts raw sampled data into 32-bit words.
#  * The storage/readout units stores sample bytes (opaque to this units) and pushes them out
#    to the USB pipe. It keeps track of the trigger pointer and pre-trigger data region. It is,
#    essentially, a FIFO with special handling of read pointer and overflows.
#  * The bridge units TBD
#
# Unusually for Glasgow gateware, the units share a fixed-size, 32-bit data path. This is done
# because the analyzer is designed for interfacing with external software, some of which may be
# written in a way that makes complex and generic bitwise transformations unreasonably difficult.


from amaranth import *
from amaranth.utils import ceil_log2
from amaranth.lib import data, wiring, stream, io
from amaranth.lib.wiring import In, Out, flipped

from glasgow.support import logging
from glasgow.gateware import octoram
from glasgow.gateware.stream import Queue
from glasgow.abstract import AbstractAssembly, GlasgowPin
from glasgow.applet import GlasgowAppletV2


__all__ = []


class Sampler(wiring.Component):
    """Sampler unit.

    Samples pins at an interval specified by a divisor.
    """

    divisor: In(24)

    o_samples: Out(stream.Signature(data.StructLayout({
        "data": 32,
    }), always_ready=True))

    def __init__(self, pins: io.PortLike):
        self._pins = pins

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.i_buf = i_buf = io.FFBuffer("i", self._pins)
        m.d.comb += self.o_samples.p.data.eq(i_buf.i)

        timer = Signal.like(self.divisor)
        with m.If(timer == 0):
            m.d.comb += self.o_samples.valid.eq(1)
            m.d.sync += timer.eq(self.divisor)
        with m.Else():
            m.d.sync += timer.eq(timer - 1)

        return m


class Trigger(wiring.Component):
    """Trigger unit.

    Compares input data with a trigger mode, marking samples that match.
    """

    class Mode(data.Struct):
        active: 1
        value:  1
        level:  1

    mode: In(data.ArrayLayout(Mode, 32))

    i_samples: In(stream.Signature(data.StructLayout({
        "data": 32,
    }), always_ready=True))
    o_samples: Out(stream.Signature(data.StructLayout({
        "data": 32,
        "trig": 1,
    }), always_ready=True))

    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.d.comb += [
            self.o_samples.p.data.eq(self.i_samples.p.data),
            self.o_samples.valid.eq(self.i_samples.valid),
        ]

        for mode, curr_bit in zip(self.mode, self.i_samples.p.data):
            prev_bit = Signal.like(curr_bit)
            with m.If(self.i_samples.valid):
                m.d.sync += prev_bit.eq(curr_bit)
            with m.If(mode.active & (curr_bit == mode.value)):
                with m.If(mode.level | (prev_bit != curr_bit)):
                    m.d.comb += self.o_samples.p.trig.eq(1)

        return m


class Packer(wiring.Component):
    """Packer unit.

    Converts 32-bit samples with some amount of unused MSBs into 4-byte packed samples that consist
    of a concatenation of used LSBs (and possibly padding).

    Currently, the (real) sample width is configured statically.
    """

    TRIG_SHAPE = data.StructLayout({
        "active": 1,
        "offset": range(32),
    })

    i_samples: In(stream.Signature(data.StructLayout({
        "data": 32,
        "trig": 1,
    }), always_ready=True))
    o_packed: Out(stream.Signature(data.StructLayout({
        "data": data.ArrayLayout(8, 4),
        "trig": TRIG_SHAPE,
    }), always_ready=True))

    i_credits: In(stream.Signature(range(32+1), always_ready=True))
    overflow:  Out(1)

    def __init__(self, *, width: int, max_credits: int):
        assert width in range(1, 33)

        self._width = width
        self._width_pow2 = 1 << ceil_log2(self._width)
        self._max_credits = max_credits

        super().__init__()

    @property
    def samples_per_word(self):
        return len(self.i_samples.p.data) // self._width_pow2

    def elaborate(self, platform):
        m = Module()

        pack = Signal(self._width_pow2)
        m.d.comb += pack.eq(self.i_samples.p.data[:self._width])

        packs = self.samples_per_word
        count = Signal(range(packs))
        trig  = Signal(self.TRIG_SHAPE)

        for index in range(packs - 1):
            with m.If(self.i_samples.valid & (count == index)):
                m.d.sync += self.o_packed.p.data.as_value().word_select(index, len(pack)).eq(pack)
                with m.If(self.i_samples.p.trig & ~trig.active):
                    m.d.sync += trig.active.eq(1)
                    m.d.sync += trig.offset.eq(count * len(pack))

        m.d.comb += self.o_packed.p.data.as_value().word_select(packs - 1, len(pack)).eq(pack)
        with m.If(self.i_samples.p.trig & ~trig.active):
            m.d.comb += self.o_packed.p.trig.active.eq(self.i_samples.p.trig)
            m.d.comb += self.o_packed.p.trig.offset.eq((packs - 1) * len(pack))
        with m.Else():
            m.d.comb += self.o_packed.p.trig.eq(trig)

        credits = Signal(range(self._max_credits + 1))
        next_credits1 = credits       + Mux(self.i_credits.valid, self.i_credits.payload, 0)
        next_credits2 = next_credits1 - Mux(self.o_packed.valid, count + 1, 0)
        with m.If(next_credits2 <= self._max_credits):
            m.d.sync += credits.eq(next_credits2)

        with m.If(self.i_samples.valid & ~self.overflow):
            next_count = count + 1
            m.d.sync += count.eq(next_count)
            with m.If(next_count == packs):
                with m.If(next_count <= next_credits1):
                    m.d.sync += trig.eq(0)
                    m.d.comb += self.o_packed.valid.eq(1)
                with m.Else():
                    m.d.sync += self.overflow.eq(1)

        return m


class Writer(wiring.Component):
    """Writer unit.

    Writes 4-byte packed samples to memory in bursts. Essentially a specialized write-combining
    cache. Outputs blocks (ranges of bytes with an optional trigger) once the write is committed
    to memory; the trigger, if active, is always at the last sample of the block.
    """

    dram: Out(octoram.Signature())

    i_packed: In(stream.Signature(data.StructLayout({
        "data": data.ArrayLayout(8, 4),
        "trig": Packer.TRIG_SHAPE,
    })))
    o_blocks: Out(stream.Signature(data.StructLayout({
        "addr": 32, # 4-byte aligned
        "size": 8,  # 4-byte multiple
        "trig": Packer.TRIG_SHAPE,
    })))

    def __init__(self, *, dram_range: range):
        self._dram_range  = dram_range
        self._burst_bytes = 32

        assert self._dram_range.start % self._burst_bytes == 0
        assert self._dram_range.stop % self._burst_bytes == 0

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        # Queue blocks once enough samples are buffered. This smoothes over the intervals when
        # the writer loses arbitration (it has priority, but reads are uninterruptible) and allows
        # filling the entire write queue.
        m.submodules.block_queue = block_queue = Queue(
            shape=self.o_blocks.p.shape(), depth=4)
        block_ready = Signal()
        m.d.comb += [
            # Output the fact that block has been committed...
            self.o_blocks.payload.eq(block_queue.o.payload),
            self.o_blocks.valid.eq(block_queue.o.valid & block_ready),
            block_queue.o.ready.eq(self.o_blocks.ready & block_ready),
            # ... and write the block itself...
            self.dram.commands.p.type.eq(octoram.Command.WriteMemRow),
            self.dram.commands.p.addr.eq(block_queue.o.p.addr),
            self.dram.commands.p.size.eq(block_queue.o.p.size >> 1),
            self.dram.commands.valid.eq(block_queue.o.valid & block_ready),
            block_queue.o.ready.eq(self.dram.commands.ready & block_ready),
            # ... at the exact same time.
            block_ready.eq(self.dram.commands.ready & self.o_blocks.ready),
        ]

        # Buffer 4-byte packed sample bursts. Sized for two bursts worth of samples so that one
        # half can be filled while the other half is being drained.
        m.submodules.w_queue = w_queue = Queue(
            shape=data.ArrayLayout(8, 4), depth=(self._burst_bytes >> 2) * 2)
        m.d.comb += [
            w_queue.i.payload.eq(Cat(self.i_packed.p.data)),
            w_queue.i.valid.eq(self.i_packed.valid),
            self.i_packed.ready.eq(w_queue.i.ready),
        ]

        # Convert 4-byte packed samples into 2-byte memory beats.
        w_phase = Signal()
        m.d.comb += [
            self.dram.w_data.p[0].data.eq(Mux(w_phase, w_queue.o.payload[2], w_queue.o.payload[0])),
            self.dram.w_data.p[1].data.eq(Mux(w_phase, w_queue.o.payload[3], w_queue.o.payload[1])),
            self.dram.w_data.valid.eq(w_queue.o.valid),
            w_queue.o.ready.eq(self.dram.w_data.ready & w_phase),
        ]
        with m.If(self.dram.w_data.valid & self.dram.w_data.ready):
            m.d.sync += w_phase.eq(~w_phase)

        # Issue memory write commands.
        w_pointer = Signal(self._dram_range, init=self._dram_range.start)
        w_advance = Signal(range(self._burst_bytes + 1))
        with m.If(w_advance):
            m.d.sync += w_pointer.eq(w_pointer + w_advance)
            with m.If(w_pointer + w_advance == self._dram_range.stop):
                m.d.sync += w_pointer.eq(w_pointer.init)
        m.d.comb += [
            block_queue.i.p.addr.eq(w_pointer),
            block_queue.i.p.size.eq(w_advance),
            block_queue.i.p.trig.eq(self.i_packed.p.trig),
            block_queue.i.valid.eq(w_advance != 0),
        ]

        # Maintain a count of entries (not bytes) pushed to the write queue but not yet committed
        # to a burst.
        w_pending = Signal.like(w_queue.level)
        m.d.sync += w_pending.eq(w_pending
            + (w_queue.i.valid & w_queue.i.ready)
            - (w_advance // len(w_queue.i.payload)))

        # Drain (write) the buffer if the next burst would cross a burst-aligned block boundary.
        # This takes care of these three important cases:
        #  * Complete burst must be written.
        #  * Partial burst must be written to avoid crossing a (2K) row boundary.
        #  * Partial burst must be written to wrap at the end of memory region.
        # Sometimes the buffer will be drained without it being strictly required, but that's OK.
        # Also drain on explicit flush.
        next_level_bytes = (w_pending + 1) * len(w_queue.i.payload)
        with m.If((((w_pointer + next_level_bytes) & (self._burst_bytes - 1)) == 0) |
                  self.i_packed.p.trig.active):
            with m.If(w_queue.i.valid & w_queue.i.ready & block_queue.i.ready):
                m.d.comb += w_advance.eq(next_level_bytes)

        return m


class Reader(wiring.Component):
    """Reader unit.

    Reads the contents of the specified ranges from memory.
    """

    dram: Out(octoram.Signature())

    i_ranges: In(stream.Signature(data.StructLayout({
        "start":  32, # 4-byte aligned
        "count":  32, # 4-byte aligned
    })))
    o_octets: In(stream.Signature(8))

    def __init__(self, *, dram_range: range):
        self._dram_range  = dram_range
        self._burst_bytes = 32

        assert self._dram_range.start % self._burst_bytes == 0
        assert self._dram_range.stop % self._burst_bytes == 0

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        # Buffer 2-byte memory beats. Sized for two bursts worth of samples so that one half can
        # be filled while the other half is being drained.
        m.submodules.r_queue = r_queue = Queue(
            shape=data.ArrayLayout(8, 2), depth=(self._burst_bytes >> 1) * 2)
        wiring.connect(m, flipped(self.dram.r_data), r_queue.i)

        # Convert 2-byte memory beats into output octets.
        r_phase = Signal()
        m.d.comb += [
            self.o_octets.payload.eq(r_queue.o.payload[r_phase]),
            self.o_octets.valid.eq(r_queue.o.valid),
            r_queue.o.ready.eq(self.o_octets.ready & r_phase),
        ]
        with m.If(self.o_octets.valid & self.o_octets.ready):
            m.d.sync += r_phase.eq(~r_phase)

        # Issue memory read commands.
        r_length  = Signal.like(self.i_ranges.p.count)
        r_pointer = Signal(self._dram_range)
        r_active  = Signal()
        r_advance = Signal(range(self._burst_bytes + 1))
        with m.If(~r_active):
            m.d.sync += r_length.eq(0)
            m.d.sync += r_pointer.eq(self.i_ranges.p.start)
        with m.Elif(self.dram.commands.ready):
            m.d.sync += r_length.eq(r_length + r_advance)
            m.d.sync += r_pointer.eq(r_pointer + r_advance)
            with m.If(r_pointer + r_advance == self._dram_range.stop):
                m.d.sync += r_pointer.eq(self._dram_range.start)
        m.d.comb += [
            self.dram.commands.p.type.eq(octoram.Command.ReadMemRow),
            self.dram.commands.p.addr.eq(r_pointer),
            self.dram.commands.p.size.eq(r_advance >> 1),
            self.dram.commands.valid.eq(r_advance != 0),
        ]

        # Maintain a count of entries (not bytes) pushed to the write queue but not yet committed
        # to a burst.
        r_pending = Signal.like(r_queue.level)
        m.d.sync += r_pending.eq(r_pending
            + (r_queue.i.valid & r_queue.i.ready)
            - (r_advance // len(r_queue.i.payload)))

        # Refill the buffer up to the next burst boundary (or until the end of the requested range).
        free_queue_bytes = (r_queue.depth - r_pending) * len(r_queue.i.payload)
        with m.If(r_active & (free_queue_bytes > self._burst_bytes)):
            remainder_bytes  = self.i_ranges.p.count - r_length
            next_burst_bytes = self._burst_bytes - (r_pointer & (self._burst_bytes - 1))
            with m.If(next_burst_bytes < remainder_bytes):
                m.d.comb += r_advance.eq(next_burst_bytes)
            with m.Elif(remainder_bytes < self._burst_bytes):
                m.d.comb += r_advance.eq(remainder_bytes)
            with m.Else():
                m.d.comb += r_advance.eq(self._burst_bytes)

        with m.FSM():
            with m.State("Idle"):
                with m.If(self.i_ranges.valid):
                    m.next = "Readout"

            with m.State("Readout"):
                m.d.comb += r_active.eq(1)
                with m.If(r_length + r_advance == self.i_ranges.p.count):
                    m.d.comb += self.i_ranges.ready.eq(self.dram.commands.ready)
                    m.next = "Idle"

        return m


class Arbiter(wiring.Component):
    """Reader/writer arbitration unit.

    A specialized arbiter that takes the particular access patterns of the analyzer into account,
    i.e. that the reader never writes and the writer never reads. The writer has priority.
    """

    dram: Out(octoram.Signature())

    writer: In(octoram.Signature())
    reader: In(octoram.Signature())

    def elaborate(self, platform):
        m = Module()

        wiring.connect(m, flipped(self.writer.w_data), flipped(self.dram.w_data))
        wiring.connect(m, flipped(self.dram.r_data), flipped(self.reader.r_data))

        # Writer has priority.
        with m.If(self.writer.commands.valid):
            wiring.connect(m, flipped(self.writer.commands), flipped(self.dram.commands))
        with m.Else():
            wiring.connect(m, flipped(self.reader.commands), flipped(self.dram.commands))

        return m


class AnalyzerCore(wiring.Component):
    dram: Out(octoram.Signature())

    divisor:  In(24)
    triggers: In(data.ArrayLayout(Trigger.Mode, 32))
    samples:  Out(stream.Signature(8))

    precap_count: In(32) # in samples, not packed samples
    total_count:  In(32) # also

    def __init__(self, *, pins: io.PortLike, dram_range: range):
        self._pins = pins
        self._dram_range = dram_range

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.sampler = sampler = Sampler(self._pins)
        m.d.comb += sampler.divisor.eq(self.divisor)

        m.submodules.trigger = trigger = Trigger()
        m.d.comb += trigger.mode.eq(self.triggers)
        wiring.connect(m, sampler.o_samples, trigger.i_samples)

        m.submodules.packer = packer = Packer(width=len(self._pins))
        wiring.connect(m, packer.i_samples, trigger.o_samples)

        m.submodules.writer = writer = Writer(dram_range=self._dram_range)
        wiring.connect(m, packer.o_packed, writer.i_packed)

        m.submodules.reader = reader = Reader(dram_range=self._dram_range)

        m.submodules.arbiter = arbiter = Arbiter()
        wiring.connect(m, arbiter.dram, flipped(self.dram))
        wiring.connect(m, arbiter.writer, writer.dram)
        wiring.connect(m, arbiter.reader, reader.dram)

        # needs to know:
        #  - where to start reading from
        #  - how many samples are before trigger
        #  - how many samples total in buffer

        push_sample = Signal()
        pop_sample  = Signal()

        m.d.comb += [
            writer.i_packed.p.data.eq(packer.o_packed.p.data),
            writer.i_packed.valid.eq(packer.o_valid),
        ]
        with m.If(writer.i_packed.valid & writer.i_packed.ready):
            m.d.comb += push_sample.eq(1)

        # XXX
        with m.If(reader.o_octets.valid & reader.o_octets.ready):
            m.d.comb += pop_sample.eq(1)

        m.submodules.start_ptr = start_ptr = Pointer(self._dram_range, step=4)
        m.submodules.trig_ptr  = trig_ptr  = Pointer(self._dram_range, step=4)
        m.submodules.write_ptr = write_ptr = Pointer(self._dram_range, step=4)
        m.submodules.read_ptr  = read_ptr  = Pointer(self._dram_range, step=1)
        m.d.comb += trig_ptr.i_value.eq(write_ptr.o_value)
        m.d.comb += read_ptr.i_value.eq(start_ptr.o_value)

        triggered   = Signal()
        write_count = Signal(range(len(self._dram_range) + 1))
        with m.If(push_sample):
            m.d.comb += write_ptr.incr.eq(1)
            with m.If(triggered & (write_count + 4 == self.total_count)):
                pass # FIXME
            with m.Elif(~triggered & (write_count + 4 == self.precap_count)):
                m.d.comb += start_ptr.incr.eq(1)
            with m.Else():
                m.d.sync += write_count.eq(write_count + 4)

        with m.Elif(packer.o_packed.valid):
            pass # TODO: overflow

        # TODO: reader.o_octets


# class Pointer(wiring.Component):
#     load:    In(1)
#     incr:    In(1)
#     i_value: In(32)
#     o_value: Out(32)
#
#     def __init__(self, interval: range, *, step: int):
#         self._range = range(interval.start, interval.stop, step)
#
#         super().__init__()
#
#     def elaborate(self, platform):
#         m = Module()
#
#         value = Signal(self._range, self._range.start)
#         m.d.comb += self.o_value.eq(value)
#
#         with m.If(self.load):
#             m.d.sync += value.eq(self.i_value)
#         with m.Elif(self.next):
#             with m.If(value + self._range.step == self._range.stop):
#                 m.d.sync += value.eq(self._range.start)
#             with m.Else():
#                 m.d.sync += value.eq(value + self._range.step)
#
#         return m


class AnalyzerComponent(wiring.Component):
    i_stream: In(stream.Signature(8))
    o_stream: Out(stream.Signature(8))

    def __init__(self, ports):
        self._ports = ports

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.clk_buffer  = clk_buffer  = io.Buffer("o",  self._ports.clk)
        m.submodules.data_buffer = data_buffer = io.Buffer("io", self._ports.data)

        # ... FPGA-side implementation goes here, for example:

        with m.If(self.loopback_en):
            wiring.connect(m, flipped(self.i_stream), flipped(self.o_stream))

        return m


class AnalyzerInterface:
    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
                 pins: list[GlasgowPin]):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        ports = assembly.add_port_group(pins=pins)
        component = assembly.add_submodule(AnalyzerComponent(ports))
        self._pipe = assembly.add_inout_pipe(component.o_stream, component.i_stream)

    def _log(self, message: str, *args):
        self._logger.log(self._level, "analyzer: " + message, *args)


class AnalyzerApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "logic analyzer"
    preview = True
    description = """
    TODO
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)

        # TODO: improve this to parse eg `run analyzer clk=A0 data=A1`
        access.add_pins_argument(parser, "pins", width=range(1, 33), required=True)

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.boilerplate_iface = AnalyzerInterface(self.logger, self.assembly,
                pins=args.pins)

    @classmethod
    def add_setup_arguments(cls, parser):
        pass

    async def setup(self, args):
        await self.boilerplate_iface.enable_loopback()

    @classmethod
    def add_run_arguments(cls, parser):
        pass

    async def run(self, args):
        result = await self.boilerplate_iface.do_something()
        print(f"did something: {result.hex()}")

    @classmethod
    def tests(cls):
        from . import test
        return test.AnalyzerAppletTestCase
