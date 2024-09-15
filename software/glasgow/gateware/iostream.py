from amaranth import *
from amaranth.lib import enum, data, wiring, stream, io
from amaranth.lib.wiring import In, Out

from glasgow.gateware.ports import PortGroup


__all__ = ["IOStreamerTop"]


def _filter_ioshape(direction, ioshape):
    direction = io.Direction(direction)
    if direction is io.Direction.Bidir:
        return True
    return io.Direction(ioshape[0]) in (direction, io.Direction.Bidir)


def _iter_ioshape(direction, ioshape, *args): # actually filter+iter
    for name, item in ioshape.items():
        if _filter_ioshape(direction, ioshape[name]):
            yield (name, *(arg[name] for arg in args))


def _map_ioshape(direction, ioshape, fn): # actually filter+map
    return data.StructLayout({
        name: fn(item[1]) for name, item in ioshape.items() if _filter_ioshape(direction, item)
    })


class SimulatableDDRBuffer(io.DDRBuffer):
    def elaborate(self, platform):
        if not isinstance(self._port, io.SimulationPort):
            return super().elaborate(platform)

        # At the time of writing Amaranth DDRBuffer doesn't allow for simulation, this implements
        # ICE40 semantics for simulation.
        m = Module()

        m.submodules.io_buffer = io_buffer = io.Buffer(self.direction, self.port)

        if self.direction is not io.Direction.Output:
            m.domains.i_domain_negedge = ClockDomain("i_domain_negedge", local=True)
            m.d.comb += ClockSignal("i_domain_negedge").eq(~ClockSignal(self.i_domain))
            i_ff = Signal(len(self.port), reset_less=True)
            i_negedge_ff = Signal(len(self.port), reset_less=True)
            i_final_ff = Signal(data.ArrayLayout(len(self.port), 2), reset_less=True)
            m.d[self.i_domain] += i_ff.eq(io_buffer.i)
            m.d["i_domain_negedge"] += i_negedge_ff.eq(io_buffer.i)
            m.d[self.i_domain] += i_final_ff.eq(Cat(i_ff, i_negedge_ff))
            m.d.comb += self.i.eq(i_final_ff)

        if self.direction is not io.Direction.Input:
            m.domains.o_domain_negedge = ClockDomain("o_domain_negedge", local=True)
            m.d.comb += ClockSignal("o_domain_negedge").eq(~ClockSignal(self.o_domain))
            o_ff = Signal(len(self.port), reset_less=True)
            o_negedge_ff = Signal(len(self.port), reset_less=True)
            oe_ff = Signal(reset_less=True)
            m.d[self.o_domain] += o_ff.eq(self.o[0] ^ o_negedge_ff)
            o1_ff = Signal(len(self.port), reset_less=True)
            m.d[self.o_domain] += o1_ff.eq(self.o[1])
            m.d["o_domain_negedge"] += o_negedge_ff.eq(o1_ff ^ o_ff)
            m.d[self.o_domain] += oe_ff.eq(self.oe)
            m.d.comb += io_buffer.o.eq(o_ff ^ o_negedge_ff)
            m.d.comb += io_buffer.oe.eq(oe_ff)

        return m

def LaneLayout(actual_layout, /, *, meta_layout=0):
    return data.StructLayout({
        "actual": actual_layout,
        "meta": meta_layout,
    })

def MetaLayoutWithTag(*, tag_layout, meta_layout=0):
    return data.StructLayout({
        "inner_meta": meta_layout,
        "tag": tag_layout,
        "last": 1,
    })

def IOOutputActualLayout(ioshape):
    return data.StructLayout({
        "port": _map_ioshape("o", ioshape, lambda width: data.StructLayout({
            "o":  width,
            "oe": 1,
        })),
        "i_en": 1,
    })

def IOOutputStreamSignature(ioshape, /, lane_count=2, *, meta_layout=0):
    actual_layout = IOOutputActualLayout(ioshape)
    return stream.Signature(
        data.ArrayLayout(
            LaneLayout(actual_layout, meta_layout=meta_layout),
            lane_count
        )
    )

def IOInputActualLayout(ioshape):
    return data.StructLayout({
        "port": _map_ioshape("i", ioshape, lambda width: data.StructLayout({
            "i":  width,
        })),
        "i_valid": 1,
    })

def IOInputStreamSignature(ioshape, /, lane_count=2, *, meta_layout=0):
    actual_layout = IOInputActualLayout(ioshape)
    return stream.Signature(
        data.ArrayLayout(
            LaneLayout(actual_layout, meta_layout=meta_layout),
            lane_count
        )
    )

