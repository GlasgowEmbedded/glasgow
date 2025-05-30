from functools import reduce
from collections import OrderedDict
from amaranth import *
from amaranth.lib.fifo import FIFOInterface, SyncFIFOBuffered


__all__ = ["EventSource", "EventAnalyzer", "TraceDecodingError", "TraceDecoder"]


REPORT_DELAY        = 0b10000000
REPORT_DELAY_MASK   = 0b10000000
REPORT_EVENT        = 0b01000000
REPORT_EVENT_MASK   = 0b11000000
REPORT_SPECIAL      = 0b00000000
REPORT_SPECIAL_MASK = 0b11000000
SPECIAL_DONE        =   0b000000
SPECIAL_OVERRUN     =   0b000001
SPECIAL_THROTTLE    =   0b000010
SPECIAL_DETHROTTLE  =   0b000011


class _PriorityEncoder(Elaboratable):
    def __init__(self, width):
        self.width = width

        self.i = Signal(width)
        self.o = Signal(range(width))
        self.n = Signal()

    def elaborate(self, platform):
        m = Module()
        for j in reversed(range(self.width)):
            with m.If(self.i[j]):
                m.d.comb += self.o.eq(j)
        m.d.comb += self.n.eq(self.i == 0)
        return m


class _PriorityDecoder(Elaboratable):
    def __init__(self, width):
        self.width = width

        self.i = Signal(range(width))
        self.n = Signal()
        self.o = Signal(width)

    def elaborate(self, platform):
        m = Module()
        with m.Switch(self.i):
            for j in range(len(self.o)):
                with m.Case(j):
                    m.d.comb += self.o.eq(1 << j)
        with m.If(self.n):
            m.d.comb += self.o.eq(0)
        return m


class EventSource(Elaboratable):
    def __init__(self, name, kind, width, fields, depth):
        assert (width >  0 and kind in ("change", "strobe") or
                width == 0 and kind == "strobe")

        self.name    = name
        self.width   = width
        self.fields  = fields
        self.depth   = depth
        self.kind    = kind

        self.data    = Signal(max(1, width))
        self.trigger = Signal()

        if width > 0:
            self.data_fifo = SyncFIFOBuffered(width=width, depth=depth)
        else:
            self.data_fifo = FIFOInterface(width=1, depth=0)

    def elaborate(self, platform):
        m = Module()

        if self.width > 0:
            m.submodules.data_fifo = self.data_fifo

            m.d.comb += [
                self.data_fifo.w_data.eq(self.data),
                self.data_fifo.w_en.eq(self.trigger),
            ]

        return m


