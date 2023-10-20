import unittest
from amaranth import *
from amaranth.lib.fifo import SyncFIFOBuffered

from glasgow.gateware import simulation_test
from glasgow.gateware.analyzer import EventAnalyzer, TraceDecoder, REPORT_DELAY, REPORT_EVENT, REPORT_SPECIAL, SPECIAL_DONE, SPECIAL_OVERRUN


class EventAnalyzerTestbench(Elaboratable):
    def __init__(self, **kwargs):
        self.fifo = SyncFIFOBuffered(width=8, depth=64)
        self.dut  = EventAnalyzer(self.fifo, **kwargs)

    def elaborate(self, platform):
        m = Module()

        m.submodules.fifo = self.fifo
        m.submodules.dut = self.dut

        return m

    def trigger(self, index, data):
        yield self.dut.event_sources[index].trigger.eq(1)
        if self.dut.event_sources[index].width > 0:
            yield self.dut.event_sources[index].data.eq(data)

    def step(self):
        yield
        for event_source in self.dut.event_sources:
            yield event_source.trigger.eq(0)

    def read(self, count, limit=128):
        data  = []
        cycle = 0
        while len(data) < count:
            while not (yield self.fifo.r_rdy) and cycle < limit:
                yield
                cycle += 1
            if not (yield self.fifo.r_rdy):
                raise ValueError("FIFO underflow")
            data.append((yield self.fifo.r_data))
            yield self.fifo.r_en.eq(1)
            yield
            yield self.fifo.r_en.eq(0)
            yield

        cycle = 16
        while not (yield self.fifo.r_rdy) and cycle < limit:
            yield
            cycle += 1
        if (yield self.fifo.r_rdy):
            raise ValueError("junk in FIFO: %#04x at %d" % ((yield self.fifo.r_data), count))

        return data