class IOStreamer(wiring.Component):
    def __init__(self, ioshape, ports, /, *, ratio=1, meta_layout=0):
        assert isinstance(ioshape, (int, dict))
        assert ratio in (1, 2)

        self._ioshape = ioshape
        self._ratio   = ratio
        self._ports   = ports

        super().__init__({
            "o_stream":  In(IOOutputStreamSignature(ioshape, lane_count=ratio, meta_layout=meta_layout)),
            "i_stream": Out(IOInputStreamSignature(ioshape, lane_count=ratio, meta_layout=meta_layout)),
        })

        self.o_stream.valid = Const(1)
        self.o_stream.ready = Const(1)
        for lane_index in range(ratio):
            self.o_stream.p[lane_index].actual.i_en = Const(1) # Must always sample!
        # self.i_stream.valid = Const(1) # i_stream is not really valid for the first `latency` cycles after reset
        self.i_stream.ready = Const(1)

    def get_latency(self, platform):
        # May be platform-dependent in the future
        if self._ratio == 1:
            return 1
        if self._ratio == 2:
            return 2

    def elaborate(self, platform):
        m = Module()

        if self._ratio == 1:
            buffer_cls = io.FFBuffer
        if self._ratio == 2:
            buffer_cls = SimulatableDDRBuffer

        latency = self.get_latency(platform)

        if isinstance(self._ports, io.PortLike):
            m.submodules.buffer = buffer = buffer_cls("io", self._ports)
        if isinstance(self._ports, PortGroup):
            buffer = {}
            for name, sub_port in self._ports.__dict__.items():
                direction, _width = self._ioshape[name]
                m.submodules[f"buffer_{name}"] = buffer[name] = buffer_cls(direction, sub_port)

        for lane_index in range(self._ratio):
            for _, buffer_parts, stream_parts in _iter_ioshape("o", self._ioshape,
                    buffer, self.o_stream.p[lane_index].actual.port):
                m.d.comb += buffer_parts.o[lane_index].eq(stream_parts.o)

        for name, buffer_parts in _iter_ioshape("o", self._ioshape,
                    buffer):
            oe_any = self.o_stream.p[0].actual.port[name].oe
            for lane_index in range(1, self._ratio):
                oe_any |= self.o_stream.p[1].actual.port[name].oe
            m.d.comb += buffer_parts.oe.eq(oe_any)

        def delay(value, name):
            delayed_values = []
            for stage in range(latency):
                next_value = Signal.like(value, name=f"{name}_{stage}")
                m.d.sync += next_value.eq(value)
                value = next_value
                delayed_values.append(next_value)
            return delayed_values

        i_en = delay(Const(1), name="i_en")[-1] # We always output samples, except for `latency` cycles after reset
        for lane_index in range(self._ratio):
            for name, i_payload_parts, buffer_parts in _iter_ioshape("i", self._ioshape, self.i_stream.p[lane_index].actual.port, buffer):
                if self._ratio > 1:
                    m.d.comb += i_payload_parts.i.eq(buffer_parts.i[lane_index])
                else:
                    m.d.comb += i_payload_parts.i.eq(buffer_parts.i)
            m.d.comb += self.i_stream.p[lane_index].actual.i_valid.eq(1)
        m.d.comb += self.i_stream.valid.eq(i_en)

        return m


class StreamStretcher(wiring.Component):
    """
    This component makes sure that any stream is not allowed to transfer more often
    than every `divisor` cycles. If `divisor` is 0 or 1, then the StreamStretcher has
    no effect.
    """
    def __init__(self, stream_signature, *, divisor_width=16):
        super().__init__({
            "i_stream":  In(stream_signature),
            "o_stream": Out(stream_signature),
            "divisor": In(divisor_width),
        })

    def elaborate(self, platform):
        m = Module()
        timer = Signal.like(self.divisor)
        timer_done = Signal()
        m.d.comb += timer_done.eq((timer == 0) | (timer == 1))

        m.d.comb += self.o_stream.p.eq(self.i_stream.p)
        m.d.comb += self.o_stream.valid.eq(self.i_stream.valid & timer_done)
        m.d.comb += self.i_stream.ready.eq(self.o_stream.ready & timer_done)

        with m.If(timer_done):
            with m.If(self.o_stream.ready & self.o_stream.valid):
                m.d.sync += timer.eq(self.divisor)
        with m.Else():
            m.d.sync += timer.eq(timer - 1)

        return m


class IOLatcher(wiring.Component):
    """
    This component has an always valid, always ready output stream,
    which passes through the "o" and "oe" fields when a transaction
    is presented at the input stream, otherwise it keeps repeating the
    last transaction, which it memorises.
    Other fields such as i_en, and meta are dropped.
    """
    def __init__(self, ioshape, /, *, ratio=1, init=None, meta_layout=0):
        assert isinstance(ioshape, (int, dict))
        assert ratio in (1, 2)

        self._ioshape = ioshape
        self._ratio   = ratio
        self._init    = init

        super().__init__({
            "i_stream":  In(IOOutputStreamSignature(ioshape, lane_count=ratio, meta_layout=meta_layout)),
            "o_stream": Out(IOOutputStreamSignature(ioshape, lane_count=ratio, meta_layout=meta_layout)),
        })

        self.o_stream.valid = Const(1)
        self.o_stream.ready = Const(1)
        self.i_stream.ready = Const(1)

    def elaborate(self, platform):
        m = Module()

        o_latch = Signal(_map_ioshape("o", self._ioshape, lambda width: data.StructLayout({
            "o":  width,
            "oe": 1,
        })), init=self._init)
        with m.If(self.i_stream.valid & self.i_stream.ready):
            for lane_index in range(self._ratio):
                m.d.comb += self.o_stream.p[lane_index].actual.port.eq(self.i_stream.p[lane_index].actual.port)

            for _, latch_parts, stream_parts in _iter_ioshape("o", self._ioshape,
                    o_latch, self.i_stream.p[-1].actual.port):
                m.d.sync += latch_parts.eq(stream_parts)

        with m.Else():
            for lane_index in range(self._ratio):
                for _, simple_stream_parts, latch_parts in _iter_ioshape("o", self._ioshape,
                        self.o_stream.p[lane_index].actual.port, o_latch):
                    m.d.comb += simple_stream_parts.eq(latch_parts)

        return m