class EventAnalyzer(Elaboratable):
    """
    An event analyzer module.

    This event analyzer is designed to observe parallel, bursty processes in real-time, and yet
    degrade gracefully (i.e. without losing data or breaking most applets) when observing processes
    that generate events continuously, or generate very many simultaneous events for a short time.
    To do this, the event analyzer is permitted to pause any applets marked as purely synchronous
    once the event FIFO high-water mark is reached.

    The event analyzer tries to make efficient use of power-of-2 wide block RAMs and be highly
    tunable. To achieve this, it separates the event FIFO from the event data FIFOs, and avoids
    storing timestamps explicitly. In a system with `n` events, each of which carries `d_n` bits
    of data, there would be a single event FIFO that is `n` bits wide, where a bit being set means
    that event `n` occurred at a given cycle; `n` event data FIFOs that are `d_n` bits wide each,
    where, if a bit is set in the event FIFO, a data word is pushed into the event data FIFO; and
    finally, one delay FIFO, where the last entry is incremented on every cycle that has
    no event, and a new entry is pushed on every cycle there is at least one event. This way,
    only cycles that have at least one event add new FIFO entries, and only one wide timestamp
    counter needs to be maintained, greatly reducing the amount of necessary resources compared
    to a more naive approach.
    """

    @staticmethod
    def _depth_for_width(width):
        if width == 0:
            return 0
        elif width <= 2:
            return 2048
        elif width <= 4:
            return 1024
        elif width <= 8:
            return 512
        else:
            return 256

    def __init__(self, output_fifo, event_depth=None, delay_width=16):
        # assert output_fifo.width == 8

        self.output_fifo   = output_fifo
        self.delay_width   = delay_width
        self.event_depth   = event_depth
        self.event_sources = Array()
        self.done          = Signal()
        self.throttle      = Signal()
        self.overrun       = Signal()

        self._delay_timer = Signal(self.delay_width)

    def add_event_source(self, name, kind, width, fields=(), depth=None):
        if depth is None:
            depth = self._depth_for_width(width)

        event_source = EventSource(name, kind, width, fields, depth)
        self.event_sources.append(event_source)
        return event_source

    def elaborate(self, platform):
        m = Module()

        assert len(self.event_sources) < 2 ** 6
        assert max(s.width for s in self.event_sources) <= 32

        # Fill the event, event data, and delay FIFOs.
        throttle_on    = Signal()
        throttle_off   = Signal()
        throttle_edge  = Signal()
        throttle_fifos = []

        with m.If(~self.throttle & throttle_on):
            m.d.sync += [
                self.throttle.eq(1),
                throttle_edge.eq(1),
            ]
        with m.Elif(self.throttle & throttle_off):
            m.d.sync += [
                self.throttle.eq(0),
                throttle_edge.eq(1),
            ]
        with m.Else():
            m.d.sync += [
                throttle_edge.eq(0),
            ]

        overrun_trip   = Signal()
        overrun_fifos  = []
        with m.If(overrun_trip):
            m.d.sync += self.overrun.eq(1)

        event_width = 1 + len(self.event_sources)
        if self.event_depth is None:
            event_depth = min(self._depth_for_width(event_width),
                              self._depth_for_width(self.delay_width))
        else:
            event_depth = self.event_depth

        m.submodules.event_fifo = event_fifo = \
            SyncFIFOBuffered(width=event_width, depth=event_depth)
        throttle_fifos.append(event_fifo)
        m.d.comb += [
            event_fifo.w_data.eq(Cat(self.throttle, [s.trigger for s in self.event_sources])),
            event_fifo.w_en.eq(reduce(lambda a, b: a | b, (s.trigger for s in self.event_sources)) |
                             throttle_edge)
        ]

        m.submodules.delay_fifo = delay_fifo = \
            SyncFIFOBuffered(width=self.delay_width, depth=event_depth)
        delay_timer = self._delay_timer
        delay_ovrun = ((1 << self.delay_width) - 1)
        delay_max   = delay_ovrun - 1
        with m.If(delay_fifo.w_en):
            m.d.sync += delay_timer.eq(0)
        with m.Else():
            m.d.sync += delay_timer.eq(delay_timer + 1)
        m.d.comb += [
            delay_fifo.w_data.eq(Mux(self.overrun, delay_ovrun, delay_timer)),
            delay_fifo.w_en.eq(event_fifo.w_en | (delay_timer == delay_max) |
                             self.done | self.overrun),
        ]

        for event_source in self.event_sources:
            m.submodules += event_source
            if event_source.width > 0:
                throttle_fifos.append(event_source.data_fifo)

        # Throttle applets based on FIFO levels with hysteresis.
        m.d.comb += [
            throttle_on .eq(reduce(lambda a, b: a | b,
                (f.level >= f.depth - f.depth // (4 if f.depth > 4 else 2)
                 for f in throttle_fifos))),
            throttle_off.eq(reduce(lambda a, b: a & b,
                (f.level <            f.depth // (4 if f.depth > 4 else 2)
                 for f in throttle_fifos))),
        ]

        # Detect imminent FIFO overrun and trip overrun indication.
        m.d.comb += [
            overrun_trip.eq(reduce(lambda a, b: a | b,
                (f.level == f.depth - 2
                 for f in throttle_fifos)))
        ]

        # Dequeue events, and serialize events and event data.
        m.submodules.event_encoder = event_encoder = \
            _PriorityEncoder(width=len(self.event_sources))
        m.submodules.event_decoder = event_decoder = \
            _PriorityDecoder(width=len(self.event_sources))
        m.d.comb += event_decoder.i.eq(event_encoder.o)

        rep_overrun      = Signal()
        rep_throttle_new = Signal()
        rep_throttle_cur = Signal()
        delay_septets = 5
        delay_counter = Signal(7 * delay_septets)
        with m.FSM() as serializer:
            with m.State("WAIT-EVENT"):
                with m.If(delay_fifo.r_rdy):
                    m.d.comb += delay_fifo.r_en.eq(1)
                    m.d.sync += delay_counter.eq(delay_counter + delay_fifo.r_data + 1)
                    with m.If(delay_fifo.r_data == delay_ovrun):
                        m.d.sync += rep_overrun.eq(1)
                        m.next = "REPORT-DELAY"
                with m.If(event_fifo.r_rdy):
                    m.d.comb += event_fifo.r_en.eq(1)
                    m.d.sync += event_encoder.i.eq(event_fifo.r_data[1:])
                    m.d.sync += rep_throttle_new.eq(event_fifo.r_data[0])
                    with m.If((event_fifo.r_data != 0) | (rep_throttle_cur != event_fifo.r_data[0])):
                        m.next = "REPORT-DELAY"
                with m.Elif(self.done):
                    m.next = "REPORT-DELAY"
            with m.State("REPORT-DELAY"):
                with m.If(delay_counter >= 128 ** 4):
                    m.next = "REPORT-DELAY-5"
                with m.Elif(delay_counter >= 128 ** 3):
                    m.next = "REPORT-DELAY-4"
                with m.Elif(delay_counter >= 128 ** 2):
                    m.next = "REPORT-DELAY-3"
                with m.Elif(delay_counter >= 128 ** 1):
                    m.next = "REPORT-DELAY-2"
                with m.Else():
                    m.next = "REPORT-DELAY-1"
            for septet_no in range(delay_septets, 0, -1):
                with m.State(f"REPORT-DELAY-{septet_no}"):
                    with m.If(self.output_fifo.w_rdy):
                        m.d.comb += [
                            self.output_fifo.w_data.eq(
                                REPORT_DELAY | delay_counter.word_select(septet_no - 1, 7)),
                            self.output_fifo.w_en.eq(1),
                        ]
                        if septet_no == 1:
                            m.d.sync += delay_counter.eq(0)
                            with m.If(rep_overrun):
                                m.next = "REPORT-OVERRUN"
                            with m.Elif(rep_throttle_cur != rep_throttle_new):
                                m.next = "REPORT-THROTTLE"
                            with m.Elif(event_encoder.i):
                                m.next = "REPORT-EVENT"
                            with m.Elif(self.done):
                                m.next = "REPORT-DONE"
                            with m.Else():
                                m.next = "WAIT-EVENT"
                        else:
                            m.next = f"REPORT-DELAY-{septet_no - 1}"
            with m.State("REPORT-THROTTLE"):
                with m.If(self.output_fifo.w_rdy):
                    m.d.sync += rep_throttle_cur.eq(rep_throttle_new)
                    with m.If(rep_throttle_new):
                        m.d.comb += self.output_fifo.w_data.eq(REPORT_SPECIAL | SPECIAL_THROTTLE)
                    with m.Else():
                        m.d.comb += self.output_fifo.w_data.eq(REPORT_SPECIAL | SPECIAL_DETHROTTLE)
                    m.d.comb += self.output_fifo.w_en.eq(1)
                    with m.If(event_encoder.n):
                        m.next = "WAIT-EVENT"
                    with m.Else():
                        m.next = "REPORT-EVENT"
            event_source = self.event_sources[event_encoder.o]
            event_data   = Signal(32)
            with m.State("REPORT-EVENT"):
                with m.If(self.output_fifo.w_rdy):
                    m.d.sync += event_encoder.i.eq(event_encoder.i & ~event_decoder.o)
                    m.d.comb += [
                        self.output_fifo.w_data.eq(REPORT_EVENT | event_encoder.o),
                        self.output_fifo.w_en.eq(1),
                    ]
                    m.d.sync += event_data.eq(event_source.data_fifo.r_data)
                    m.d.comb += event_source.data_fifo.r_en.eq(1)
                    with m.If(event_source.width > 24):
                        m.next = "REPORT-EVENT-DATA-4"
                    with m.Elif(event_source.width > 16):
                        m.next = "REPORT-EVENT-DATA-3"
                    with m.Elif(event_source.width > 8):
                        m.next = "REPORT-EVENT-DATA-2"
                    with m.Elif(event_source.width > 0):
                        m.next = "REPORT-EVENT-DATA-1"
                    with m.Else():
                        with m.If(event_encoder.i & ~event_decoder.o):
                            m.next = "REPORT-EVENT"
                        with m.Else():
                            m.next = "WAIT-EVENT"
            for octet_no in range(4, 0, -1):
                with m.State(f"REPORT-EVENT-DATA-{octet_no}"):
                    with m.If(self.output_fifo.w_rdy):
                        m.d.comb += [
                            self.output_fifo.w_data.eq(event_data.word_select(octet_no - 1, 8)),
                            self.output_fifo.w_en.eq(1),
                        ]
                        if octet_no == 1:
                            with m.If(event_encoder.n):
                                m.next = "WAIT-EVENT"
                            with m.Else():
                                m.next = "REPORT-EVENT"
                        else:
                            m.next = f"REPORT-EVENT-DATA-{octet_no - 1}"
            with m.State("REPORT-DONE"):
                with m.If(self.output_fifo.w_rdy):
                    m.d.comb += [
                        self.output_fifo.w_data.eq(REPORT_SPECIAL | SPECIAL_DONE),
                        self.output_fifo.w_en.eq(1),
                    ]
                    m.next = "DONE"
            if hasattr(self.output_fifo, "flush"):
                flush_output_fifo = [self.output_fifo.flush.eq(1)]
            else:
                flush_output_fifo = []
            with m.State("DONE"):
                with m.If(self.done):
                    m.d.comb += flush_output_fifo
                with m.Else():
                    m.next = "WAIT-EVENT"
            with m.State("REPORT-OVERRUN"):
                with m.If(self.output_fifo.w_rdy):
                    m.d.comb += [
                        self.output_fifo.w_data.eq(REPORT_SPECIAL | SPECIAL_OVERRUN),
                        self.output_fifo.w_en.eq(1),
                    ]
                    m.next = "OVERRUN"
            with m.State("OVERRUN"):
                m.d.comb += flush_output_fifo
                m.next = "OVERRUN"

        return m