class EventAnalyzerTestCase(unittest.TestCase):
    def setUp(self):
        self.tb = EventAnalyzerTestbench(event_depth=16)

    def configure(self, tb, sources):
        for n, args in enumerate(sources):
            if not isinstance(args, tuple):
                args = (args,)
            tb.dut.add_event_source(str(n), "strobe", *args)

    def assertEmitted(self, tb, data, decoded, flush_pending=True):
        self.assertEqual((yield from tb.read(len(data))), data)

        decoder = TraceDecoder(self.tb.dut.event_sources)
        decoder.process(data)
        self.assertEqual(decoder.flush(flush_pending), decoded)

    @simulation_test(sources=(8,))
    def test_one_8bit_src(self, tb):
        yield from tb.trigger(0, 0xaa)
        yield from tb.step()
        yield from self.assertEmitted(tb, [
            REPORT_DELAY|2,
            REPORT_EVENT|0, 0xaa,
        ], [
            (2, {"0": 0xaa}),
        ])

    @simulation_test(sources=(8,8))
    def test_two_8bit_src(self, tb):
        yield from tb.trigger(0, 0xaa)
        yield from tb.trigger(1, 0xbb)
        yield from tb.step()
        yield from self.assertEmitted(tb, [
            REPORT_DELAY|2,
            REPORT_EVENT|0, 0xaa,
            REPORT_EVENT|1, 0xbb,
        ], [
            (2, {"0": 0xaa, "1": 0xbb}),
        ])

    @simulation_test(sources=(12,))
    def test_one_12bit_src(self, tb):
        yield from tb.trigger(0, 0xabc)
        yield from tb.step()
        yield from self.assertEmitted(tb, [
            REPORT_DELAY|2,
            REPORT_EVENT|0, 0x0a, 0xbc,
        ], [
            (2, {"0": 0xabc}),
        ])

    @simulation_test(sources=(16,))
    def test_one_16bit_src(self, tb):
        yield from tb.trigger(0, 0xabcd)
        yield from tb.step()
        yield from self.assertEmitted(tb, [
            REPORT_DELAY|2,
            REPORT_EVENT|0, 0xab, 0xcd,
        ], [
            (2, {"0": 0xabcd}),
        ])

    @simulation_test(sources=(24,))
    def test_one_24bit_src(self, tb):
        yield from tb.trigger(0, 0xabcdef)
        yield from tb.step()
        yield from self.assertEmitted(tb, [
            REPORT_DELAY|2,
            REPORT_EVENT|0, 0xab, 0xcd, 0xef
        ], [
            (2, {"0": 0xabcdef}),
        ])

    @simulation_test(sources=(32,))
    def test_one_32bit_src(self, tb):
        yield from tb.trigger(0, 0xabcdef12)
        yield from tb.step()
        yield from self.assertEmitted(tb, [
            REPORT_DELAY|2,
            REPORT_EVENT|0, 0xab, 0xcd, 0xef, 0x12
        ], [
            (2, {"0": 0xabcdef12}),
        ])

    @simulation_test(sources=(0,))
    def test_one_0bit_src(self, tb):
        yield from tb.trigger(0, 0)
        yield from tb.step()
        yield from self.assertEmitted(tb, [
            REPORT_DELAY|2,
            REPORT_EVENT|0,
        ], [
            (2, {"0": None}),
        ])

    @simulation_test(sources=(0,0))
    def test_two_0bit_src(self, tb):
        yield from tb.trigger(0, 0)
        yield from tb.trigger(1, 0)
        yield from tb.step()
        yield from self.assertEmitted(tb, [
            REPORT_DELAY|2,
            REPORT_EVENT|0,
            REPORT_EVENT|1,
        ], [
            (2, {"0": None, "1": None}),
        ])

    @simulation_test(sources=(0,1))
    def test_0bit_1bit_src(self, tb):
        yield from tb.trigger(0, 0)
        yield from tb.trigger(1, 1)
        yield from tb.step()
        yield from self.assertEmitted(tb, [
            REPORT_DELAY|2,
            REPORT_EVENT|0,
            REPORT_EVENT|1, 0b1
        ], [
            (2, {"0": None, "1": 0b1}),
        ])

    @simulation_test(sources=(1,0))
    def test_1bit_0bit_src(self, tb):
        yield from tb.trigger(0, 1)
        yield from tb.trigger(1, 0)
        yield from tb.step()
        yield from self.assertEmitted(tb, [
            REPORT_DELAY|2,
            REPORT_EVENT|0, 0b1,
            REPORT_EVENT|1,
        ], [
            (2, {"0": 0b1, "1": None}),
        ])

    @simulation_test(sources=((3, (("a", 1), ("b", 2))),))
    def test_fields(self, tb):
        yield from tb.trigger(0, 0b101)
        yield from tb.step()
        yield from tb.trigger(0, 0b110)
        yield from tb.step()
        yield from self.assertEmitted(tb, [
            REPORT_DELAY|2,
            REPORT_EVENT|0, 0b101,
            REPORT_DELAY|1,
            REPORT_EVENT|0, 0b110,
        ], [
            (2, {"a-0": 0b1, "b-0": 0b10}),
            (3, {"a-0": 0b0, "b-0": 0b11}),
        ])

    @simulation_test(sources=(8,))
    def test_delay(self, tb):
        yield
        yield
        yield from tb.trigger(0, 0xaa)
        yield from tb.step()
        yield
        yield from tb.trigger(0, 0xbb)
        yield from tb.step()
        yield
        yield
        yield from self.assertEmitted(tb, [
            REPORT_DELAY|4,
            REPORT_EVENT|0, 0xaa,
            REPORT_DELAY|2,
            REPORT_EVENT|0, 0xbb,
        ], [
            (4, {"0": 0xaa}),
            (6, {"0": 0xbb}),
        ])

    @simulation_test(sources=(1,))
    @unittest.skip("FIXME: see issue #182")
    def test_delay_2_septet(self, tb):
        yield tb.dut._delay_timer.eq(0b1_1110000)
        yield from tb.trigger(0, 1)
        yield from tb.step()
        yield from self.assertEmitted(tb, [
            REPORT_DELAY|0b0000001,
            REPORT_DELAY|0b1110001,
            REPORT_EVENT|0, 0b1
        ], [
            (0b1_1110001, {"0": 0b1}),
        ])

    @simulation_test(sources=(1,))
    @unittest.skip("FIXME: see issue #182")
    def test_delay_3_septet(self, tb):
        yield tb.dut._delay_timer.eq(0b01_0011000_1100011)
        yield from tb.trigger(0, 1)
        yield from tb.step()
        yield from self.assertEmitted(tb, [
            REPORT_DELAY|0b0000001,
            REPORT_DELAY|0b0011000,
            REPORT_DELAY|0b1100100,
            REPORT_EVENT|0, 0b1
        ], [
            (0b01_0011000_1100100, {"0": 0b1}),
        ])

    @simulation_test(sources=(1,))
    @unittest.skip("FIXME: see issue #182")
    def test_delay_max(self, tb):
        yield tb.dut._delay_timer.eq(0xfffe)
        yield from tb.trigger(0, 1)
        yield from tb.step()
        yield from self.assertEmitted(tb, [
            REPORT_DELAY|0b0000011,
            REPORT_DELAY|0b1111111,
            REPORT_DELAY|0b1111111,
            REPORT_EVENT|0, 0b1
        ], [
            (0xffff, {"0": 0b1}),
        ])

    @simulation_test(sources=(1,))
    @unittest.skip("FIXME: see issue #182")
    def test_delay_overflow(self, tb):
        yield tb.dut._delay_timer.eq(0xfffe)
        yield
        yield from tb.trigger(0, 1)
        yield from tb.step()
        yield from self.assertEmitted(tb, [
            REPORT_DELAY|0b0000100,
            REPORT_DELAY|0b0000000,
            REPORT_DELAY|0b0000000,
            REPORT_EVENT|0, 0b1
        ], [
            (0x10000, {"0": 0b1}),
        ])

    @simulation_test(sources=(1,))
    @unittest.skip("FIXME: see issue #182")
    def test_delay_overflow_p1(self, tb):
        yield tb.dut._delay_timer.eq(0xfffe)
        yield
        yield
        yield from tb.trigger(0, 1)
        yield from tb.step()
        yield from self.assertEmitted(tb, [
            REPORT_DELAY|0b0000100,
            REPORT_DELAY|0b0000000,
            REPORT_DELAY|0b0000001,
            REPORT_EVENT|0, 0b1
        ], [
            (0x10001, {"0": 0b1}),
        ])

    @simulation_test(sources=(1,))
    @unittest.skip("FIXME: see issue #182")
    def test_delay_4_septet(self, tb):
        for _ in range(64):
            yield tb.dut._delay_timer.eq(0xfffe)
            yield

        yield from tb.trigger(0, 1)
        yield from tb.step()
        yield from self.assertEmitted(tb, [
            REPORT_DELAY|0b0000001,
            REPORT_DELAY|0b1111111,
            REPORT_DELAY|0b1111111,
            REPORT_DELAY|0b1000001,
            REPORT_EVENT|0, 0b1
        ], [
            (0xffff * 64 + 1, {"0": 0b1}),
        ])

    @simulation_test(sources=(1,))
    def test_done(self, tb):
        yield from tb.trigger(0, 1)
        yield from tb.step()
        yield
        yield tb.dut.done.eq(1)
        yield from self.assertEmitted(tb, [
            REPORT_DELAY|2,
            REPORT_EVENT|0, 0b1,
            REPORT_DELAY|2,
            REPORT_SPECIAL|SPECIAL_DONE
        ], [
            (2, {"0": 0b1}),
            (4, {})
        ], flush_pending=False)

    @simulation_test(sources=(1,))
    def test_throttle_hyst(self, tb):
        for x in range(16):
            yield from tb.trigger(0, 1)
            yield from tb.step()
            self.assertEqual((yield tb.dut.throttle), 0)
        yield from tb.trigger(0, 1)
        yield from tb.step()
        self.assertEqual((yield tb.dut.throttle), 1)
        yield tb.fifo.r_en.eq(1)
        for x in range(52):
            yield
        yield tb.fifo.r_en.eq(0)
        yield
        self.assertEqual((yield tb.dut.throttle), 0)

    @simulation_test(sources=(1,))
    def test_overrun(self, tb):
        for x in range(18):
            yield from tb.trigger(0, 1)
            yield from tb.step()
            self.assertEqual((yield tb.dut.overrun), 0)
        yield from tb.trigger(0, 1)
        yield from tb.step()
        self.assertEqual((yield tb.dut.overrun), 1)
        yield tb.fifo.r_en.eq(1)
        for x in range(55):
            while not (yield tb.fifo.r_rdy):
                yield
            yield
        yield tb.fifo.r_en.eq(0)
        yield
        yield from self.assertEmitted(tb, [
            REPORT_DELAY|0b0000100,
            REPORT_DELAY|0b0000000,
            REPORT_DELAY|0b0000000,
            REPORT_SPECIAL|SPECIAL_OVERRUN,
        ], [
            (0x10000, "overrun"),
        ], flush_pending=False)