class SkidBuffer(wiring.Component):
    """
    This component is a generic skid buffer.
    It is essentially a `depth` deep FIFO with a stream interface.
    """
    def __init__(self, depth, stream_signature):
        self._depth = depth
        super().__init__({
            "i_stream":  In(stream_signature),
            "o_stream": Out(stream_signature),
        })

    def elaborate(self, platform):
        m = Module()

        # This skid buffer is organized as a shift register to avoid any uncertainties associated
        # with the use of an async read memory. On platforms that have LUTRAM, this implementation
        # may be slightly worse than using LUTRAM, and may have to be revisited in the future.
        skid = Array(Signal(self.i_stream.p.shape(), name=f"skid_{stage}")
                     for stage in range(1 + self._depth))

        skid_at = Signal(range(1 + self._depth))

        m.d.comb += skid[0].eq(self.i_stream.p)

        with m.If(self.i_stream.valid):
            for n_shift in range(self._depth):
                m.d.sync += skid[n_shift + 1].eq(skid[n_shift])

        not_full = Signal()
        m.d.comb += not_full.eq(skid_at != self._depth)

        m.d.comb += self.o_stream.p.eq(skid[skid_at])
        m.d.comb += self.o_stream.valid.eq(self.i_stream.valid | (skid_at != 0))
        m.d.comb += self.i_stream.ready.eq(self.o_stream.ready | not_full)

        with m.If(self.i_stream.valid & self.i_stream.ready & ~self.o_stream.ready):
            m.d.sync += skid_at.eq(skid_at + 1)
        with m.Elif(~self.i_stream.valid & self.o_stream.valid & self.o_stream.ready):
            m.d.sync += skid_at.eq(skid_at - 1)

        return m