class TraceDecodingError(Exception):
    pass


class TraceDecoder:
    """
    Event analyzer trace decoder.

    Decodes raw analyzer traces into a timestamped sequence of maps from event fields to
    their values.
    """
    def __init__(self, event_sources, absolute_timestamps=True):
        self.event_sources       = event_sources
        self.absolute_timestamps = absolute_timestamps

        self._state      = "IDLE"
        self._byte_off   = 0
        self._timestamp  = 0
        self._delay      = 0
        self._event_src  = 0
        self._event_off  = 0
        self._event_data = 0
        self._pending    = OrderedDict()
        self._timeline   = []

    def events(self):
        """
        Return names and widths for all events that may be emitted by this trace decoder.
        """
        yield ("throttle", "throttle", 1)

        for event_src in self.event_sources:
            if event_src.fields:
                for field_name, field_width in event_src.fields:
                    yield ("{}-{}".format(field_name, event_src.name), event_src.kind, field_width)
            else:
                yield (event_src.name, event_src.kind, event_src.width)

    def _flush_timestamp(self):
        if self._delay == 0:
            return

        if self._pending:
            self._timeline.append((self._timestamp, self._pending))
            self._pending = OrderedDict()

        if self.absolute_timestamps:
            self._timestamp += self._delay
        else:
            self._timestamp  = self._delay
        self._delay = 0

    def process(self, data):
        """
        Incrementally parse a chunk of analyzer trace, and record events in it.
        """
        for octet in data:
            is_delay   = ((octet & REPORT_DELAY_MASK)   == REPORT_DELAY)
            is_event   = ((octet & REPORT_EVENT_MASK)   == REPORT_EVENT)
            is_special = ((octet & REPORT_SPECIAL_MASK) == REPORT_SPECIAL)
            special    = octet & ~REPORT_SPECIAL

            if self._state == "IDLE" and is_delay:
                self._state = "DELAY"
                self._delay = octet & ~REPORT_DELAY_MASK

            elif self._state == "DELAY" and is_delay:
                self._delay = (self._delay << 7) | (octet & ~REPORT_DELAY_MASK)

            elif self._state == "DELAY" and is_special and \
                        special in (SPECIAL_THROTTLE, SPECIAL_DETHROTTLE):
                self._flush_timestamp()

                if special == SPECIAL_THROTTLE:
                    self._pending["throttle"] = 1
                elif special == SPECIAL_DETHROTTLE:
                    self._pending["throttle"] = 0

            elif self._state in ("IDLE", "DELAY") and is_event:
                self._flush_timestamp()

                if (octet & ~REPORT_EVENT_MASK) > len(self.event_sources):
                    raise TraceDecodingError("at byte offset %d: event source out of bounds" %
                                             self._byte_off)
                self._event_src = self.event_sources[octet & ~REPORT_EVENT_MASK]
                if self._event_src.width == 0:
                    self._pending[self._event_src.name] = None
                    self._state = "IDLE"
                else:
                    self._event_off  = self._event_src.width
                    self._event_data = 0
                    self._state = "EVENT"

            elif self._state == "EVENT":
                self._event_data <<= 8
                self._event_data  |= octet
                if self._event_off > 8:
                    self._event_off -= 8
                else:
                    if self._event_src.fields:
                        offset = 0
                        for field_name, field_width in self._event_src.fields:
                            self._pending["{}-{}".format(field_name, self._event_src.name)] = \
                                (self._event_data >> offset) & ((1 << field_width) - 1)
                            offset += field_width
                    else:
                        self._pending[self._event_src.name] = self._event_data

                    self._state = "IDLE"

            elif self._state in "DELAY" and is_special and \
                        special in (SPECIAL_DONE, SPECIAL_OVERRUN):
                self._flush_timestamp()
                if special == SPECIAL_DONE:
                    self._state = "DONE"
                elif special == SPECIAL_OVERRUN:
                    self._state = "OVERRUN"

            else:
                raise TraceDecodingError("at byte offset %d: invalid byte %#04x for state %s" %
                                         (self._byte_off, octet, self._state))

            self._byte_off += 1

    def flush(self, pending=False):
        """
        Return the complete event timeline since the start of decoding or the previous flush.
        If ``pending`` is ``True``, also flushes pending events; this may cause duplicate
        timestamps if more events arrive after the flush.
        """
        if self._state == "OVERRUN":
            self._timeline.append((self._timestamp, "overrun"))
        elif pending and self._pending or self._state == "DONE":
            self._timeline.append((self._timestamp, self._pending))
            self._pending = OrderedDict()

        timeline, self._timeline = self._timeline, []
        return timeline

    def is_done(self):
        return self._state in ("DONE", "OVERRUN")
