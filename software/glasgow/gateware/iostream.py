from amaranth import *
from amaranth.lib import enum, data, wiring, stream, io
from amaranth.lib.wiring import In, Out

from glasgow.gateware.ports import PortGroup


__all__ = ["IOStreamer"]


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


class IOStreamer(wiring.Component):
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

    @staticmethod
    def o_stream_signature(ioshape, /, *, ratio=1, meta_layout=0):
        return stream.Signature(data.StructLayout({
            "port": _map_ioshape("o", ioshape, lambda width: data.StructLayout({
                "o":  width if ratio == 1 else data.ArrayLayout(width, ratio),
                "oe": 1,
            })),
            "i_en": 1,
            "meta": meta_layout,
        }))

    @staticmethod
    def i_stream_signature(ioshape, /, *, ratio=1, meta_layout=0):
        return stream.Signature(data.StructLayout({
            "port": _map_ioshape("i", ioshape, lambda width: data.StructLayout({
                "i":  width if ratio == 1 else data.ArrayLayout(width, ratio),
            })),
            "meta": meta_layout,
        }))

    def __init__(self, ioshape, ports, /, *, ratio=1, init=None, meta_layout=0, sample_delay_half_clocks=0):
        if ratio == 1:
            assert (sample_delay_half_clocks % 2) == 0
        assert isinstance(ioshape, (int, dict))
        assert ratio in (1, 2)

        self._ioshape = ioshape
        self._ports   = ports
        self._ratio   = ratio
        self._init    = init
        self._sample_delay_half_clocks = sample_delay_half_clocks

        super().__init__({
            "o_stream":  In(self.o_stream_signature(ioshape, ratio=ratio, meta_layout=meta_layout)),
            "i_stream": Out(self.i_stream_signature(ioshape, ratio=ratio, meta_layout=meta_layout)),
        })

    def elaborate(self, platform):
        m = Module()

        if self._ratio == 1:
            buffer_cls, latency = io.FFBuffer, 1 + self._sample_delay_half_clocks // 2
        if self._ratio == 2:
            buffer_cls, latency = SimulatableDDRBuffer, 2 + (self._sample_delay_half_clocks // 2) + (self._sample_delay_half_clocks % 2)

        if isinstance(self._ports, io.PortLike):
            m.submodules.buffer = buffer = buffer_cls("io", self._ports)
        if isinstance(self._ports, PortGroup):
            buffer = {}
            for name, sub_port in self._ports.__dict__.items():
                direction, _width = self._ioshape[name]
                m.submodules[f"buffer_{name}"] = buffer[name] = buffer_cls(direction, sub_port)

        o_latch = Signal(_map_ioshape("o", self._ioshape, lambda width: data.StructLayout({
            "o":  width,
            "oe": 1,
        })), init=self._init)
        with m.If(self.o_stream.valid & self.o_stream.ready):
            for _, buffer_parts, stream_parts in _iter_ioshape("o", self._ioshape,
                    buffer, self.o_stream.p.port):
                m.d.comb += buffer_parts.o.eq(stream_parts.o)
                m.d.comb += buffer_parts.oe.eq(stream_parts.oe)
            for _, latch_parts, stream_parts in _iter_ioshape("o", self._ioshape,
                    o_latch, self.o_stream.p.port):
                if self._ratio == 1:
                    m.d.sync += latch_parts.o.eq(stream_parts.o)
                else:
                    m.d.sync += latch_parts.o.eq(stream_parts.o[-1])
                m.d.sync += latch_parts.oe.eq(stream_parts.oe)
        with m.Else():
            for _, buffer_parts, latch_parts in _iter_ioshape("o", self._ioshape,
                    buffer, o_latch):
                if self._ratio == 1:
                    m.d.comb += buffer_parts.o.eq(latch_parts.o)
                else:
                    m.d.comb += buffer_parts.o.eq(latch_parts.o.replicate(self._ratio))
                m.d.comb += buffer_parts.oe.eq(latch_parts.oe)

        def delay(value, name):
            for stage in range(latency):
                next_value = Signal.like(value, name=f"{name}_{stage}")
                m.d.sync += next_value.eq(value)
                value = next_value
            return value

        i_en = delay(self.o_stream.valid & self.o_stream.ready &
                     self.o_stream.p.i_en, name="i_en")
        meta = delay(self.o_stream.p.meta, name="meta")

        # This skid buffer is organized as a shift register to avoid any uncertainties associated
        # with the use of an async read memory. On platforms that have LUTRAM, this implementation
        # may be slightly worse than using LUTRAM, and may have to be revisited in the future.
        skid = Array(Signal(self.i_stream.payload.shape(), name=f"skid_{stage}")
                     for stage in range(1 + latency))
        for name, skid_parts, buffer_parts in _iter_ioshape("i", self._ioshape, skid[0].port, buffer):
            if self._sample_delay_half_clocks % 2:
                m.d.comb += skid_parts.i[1].eq(buffer_parts.i[0])
                i1_delayed = Signal.like(buffer_parts.i[1], name=f"{name}_i1_delayed")
                m.d.sync += i1_delayed.eq(buffer_parts.i[1])
                m.d.comb += skid_parts.i[0].eq(i1_delayed)
            else:
                m.d.comb += skid_parts.i.eq(buffer_parts.i)
        m.d.comb += skid[0].meta.eq(meta)

        skid_at = Signal(range(1 + latency))

        with m.If(i_en):
            for n_shift in range(latency):
                m.d.sync += skid[n_shift + 1].eq(skid[n_shift])

        with m.If(i_en & ~self.i_stream.ready):
            # m.d.sync += Assert(skid_at != latency)
            m.d.sync += skid_at.eq(skid_at + 1)
        with m.Elif((skid_at != 0) & ~i_en & self.i_stream.ready):
            m.d.sync += skid_at.eq(skid_at - 1)

        m.d.comb += self.i_stream.payload.eq(skid[skid_at])
        m.d.comb += self.i_stream.valid.eq(i_en | (skid_at != 0))
        m.d.comb += self.o_stream.ready.eq(self.i_stream.ready & (skid_at == 0))

        return m


class IOClocker(wiring.Component):
    @staticmethod
    def i_stream_signature(ioshape, /, *, _ratio=1, meta_layout=0):
        # Currently the only supported ratio is 1, but this will change in the future for
        # interfaces like HyperBus.
        return stream.Signature(data.StructLayout({
            "bypass": 1,
            "port": _map_ioshape("o", ioshape, lambda width: data.StructLayout({
                "o":  width if _ratio == 1 else data.ArrayLayout(width, _ratio),
                "oe": 1,
            })),
            "i_en": 1,
            "meta": meta_layout,
        }))

    @staticmethod
    def o_stream_signature(ioshape, /, *, ratio=1, meta_layout=0):
        return IOStreamer.o_stream_signature(ioshape, ratio=ratio, meta_layout=meta_layout)

    def __init__(self, ioshape, *, clock, o_ratio=1, meta_layout=0, divisor_width=16):
        assert isinstance(ioshape, dict)
        assert isinstance(clock, str)
        assert o_ratio in (1, 2)
        assert clock in ioshape

        self._clock   = clock
        self._ioshape = ioshape
        self._o_ratio = o_ratio

        super().__init__({
            "i_stream":  In(self.i_stream_signature(ioshape,
                meta_layout=meta_layout)),
            "o_stream": Out(self.o_stream_signature(ioshape,
                ratio=o_ratio, meta_layout=meta_layout)),

            # f_clk = f_sync if (o_ratio == 2 and divisor == 0) else f_sync / (2 * max(1, divisor))
            "divisor": In(divisor_width),
        })

    def elaborate(self, platform):
        m = Module()

        # Forward the inputs to the outputs as-is. This includes the clock; it is overridden below
        # if the clocker is used (not bypassed).
        for _, i_parts, o_parts in _iter_ioshape("io", self._ioshape,
                self.i_stream.p.port, self.o_stream.p.port):
            m.d.comb += o_parts.o .eq(i_parts.o.replicate(self._o_ratio))
            m.d.comb += o_parts.oe.eq(i_parts.oe)
        m.d.comb += self.o_stream.p.i_en.eq(self.i_stream.p.i_en)
        m.d.comb += self.o_stream.p.meta.eq(self.i_stream.p.meta)

        phase = Signal()
        # If the clocker is used...
        with m.If(~self.i_stream.p.bypass):
            # ... ignore the clock in the inputs and replace it with the generated one...
            if self._o_ratio == 1:
                m.d.comb += self.o_stream.p.port[self._clock].o.eq(phase)
            if self._o_ratio == 2:
                with m.If(self.divisor == 0):
                    m.d.comb += self.o_stream.p.port[self._clock].o.eq(Cat(~phase, phase))
                with m.Else():
                    m.d.comb += self.o_stream.p.port[self._clock].o.eq(Cat(phase, phase))
            m.d.comb += self.o_stream.p.port[self._clock].oe.eq(1)
            # ... while requesting input sampling only for the rising edge. (Interfaces triggering
            # transfers on falling edge will be inverting the clock at the `IOPort` level.)
            m.d.comb += self.o_stream.p.i_en.eq(self.i_stream.p.i_en & phase)

        timer = Signal.like(self.divisor)
        with m.If((timer == 0) | (timer == 1)):
            # Only produce output when the timer has expired. This ensures that no clock pulse
            # exceeds the frequency set by `divisor`, except the ones that bypass the clocker.
            m.d.comb += self.o_stream.valid.eq(self.i_stream.valid)

            with m.FSM():
                with m.State("Falling"):
                    with m.If(self.i_stream.p.bypass): # Bypass the clocker entirely.
                        m.d.comb += self.i_stream.ready.eq(self.o_stream.ready)

                    with m.Else(): # Produce a falling edge at the output.
                        # Whenever DDR output is used, with `divisor == 0`, we output a low state
                        # on the first half of the clock cycle, and a high state on the second half.
                        # This mode allows clocking the peripheral at the `sync` frequency.
                        # In this case the signal sampled at the rising edge will be output on i[1]
                        # (if sample_delay was set to zero)
                        # In all other cases the signal sampled at the rising edge will be output on i[0]
                        # (if sample_delay was set to zero)
                        with m.If((self._o_ratio == 2) & (self.divisor == 0)):
                            m.d.comb += phase.eq(1)
                            with m.If(self.o_stream.ready):
                                m.d.comb += self.i_stream.ready.eq(1)
                        with m.Else():
                            m.d.comb += phase.eq(0)
                            with m.If(self.o_stream.ready & self.i_stream.valid):
                                m.d.sync += timer.eq(self.divisor)
                                m.next = "Rising"

                with m.State("Rising"):
                    m.d.comb += phase.eq(1)
                    with m.If(self.o_stream.ready):
                        m.d.comb += self.i_stream.ready.eq(1)
                        m.d.sync += timer.eq(self.divisor)
                        m.next = "Falling"

        with m.Else():
            m.d.sync += timer.eq(timer - 1)

        return m