class SampleRequestDelayer(wiring.Component):
    def __init__(self, /, *, ratio, meta_layout, min_latency, max_sample_delay_half_clocks, min_divisor):
        self._ratio = ratio
        self._min_latency = min_latency
        self._max_sample_delay_half_clocks = max_sample_delay_half_clocks
        self._min_divisor = min_divisor
        self._max_latency_except_hcyc = min_latency + self._max_sample_delay_half_clocks // 2

        super().__init__({
            "i_en": In(data.ArrayLayout(1, ratio)),
            "meta": In(data.ArrayLayout(meta_layout, ratio)),
            "sample_delay_half_clocks": In(range(max_sample_delay_half_clocks + 1)),
            "i_en_delayed": Out(data.ArrayLayout(1, ratio)),
            "meta_delayed": Out(data.ArrayLayout(meta_layout, ratio)),
            "reads_in_flight": Out(1),
        })

    def elaborate(self, platform):
        m = Module()

        def delay(value, name, cycles):
            delayed_values = Array(Signal(value.shape(), name=f"delayed_{name}_{stage}")
                     for stage in range(cycles))
            m.d.sync += delayed_values[0].eq(value)
            for stage in range(1, cycles):
                m.d.sync += delayed_values[stage].eq(delayed_values[stage-1])
            return delayed_values

        i_en_delayed_except_half_cyc = Signal.like(self.i_en_delayed)
        meta_delayed_except_half_cyc = Signal.like(self.meta_delayed)
        reads_in_flight_except_half_cyc = Signal.like(self.reads_in_flight)

        # Following are two implementations: the second one is really simple, using only shift registers,
        # while the first one relies on a `min_divisor` setting to use a counter for the first part of the
        # delay mechanism.

        # Some statistics using the memory-25x applet:
        # divisor=24  sample_delay=0   => simple:  810 ICESTORM_LCs, optimized: 811 ICESTORM_LCs
        # divisor=24  sample_delay=1   => simple:  830 ICESTORM_LCs, optimized: 832 ICESTORM_LCs
        # divisor=24  sample_delay=2   => simple:  823 ICESTORM_LCs, optimized: 825 ICESTORM_LCs
        # divisor=24  sample_delay=3   => simple:  832 ICESTORM_LCs, optimized: 824 ICESTORM_LCs
        # divisor=24  sample_delay=6   => simple:  836 ICESTORM_LCs, optimized: 823 ICESTORM_LCs
        # divisor=24  sample_delay=12  => simple:  849 ICESTORM_LCs, optimized: 825 ICESTORM_LCs
        # divisor=24  sample_delay=24  => simple:  888 ICESTORM_LCs, optimized: 830 ICESTORM_LCs
        # divisor=24  sample_delay=36  => simple:  928 ICESTORM_LCs, optimized: 833 ICESTORM_LCs
        # divisor=24  sample_delay=47  => simple: 1001 ICESTORM_LCs, optimized: 877 ICESTORM_LCs
        # divisor=3   sample_delay=0   => simple:  813 ICESTORM_LCs, optimized: 820 ICESTORM_LCs
        # divisor=3   sample_delay=3   => simple:  859 ICESTORM_LCs, optimized: 860 ICESTORM_LCs
        # divisor=3   sample_delay=6   => simple:  872 ICESTORM_LCs, optimized: 858 ICESTORM_LCs
        # divisor=3   sample_delay=12  => simple:  894 ICESTORM_LCs, optimized: 901 ICESTORM_LCs
        # divisor=3   sample_delay=24  => simple:  980 ICESTORM_LCs, optimized: 970 ICESTORM_LCs
        # divisor=4   sample_delay=8   => simple:  874 ICESTORM_LCs, optimized: 866 ICESTORM_LCs
        # divisor=4   sample_delay=16  => simple:  903 ICESTORM_LCs, optimized: 893 ICESTORM_LCs
        # divisor=4   sample_delay=32  => simple:  999 ICESTORM_LCs, optimized: 988 ICESTORM_LCs
        # divisor=5   sample_delay=10  => simple:  868 ICESTORM_LCs, optimized: 858 ICESTORM_LCs
        # divisor=8   sample_delay=6   => simple:  836 ICESTORM_LCs, optimized: 830 ICESTORM_LCs
        # divisor=8   sample_delay=16  => simple:  886 ICESTORM_LCs, optimized: 866 ICESTORM_LCs
        # divisor=240 sample_delay=100 => simple: 1114 ICESTORM_LCs, optimized: 826 ICESTORM_LCs
        # divisor=240 sample_delay=238 => simple: 1528 ICESTORM_LCs, optimized: 830 ICESTORM_LCs

        #if self._min_divisor >= 1: # The optimized implementation works correctly as long as _min_divisor >= 1
        if self._min_divisor >= 4:  # however it may not make sense to use it when min_divisor is a low number
            # Optimized implementaiton using a counter as a first-stage delay mechanism
            assert self._min_divisor >= 1, "with a divisor of less than 1, the counter logic wouldn't work"
            assert self._min_latency >= 1, "with a min latency less then 1, and sample delay of zero, the counter logic wouldn't work"
            counting = Signal()
            counter = Signal(range(min(self._min_divisor, self._max_latency_except_hcyc)))
            i_en_cached = Signal.like(self.i_en)
            meta_cached = Signal.like(self.meta)
            i_en_delay_chain_input = Signal.like(self.i_en)

            latency_minus_1 = self._min_latency - 1 + self.sample_delay_half_clocks // 2

            with m.If(counting):
                with m.If((counter == self._min_divisor - 1) | 
                          (counter == latency_minus_1)):
                    m.d.sync += counting.eq(0)
                    m.d.comb += i_en_delay_chain_input.eq(i_en_cached)
                with m.Else():
                    m.d.sync += counter.eq(counter + 1)

            with m.If(Signal.cast(self.i_en).any()):
                m.d.sync += (
                    counting.eq(1),
                    i_en_cached.eq(self.i_en),
                    meta_cached.eq(self.meta),
                    counter.eq(0),
                )

            m.d.comb += (
                i_en_delayed_except_half_cyc.eq(i_en_delay_chain_input),
                meta_delayed_except_half_cyc.eq(meta_cached),
                reads_in_flight_except_half_cyc.eq(counting),
            )

            if self._max_latency_except_hcyc > self._min_divisor:
                delay_chain_cycles = self._max_latency_except_hcyc - self._min_divisor
                i_en_delays = delay(i_en_delay_chain_input, name=f"i_en", cycles=delay_chain_cycles)
                meta_delays = delay(meta_cached, name=f"meta", cycles=delay_chain_cycles)

                delay_selector = latency_minus_1 - self._min_divisor

                i_en_in_flight_up_to = Array(Signal(1, name=f"i_en_in_flight_{stage}") for stage in range(delay_chain_cycles))
                m.d.comb += i_en_in_flight_up_to[0].eq(Signal.cast(i_en_delays[0]).any())
                for stage in range(1, delay_chain_cycles):
                    value = Signal.cast(i_en_delays[stage]).any() | i_en_in_flight_up_to[stage - 1]
                    m.d.comb += i_en_in_flight_up_to[stage].eq(value)

                with m.If(latency_minus_1 >= self._min_divisor):
                    m.d.comb += i_en_delayed_except_half_cyc.eq(i_en_delays[delay_selector])
                    m.d.comb += meta_delayed_except_half_cyc.eq(meta_delays[delay_selector])
                    m.d.comb += reads_in_flight_except_half_cyc.eq(counting | i_en_in_flight_up_to[delay_selector])

        else: # Simple shift-register-only based implementation
            meta, i_en_delays, i_en  = [], [], []
            delay_selector = self._min_latency - 1 + self.sample_delay_half_clocks // 2

            i_en_delays = delay(self.i_en, name=f"i_en", cycles=self._max_latency_except_hcyc)
            meta_delays = delay(self.meta, name=f"meta", cycles=self._max_latency_except_hcyc)

            m.d.comb += i_en_delayed_except_half_cyc.eq(i_en_delays[delay_selector])
            m.d.comb += meta_delayed_except_half_cyc.eq(meta_delays[delay_selector])

            i_en_in_flight_up_to = Array(Signal(1, name=f"i_en_in_flight_{stage}") for stage in range(self._max_latency_except_hcyc))
            m.d.comb += i_en_in_flight_up_to[0].eq(Signal.cast(i_en_delays[0]).any())
            for stage in range(1, self._max_latency_except_hcyc):
                value = Signal.cast(i_en_delays[stage]).any() | i_en_in_flight_up_to[stage - 1]
                m.d.comb += i_en_in_flight_up_to[stage].eq(value)

            m.d.comb += reads_in_flight_except_half_cyc.eq(i_en_in_flight_up_to[delay_selector])

        # Here follows code common to both implementations, that handles half a cycle delays.
        # Half-cycle delays are handled as an additional delay step. (The sample payload will
        # be combined from two different clock cycles.) We're using an additional shift
        # register stage to avoid having to calculate a dynamic delay of
        # (sample_delay // 2 + sample_delay % 2)
        m.d.comb += self.i_en_delayed.eq(i_en_delayed_except_half_cyc)
        m.d.comb += self.meta_delayed.eq(meta_delayed_except_half_cyc)
        m.d.comb += self.reads_in_flight.eq(reads_in_flight_except_half_cyc)

        if self._ratio == 2:
            i_en_hcyc = delay(i_en_delayed_except_half_cyc, name=f"i_en_hcyc", cycles=1)[0]
            meta_hcyc = delay(meta_delayed_except_half_cyc, name=f"meta_hcyc", cycles=1)[0]
            with m.If(self.sample_delay_half_clocks % 2):
                m.d.comb += self.i_en_delayed.eq(i_en_hcyc)
                m.d.comb += self.meta_delayed.eq(meta_hcyc)
                m.d.comb += self.reads_in_flight.eq(reads_in_flight_except_half_cyc | Signal.cast(i_en_hcyc).any())

        return m

class IOStreamerTop(wiring.Component):
    """I/O buffer to stream adapter.

    This adapter instantiates I/O buffers for a port (FF or DDR) and connects them to a pair of
    streams, one for the outputs of the buffers and one for the inputs. Whenever an `o_stream`
    transfer occurs, the state of the output is updated _t1_ cycles later; if `o_stream.p.i_en`
    is set, then _t2_ cycles later, a payload with the data captured at the same time as
    the outputs were updated appears on `i_stream.p.i`.

    Arbitrary ancillary data may be provided with `o_stream` transfers via `o_stream.p.meta`,
    and this data will be relayed back as `i_stream.p.meta` with the output-to-input latency
    of the buffer. Higher-level protocol engines can use this data to indicate how the inputs
    must be processed without needing counters or state machines on a higher level to match
    the latency (and, usually, without needing any knowledge of the latency at all).

    On reset, output ports have their drivers enabled, and bidirectional ports have them disabled.
    All of the signals are deasserted, which could be a low or a high level depending on the port
    polarity.
    """

    def __init__(self, ioshape, ports, /, *, ratio=1, init=None, meta_layout=0, divisor_width=16, max_sample_delay_half_clocks=0, min_divisor=0):
        assert isinstance(ioshape, (int, dict))
        assert ratio in (1, 2)

        self._ioshape = ioshape
        self._ports   = ports
        self._ratio   = ratio
        self._init    = init
        self._divisor_width = divisor_width
        self._max_sample_delay_half_clocks = max_sample_delay_half_clocks
        self._meta_layout = meta_layout
        self._min_divisor = min_divisor

        super().__init__({
            "o_stream":  In(IOOutputStreamSignature(ioshape, lane_count=ratio, meta_layout=meta_layout)),
            "i_stream": Out(IOInputStreamSignature(ioshape, lane_count=ratio, meta_layout=meta_layout)),
            "divisor": In(divisor_width),
            "sample_delay_half_clocks": In(range(max_sample_delay_half_clocks + 1)),
        })

    def elaborate(self, platform):
        m = Module()

        #if self._min_divisor:
        #    m.d.sync += Assert(self.divisor >= self._min_divisor)

        #if self._ratio == 1:
        #    m.d.sync += Assert(self.sample_delay_half_clocks % 2 == 0)

        m.submodules.stream_stretcher = stream_stretcher = StreamStretcher(
            IOOutputStreamSignature(self._ioshape, lane_count=self._ratio, meta_layout=self._meta_layout),
            divisor_width = self._divisor_width)
        m.d.comb += stream_stretcher.divisor.eq(self.divisor)
        wiring.connect(m, io_streamer=wiring.flipped(self.o_stream), stream_strecher=stream_stretcher.i_stream)

        m.submodules.io_streamer = io_streamer = IOStreamer(self._ioshape, self._ports, ratio=self._ratio, meta_layout=0)
        m.submodules.io_latcher = io_latcher = IOLatcher(self._ioshape, ratio=self._ratio, init=self._init, meta_layout=0)
        wiring.connect(m, io_latcher=io_latcher.o_stream, io_streamer=io_streamer.o_stream)
        for lane_index in range(self._ratio):
            m.d.comb += io_latcher.i_stream.p[lane_index].actual.port.eq(stream_stretcher.o_stream.p[lane_index].actual.port)
        m.d.comb += io_latcher.i_stream.valid.eq(stream_stretcher.o_stream.valid & stream_stretcher.o_stream.ready)
        #  ^ note: the above makes sure IOLatcher doesn't take a new transaction if we're blocking the input

        min_latency = io_streamer.get_latency(platform)
        max_latency = min_latency + self._max_sample_delay_half_clocks // 2 + self._max_sample_delay_half_clocks % 2

        m.submodules.sample_request_delayer = sample_request_delayer = SampleRequestDelayer(ratio=self._ratio,
                                                                                            meta_layout=self._meta_layout,
                                                                                            min_latency=min_latency,
                                                                                            max_sample_delay_half_clocks=self._max_sample_delay_half_clocks,
                                                                                            min_divisor=self._min_divisor)
        m.d.comb += sample_request_delayer.sample_delay_half_clocks.eq(self.sample_delay_half_clocks)
        for lane_index in range(self._ratio):
            m.d.comb += sample_request_delayer.i_en[lane_index].eq(stream_stretcher.o_stream.valid &
                                                                   stream_stretcher.o_stream.ready &
                                                                   stream_stretcher.o_stream.p[lane_index].actual.i_en)
            m.d.comb += sample_request_delayer.meta[lane_index].eq(stream_stretcher.o_stream.p[lane_index].meta)

        skid_buffer_depth = max_latency
        if self._min_divisor > 1:
            # This is an optimisation we can apply if we know at elaboration time that divisor can never be larger than min_divisor
            skid_buffer_depth = (max_latency + self._min_divisor - 1) // self._min_divisor

        m.submodules.skid_buffer = skid_buffer = SkidBuffer(
            skid_buffer_depth,
            IOInputStreamSignature(self._ioshape, lane_count=self._ratio, meta_layout=self._meta_layout),
        )
        m.d.comb += skid_buffer.i_stream.valid.eq(Signal.cast(sample_request_delayer.i_en_delayed).any())
        #with m.If(skid_buffer.i_stream.valid):
        #    m.d.sync += Assert(skid_buffer.i_stream.ready)

        for lane_index in range(self._ratio):
            m.d.comb += skid_buffer.i_stream.p[lane_index].actual.port.eq(io_streamer.i_stream.p[lane_index].actual.port)

        if self._ratio == 2:
            with m.If(self.sample_delay_half_clocks % 2):
                m.d.comb += skid_buffer.i_stream.p[1].actual.port.eq(io_streamer.i_stream.p[0].actual.port)
                i1_delayed = Signal.like(io_streamer.i_stream.p[1].actual.port, name=f"i1_delayed")
                m.d.sync += i1_delayed.eq(io_streamer.i_stream.p[1].actual.port)
                m.d.comb += skid_buffer.i_stream.p[0].actual.port.eq(i1_delayed)

        for lane_index in range(self._ratio):
            m.d.comb += skid_buffer.i_stream.p[lane_index].meta.eq(sample_request_delayer.meta_delayed[lane_index])
            m.d.comb += skid_buffer.i_stream.p[lane_index].actual.i_valid.eq(sample_request_delayer.i_en_delayed[lane_index])

        wiring.connect(m, skid_buffer=skid_buffer.o_stream, io_streamer_top=wiring.flipped(self.i_stream))

        m.d.comb += stream_stretcher.o_stream.ready.eq(self.i_stream.ready | (~skid_buffer.o_stream.valid & ~sample_request_delayer.reads_in_flight))

        return m


class IO2LaneTo1Lane(wiring.Component):
    """
    This component down-converts a 2-lane stream to a 1-lane stream, while adding
    information to the metadata, which includes:
        tag: the index of the lane the original data belonged to
        last: a flag signifying if a second beat is expected in the case of later up-conversion
    The last fields is optionally determined using the supplied is_beat_0_last argument
    to the constructor, which must be a function that returns an amaranth expression
    """
    @staticmethod
    def i_stream_signature(actual_layout, /, *, meta_layout=0):
        return stream.Signature(
            data.ArrayLayout(
                LaneLayout(actual_layout, meta_layout=meta_layout),
                2
            )
        )

    @staticmethod
    def o_stream_signature(actual_layout, /, *, meta_layout=0):
        return stream.Signature(
            data.ArrayLayout(
                LaneLayout(actual_layout, meta_layout=MetaLayoutWithTag(tag_layout=range(2), meta_layout=meta_layout)),
                1
            )
        )

    def __init__(self, actual_layout, *, meta_layout=0, is_beat_0_last=lambda payload: 0):
        self._is_beat_0_last = is_beat_0_last
        super().__init__({
            "i_stream":  In(self.i_stream_signature(actual_layout, meta_layout=meta_layout)),
            "o_stream": Out(self.o_stream_signature(actual_layout, meta_layout=meta_layout)),
        })

    def elaborate(self, platform):
        m = Module()

        phase = Signal()
        m.d.comb += self.o_stream.p[0].actual.eq(self.i_stream.p[phase].actual)
        m.d.comb += self.o_stream.p[0].meta.inner_meta.eq(self.i_stream.p[phase].meta)
        m.d.comb += self.o_stream.p[0].meta.tag.eq(phase)
        m.d.comb += self.o_stream.p[0].meta.last.eq(1)
        with m.If((phase == 0) & ~self._is_beat_0_last(self.i_stream.p)):
            m.d.comb += self.o_stream.p[0].meta.last.eq(0)

        m.d.comb += self.o_stream.valid.eq(self.i_stream.valid)
        with m.If(self.o_stream.ready):
            with m.If(phase == 0):
                with m.If(self.i_stream.valid):
                    m.d.sync += phase.eq(1)

            with m.Else(): # phase == 1
                m.d.comb += self.i_stream.ready.eq(1)
                m.d.sync += phase.eq(0)

        return m


class IOClocker(wiring.Component):
    """
    In case of ratio=1:
        This component down-converts (serializes) 2 lanes to 1 lane, while adding metadata to identify which lane each beat belonged to.
    In case of ratio=2, divisor=0:
        This component adds useless metadata, but is otherwise a pass-through. Adding the metadata is necessary, because divisor is not a compile-time parameter
    In case of ratio=2, divisor!=0:
        This component down-converts (serializes) 2 lanes to 1 lane, just like in the ratio=1 case above, except, it duplicates the resulting lane, while also making
        sure to force `i_en` of the second resulting lane to 0. This means that one `i_en` bit high doesn't result in two samples.
        ratio=2, divisor!=0 is designed to behave exactly like ratio=1, divisor!=0, so the read samples associated with output lane 0 are the only ones we care about.
    """
    @staticmethod
    def i_stream_signature(ioshape, /, *, _ratio=2, meta_layout=0):
        # Currently the only supported ratio is 2
        return IOOutputStreamSignature(ioshape, lane_count=_ratio, meta_layout=meta_layout)

    @staticmethod
    def o_stream_signature(ioshape, /, *, ratio=1, meta_layout=0):
        return IOOutputStreamSignature(ioshape, lane_count=ratio, meta_layout=MetaLayoutWithTag(tag_layout=range(2), meta_layout=meta_layout))

    def __init__(self, ioshape, *, o_ratio=1, meta_layout=0, divisor_width=16):
        assert isinstance(ioshape, dict)
        assert o_ratio in (1, 2)

        self._ioshape = ioshape
        self._o_ratio = o_ratio
        self._meta_layout = meta_layout

        super().__init__({
            "i_stream":  In(self.i_stream_signature(ioshape,
                meta_layout=meta_layout)),
            "o_stream": Out(self.o_stream_signature(ioshape,
                ratio=o_ratio, meta_layout=meta_layout)),
            "divisor": In(divisor_width),
        })

    def elaborate(self, platform):
        m = Module()

        m.submodules.io_2to1_lane = io_2to1_lane = IO2LaneTo1Lane(IOOutputActualLayout(self._ioshape), meta_layout=self._meta_layout,
                is_beat_0_last = lambda payload: payload[1].actual.i_en==0)

        phase = Signal()
        if self._o_ratio == 1:
            wiring.connect(m, ioclocker=wiring.flipped(self.i_stream), io_2to1_lane=io_2to1_lane.i_stream)
            wiring.connect(m, ioclocker=wiring.flipped(self.o_stream), io_2to1_lane=io_2to1_lane.o_stream)
        if self._o_ratio == 2:
            with m.If(self.divisor == 0):
                # Just pass-through, we're doing nothing, but adding currently-useless tag metadata
                for lane_index in range(self._o_ratio):
                    m.d.comb += self.o_stream.p[lane_index].actual.eq(self.i_stream.p[lane_index].actual)
                    m.d.comb += self.o_stream.p[lane_index].meta.inner_meta.eq(self.i_stream.p[lane_index].meta)
                    m.d.comb += self.o_stream.p[lane_index].meta.tag.eq(lane_index)
                    m.d.comb += self.o_stream.p[lane_index].meta.last.eq(~self.i_stream.p[1].actual.i_en)
                m.d.comb += self.o_stream.valid.eq(self.i_stream.valid)
                m.d.comb += self.i_stream.ready.eq(self.o_stream.ready)
            with m.Else():
                wiring.connect(m, ioclocker=wiring.flipped(self.i_stream), io_2to1_lane=io_2to1_lane.i_stream)
                for olane_index in range(2):
                    m.d.comb += self.o_stream.p[olane_index].eq(io_2to1_lane.o_stream.p[0])
                m.d.comb += self.o_stream.p[1].actual.i_en.eq(0) # Override i_en, to only sample once
                m.d.comb += self.o_stream.valid.eq(io_2to1_lane.o_stream.valid)
                m.d.comb += io_2to1_lane.o_stream.ready.eq(self.o_stream.ready)

        return m


class IO1LaneTo2Lane(wiring.Component):
    """
    This component up-converts a 1-lane stream to a 2-lane stream, using
    information from the metadata, to determine which lane to put each beat in:
        tag: the index of the lane the data should be put on
        last: a flag signifying if a second beat is expected
    An output stream transaction occurs only when the last bit is high for an
    input-stream transaction.
    """
    @staticmethod
    def o_stream_signature(actual_layout, /, *, meta_layout=0):
        return stream.Signature(
            data.ArrayLayout(
                LaneLayout(actual_layout, meta_layout=meta_layout),
                2
            )
        )

    @staticmethod
    def i_stream_signature(actual_layout, /, *, meta_layout=0):
        return stream.Signature(
            data.ArrayLayout(
                LaneLayout(actual_layout, meta_layout=MetaLayoutWithTag(tag_layout=range(2), meta_layout=meta_layout)),
                1
            )
        )

    def __init__(self, actual_layout, *, meta_layout=0):
        super().__init__({
            "i_stream":  In(self.i_stream_signature(actual_layout, meta_layout=meta_layout)),
            "o_stream": Out(self.o_stream_signature(actual_layout, meta_layout=meta_layout)),
        })

    def elaborate(self, platform):
        m = Module()

        untagged_istream_lane = Signal.like(self.o_stream.p[0])
        m.d.comb += untagged_istream_lane.actual.eq(self.i_stream.p[0].actual)
        m.d.comb += untagged_istream_lane.meta.eq(self.i_stream.p[0].meta.inner_meta)

        phase_0_stored = Signal.like(untagged_istream_lane)

        m.d.comb += self.i_stream.ready.eq(self.o_stream.ready)
        with m.If(self.i_stream.valid):
            with m.If(self.i_stream.p[0].meta.last):
                m.d.comb += self.o_stream.p[self.i_stream.p[0].meta.tag].eq(untagged_istream_lane)
                with m.If(self.i_stream.p[0].meta.tag != 0):
                    m.d.comb += self.o_stream.p[0].eq(phase_0_stored)
                m.d.comb += self.o_stream.valid.eq(1)
                with m.If(self.i_stream.ready):
                    m.d.sync += phase_0_stored.eq(0)
            with m.Else():
                with m.If(self.i_stream.ready):
                    m.d.sync += phase_0_stored.eq(untagged_istream_lane)

        return m


class IOClockerDeframer(wiring.Component):
    """
    In case of ratio=1:
        This component up-converts (deserializes) 1-lane samples to 2-lane.
    In case of ratio=2, divisor=0:
        This component is a simple pass-through, doing nothing
    In case of ratio=2, divisor!=0:
        This component throws away lane[1] of the input, and up-converts (deserializes) lane[0] to 2 lanes
    See IO1LaneTo2Lane subcomponent for more details
    """
    @staticmethod
    def o_stream_signature(ioshape, /, *, _ratio=1, meta_layout=0):
        # Currently the only supported ratio is 1, but this will change in the future for
        # interfaces like HyperBus.
        return IOInputStreamSignature(ioshape, lane_count=2, meta_layout=meta_layout)

    @staticmethod
    def i_stream_signature(ioshape, /, *, ratio=1, meta_layout=0):
        return IOInputStreamSignature(ioshape, lane_count=ratio, meta_layout=MetaLayoutWithTag(tag_layout=range(2), meta_layout=meta_layout))

    def __init__(self, ioshape, *, i_ratio=1, meta_layout=0, divisor_width=16):
        assert isinstance(ioshape, dict)
        assert i_ratio in (1, 2)

        self._ioshape = ioshape
        self._i_ratio = i_ratio
        self._meta_layout = meta_layout

        super().__init__({
            "i_stream":  In(self.i_stream_signature(ioshape,
                ratio=i_ratio, meta_layout=meta_layout)),
            "o_stream": Out(self.o_stream_signature(ioshape,
                meta_layout=meta_layout)),
            "divisor": In(divisor_width),
        })

    def elaborate(self, platform):
        m = Module()

        m.submodules.io_1to2_lane = io_1to2_lane = IO1LaneTo2Lane(IOInputActualLayout(self._ioshape), meta_layout=self._meta_layout)

        with m.If((self.divisor == 0) & (self._i_ratio == 2)):
            # Just pass-through everyting
            for lane_index in range(self._i_ratio):
                m.d.comb += self.o_stream.p[lane_index].actual.eq(self.i_stream.p[lane_index].actual)
                m.d.comb += self.o_stream.p[lane_index].meta.eq(self.i_stream.p[lane_index].meta.inner_meta)
            m.d.comb += self.o_stream.valid.eq(self.i_stream.valid)
            m.d.comb += self.i_stream.ready.eq(self.o_stream.ready)
        with m.Else():
            m.d.comb += io_1to2_lane.i_stream.valid.eq(self.i_stream.valid)
            m.d.comb += self.i_stream.ready.eq(io_1to2_lane.i_stream.ready)
            m.d.comb += io_1to2_lane.i_stream.p[0].eq(self.i_stream.p[0])
            # ^ `wiring.connect` won't work here in case of i_ratio=2, we're explicitly
            # throwing away the second lane here, cause we know IOClocker always sends
            # sample requests on lane 0, (when divisor != 0). In case of i_ratio=1,
            # this is equivalent to `wiring.connect`

            wiring.connect(m, io_1to2_lane=io_1to2_lane.o_stream, io_clocker_deframer=wiring.flipped(self.o_stream))

        return m
