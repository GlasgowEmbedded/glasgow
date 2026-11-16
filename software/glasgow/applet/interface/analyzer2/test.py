from contextlib import contextmanager

from amaranth import *
from amaranth.lib import io, wiring
from amaranth.sim import Simulator

from glasgow.gateware.stream import stream_put, stream_get, stream_assert
from glasgow.gateware import octoram
from glasgow.applet import GlasgowAppletV2TestCase, applet_v2_simulation_test
from glasgow.simulation.assembly import SimulationAssembly
from . import (AnalyzerApplet, PinSampler, BasicTrigger, Writer, Reader, WriteControl, AnalyzerCore,
               Arbiter, Marker, Event, DigitalFormat, DigitalTrigger)


class AnalyzerAppletTestCase(GlasgowAppletV2TestCase, applet=AnalyzerApplet):
    # @synthesis_test
    # def test_build(self):
    #     self.assertBuilds()

    @contextmanager
    def run_test(self, dut, name="test"):
        sim = Simulator(dut)
        sim.add_clock(1/48e6,  domain="sync")
        yield sim
        if hasattr(self, "_dram_testbench"):
            sim.add_clock(1/100e6, domain="dram")
            sim.add_testbench(self._dram_testbench, background=True)
        with sim.write_vcd(f"{name}.vcd"):
            sim.run()

    def _Module_with_dram(self, *, size: int):
        m = Module()

        m.submodules.dram_ctrl = dram_ctrl = DomainRenamer("dram")(
            octoram.SimulationController(size))
        self._dram_testbench = dram_ctrl.testbench

        m.submodules.dram_queue = dram_queue = octoram.InterfaceQueue(
            i_domain="sync", o_domain="dram",
            w_buffer_depth=256,
            r_buffer_depth=256,
        )
        wiring.connect(m, dram_queue.o, dram_ctrl.bus)

        return m, dram_ctrl.memory, dram_queue.i

    def test_digital_format(self):
        def check_width(width, stride):
            format = DigitalFormat.for_width(width)
            assert format.stride == stride

        check_width(1,  1)
        check_width(2,  2)
        check_width(3,  4)
        check_width(4,  4)
        check_width(5,  8)
        check_width(8,  8)
        check_width(9,  16)
        check_width(16, 16)
        check_width(17, 32)
        check_width(32, 32)

    def test_sampler_basic(self):
        pins = io.SimulationPort("i", 32)
        dut = PinSampler(format=DigitalFormat.for_width(32), pins=pins)

        async def testbench_pins(ctx):
            ctx.set(dut.control.divisor, divisor)
            for value in range(0, 64):
                ctx.set(pins.i, value)
                await ctx.tick()

        for divisor in (0, 1, 4):
            async def testbench_samples(ctx):
                await stream_assert(ctx, dut.o_samples, {"data": 0})
                for expected in range(divisor, 64, divisor + 1):
                    await stream_assert(ctx, dut.o_samples, {"data": expected})

            with self.run_test(dut) as sim:
                sim.add_testbench(testbench_pins, background=True)
                sim.add_testbench(testbench_samples)

    def test_sampler_packing_8(self):
        pins = io.SimulationPort("i", 8)
        dut = PinSampler(format=DigitalFormat.for_width(8), pins=pins)

        async def testbench_pins(ctx):
            for value in range(0, 64):
                ctx.set(pins.i, value)
                await ctx.tick()

        async def testbench_samples(ctx):
            await stream_assert(ctx, dut.o_samples, {"data": 0x02010000})
            await stream_assert(ctx, dut.o_samples, {"data": 0x06050403})

        with self.run_test(dut) as sim:
            sim.add_testbench(testbench_pins, background=True)
            sim.add_testbench(testbench_samples)

    def test_sampler_packing_14(self):
        pins = io.SimulationPort("i", 14)
        dut = PinSampler(format=DigitalFormat.for_width(14), pins=pins)

        async def testbench_pins(ctx):
            for value in range(0, 64):
                ctx.set(pins.i, 0xff00|value)
                await ctx.tick()

        async def testbench_samples(ctx):
            await stream_assert(ctx, dut.o_samples, {"data": 0x3f000000})
            await stream_assert(ctx, dut.o_samples, {"data": 0x3f023f01})

        with self.run_test(dut) as sim:
            sim.add_testbench(testbench_pins, background=True)
            sim.add_testbench(testbench_samples)

    def test_trigger_level(self):
        dut = BasicTrigger(format=DigitalFormat.for_width(32))

        async def testbench_samples(ctx):
            for value in range(0, 64):
                await stream_put(ctx, dut.i_samples, {"data": value})
                await ctx.tick()

        async def testbench_events(ctx):
            ctx.set(dut.control[1], {"active": 1, "value": 1, "level": 1})
            await stream_put(ctx, dut.i_events, Event.EnableTrig)
            await ctx.tick()
            await ctx.tick()
            await ctx.tick()
            await stream_put(ctx, dut.i_events, Event.EnableTrig)

        async def testbench_triggers(ctx):
            await stream_assert(ctx, dut.o_samples,
                    {"data": 0, "meta": {"marker": Marker.Normal}})
            await stream_assert(ctx, dut.o_samples,
                    {"data": 1, "meta": {"marker": Marker.Normal}})
            await stream_assert(ctx, dut.o_samples,
                    {"data": 2, "meta": {"marker": Marker.Trigger}})
            await stream_assert(ctx, dut.o_samples,
                    {"data": 3, "meta": {"marker": Marker.Trigger}})
            await stream_assert(ctx, dut.o_samples,
                    {"data": 4, "meta": {"marker": Marker.Normal}})

        with self.run_test(dut) as sim:
            sim.add_testbench(testbench_samples, background=True)
            sim.add_testbench(testbench_events)
            sim.add_testbench(testbench_triggers)

    def test_trigger_edge(self):
        dut = BasicTrigger(format=DigitalFormat.for_width(32))

        async def testbench_samples(ctx):
            for value in range(0, 64):
                await stream_put(ctx, dut.i_samples, {"data": value})
                await ctx.tick()

        async def testbench_events(ctx):
            ctx.set(dut.control[1], {"active": 1, "value": 1, "level": 0})
            for _ in range(2):
                await stream_put(ctx, dut.i_events, Event.EnableTrig)

        async def testbench_triggers(ctx):
            await stream_assert(ctx, dut.o_samples,
                    {"data": 0, "meta": {"marker": Marker.Normal}})
            await stream_assert(ctx, dut.o_samples,
                    {"data": 1, "meta": {"marker": Marker.Normal}})
            await stream_assert(ctx, dut.o_samples,
                    {"data": 2, "meta": {"marker": Marker.Trigger}})
            await stream_assert(ctx, dut.o_samples,
                    {"data": 3, "meta": {"marker": Marker.Normal}})
            await stream_assert(ctx, dut.o_samples,
                    {"data": 4, "meta": {"marker": Marker.Normal}})

        with self.run_test(dut) as sim:
            sim.add_testbench(testbench_samples, background=True)
            sim.add_testbench(testbench_events)
            sim.add_testbench(testbench_triggers)

    def test_trigger_force(self):
        dut = BasicTrigger(format=DigitalFormat.for_width(32))

        async def testbench_samples(ctx):
            for value in range(0, 64):
                await stream_put(ctx, dut.i_samples, {"data": value})
                await ctx.tick()

        async def testbench_events(ctx):
            for _ in range(4):
                await ctx.tick()
            await stream_put(ctx, dut.i_events, Event.ForceTrig)
            await ctx.tick()

        async def testbench_triggers(ctx):
            await stream_assert(ctx, dut.o_samples,
                    {"data": 0, "meta": {"marker": Marker.Normal}})
            await stream_assert(ctx, dut.o_samples,
                    {"data": 1, "meta": {"marker": Marker.Normal}})
            await stream_assert(ctx, dut.o_samples,
                    {"data": 2, "meta": {"marker": Marker.Normal}})
            await stream_assert(ctx, dut.o_samples,
                    {"data": 3, "meta": {"marker": Marker.Trigger}})
            await stream_assert(ctx, dut.o_samples,
                    {"data": 4, "meta": {"marker": Marker.Normal}})

        with self.run_test(dut) as sim:
            sim.add_testbench(testbench_samples, background=True)
            sim.add_testbench(testbench_events)
            sim.add_testbench(testbench_triggers)

    def test_trigger_event_backpressure(self):
        dut = BasicTrigger(format=DigitalFormat.for_width(32))

        async def testbench_samples(ctx):
            for value in range(0, 64):
                await stream_put(ctx, dut.i_samples, {"data": value})
                await ctx.tick()
                await ctx.tick()
                await ctx.tick()

        async def testbench_events(ctx):
            for _ in range(4):
                await ctx.tick()
            await stream_put(ctx, dut.i_events, Event.Interrupt)
            await stream_put(ctx, dut.i_events, Event.ForceTrig)
            await ctx.tick()

        async def testbench_triggers(ctx):
            await stream_assert(ctx, dut.o_samples,
                    {"data": 0, "meta": {"marker": Marker.Normal}})
            await stream_assert(ctx, dut.o_samples,
                    {"data": 1, "meta": {"marker": Marker.Normal}})
            await stream_assert(ctx, dut.o_samples,
                    {"data": 2, "meta": {"marker": Marker.Discard}})
            await stream_assert(ctx, dut.o_samples,
                    {"data": 3, "meta": {"marker": Marker.Trigger}})
            await stream_assert(ctx, dut.o_samples,
                    {"data": 4, "meta": {"marker": Marker.Normal}})

        with self.run_test(dut) as sim:
            sim.add_testbench(testbench_samples, background=True)
            sim.add_testbench(testbench_events)
            sim.add_testbench(testbench_triggers)

    def test_trigger_offset(self):
        dut = BasicTrigger(format=DigitalFormat(width=5, stride=8))

        async def testbench_samples(ctx):
            await ctx.tick()
            await stream_put(ctx, dut.i_samples, {"data": 0x00000000})
            await stream_put(ctx, dut.i_samples, {"data": 0x00000100})

        async def testbench_events(ctx):
            ctx.set(dut.control[0].active, 1)
            ctx.set(dut.control[0].value,  1)
            await stream_put(ctx, dut.i_events, Event.EnableTrig)

        async def testbench_triggers(ctx):
            await stream_assert(ctx, dut.o_samples,
                    {"data": 0x00000000, "meta": {"marker": Marker.Normal}})
            await stream_assert(ctx, dut.o_samples,
                    {"data": 0x00000100, "meta": {"marker": Marker.Trigger, "offset": 8}})

        with self.run_test(dut) as sim:
            sim.add_testbench(testbench_samples, background=True)
            sim.add_testbench(testbench_events)
            sim.add_testbench(testbench_triggers)

    def test_trigger_horiz(self):
        dut = BasicTrigger(format=DigitalFormat(width=8, stride=8))

        async def testbench_samples(ctx):
            await stream_put(ctx, dut.i_samples, {"data": 0x01010101})
            await stream_put(ctx, dut.i_samples, {"data": 0x01010101})
            await stream_put(ctx, dut.i_samples, {"data": 0x01010000})

        async def testbench_events(ctx):
            ctx.set(dut.control[0], {"active": 1, "value": 1, "level": 0})
            await ctx.tick()
            await stream_put(ctx, dut.i_events, Event.EnableTrig)

        async def testbench_triggers(ctx):
            await stream_assert(ctx, dut.o_samples, {"data": 0x01010101})
            await stream_assert(ctx, dut.o_samples, {"data": 0x01010101})
            await stream_assert(ctx, dut.o_samples, {"data": 0x01010000,
                "meta": {"marker": Marker.Trigger, "offset": 16}})

        with self.run_test(dut) as sim:
            sim.add_testbench(testbench_samples)
            sim.add_testbench(testbench_events)
            sim.add_testbench(testbench_triggers)

    def test_arbiter(self):
        m, dram_memory, dram_bus = self._Module_with_dram(size=0x100)
        m.submodules.dut = dut = Arbiter(queue_bytes=0x40, burst_bytes=0x20)
        wiring.connect(m, dut.dram, dram_bus)

        async def testbench_data(ctx):
            for val in range(0, 64, 2):
                await stream_put(ctx, dut.w_data, [val+0, val+1])

            for val in range(0,  16, 2):
                self.assertEqual(list(await stream_get(ctx, dut.r_data)), [val+0, val+1])
            for val in range(32, 64, 2):
                self.assertEqual(list(await stream_get(ctx, dut.r_data)), [val+0, val+1])

        async def testbench_cmd(ctx):
            await stream_put(ctx, dut.w_cmd, {"addr": 0x10, "size": 0x20})
            await ctx.tick().repeat(64)
            self.assertEqual(dram_memory[0x10:0x10+0x20], bytes(range(0x00, 0x20)),
                msg=f"{dram_memory[0x10:0x10+0x20].hex()}")

            await stream_put(ctx, dut.w_cmd, {"addr": 0x20, "size": 0x20})
            await ctx.tick().repeat(64)
            self.assertEqual(dram_memory[0x20:0x20+0x20], bytes(range(0x20, 0x40)))

            await stream_put(ctx, dut.r_cmd, {"addr": 0x10, "size": 0x30})

        with self.run_test(m) as sim:
            sim.add_testbench(testbench_data)
            sim.add_testbench(testbench_cmd)

    def test_writer(self):
        m, dram_memory, dram_bus = self._Module_with_dram(size=0x40)
        m.submodules.arb    = arb = Arbiter(queue_bytes=0x40, burst_bytes=0x20)
        m.submodules.writer = dut = Writer(dram_range=range(len(dram_memory)), burst_bytes=0x20)
        wiring.connect(m, arb.dram,   dram_bus)
        wiring.connect(m, dut.w_data, arb.w_data)
        wiring.connect(m, dut.w_cmd,  arb.w_cmd)

        async def testbench_samples(ctx):
            for packed in [
                {"data": [0x10,0x32,0x54,0x76], "meta": {}},
                {"data": [0x98,0xBA,0xDC,0xFE], "meta": {}},
                {"data": [0x00,0x11,0x22,0x33], "meta": {}},
                {"data": [0x44,0x55,0x66,0x77], "meta": {}},

                {"data": [0x00,0x00,0x11,0x11], "meta": {}},
                {"data": [0x22,0x22,0x33,0x33], "meta": {}},
                {"data": [0x44,0x44,0x55,0x55], "meta": {}},
                {"data": [0x66,0x66,0x77,0x77], "meta": {}},
            ]:
                await stream_put(ctx, dut.i_samples, packed)

            await ctx.tick().repeat(32)

            for packed in [
                {"data": [0xA0,0xA1,0xA2,0xA3], "meta": {}},
                {"data": [0xB0,0xB1,0xB2,0xB3], "meta": {"marker": Marker.Trigger, "offset": 16}},
            ]:
                await stream_put(ctx, dut.i_samples, packed)

            await ctx.tick().repeat(32)

            for packed in [
                {"data": [0x00,0x00,0x11,0x11], "meta": {}},
                {"data": [0x22,0x22,0x33,0x33], "meta": {}},
                {"data": [0x44,0x44,0x55,0x55], "meta": {}},
                {"data": [0x66,0x66,0x77,0x77], "meta": {}},

                {"data": [0x00,0x00,0x11,0x11], "meta": {}},
                {"data": [0xE0,0xE1,0xE2,0xE3], "meta": {}},

                {"data": [0xF0,0xF1,0xF2,0xF3], "meta": {"marker": Marker.Overflow}},
            ]:
                await stream_put(ctx, dut.i_samples, packed)

            await ctx.tick().repeat(32)

            for packed in [
                {"data": [0xD0,0xD1,0xD2,0xD3], "meta": {"marker": Marker.Complete}},
            ]:
                await stream_put(ctx, dut.i_samples, packed)

        async def testbench_blocks(ctx):
            assert dram_memory[ 0: 4] == b"\x00\x00\x00\x00", dram_memory.hex()

            await stream_assert(ctx, dut.o_blocks,
                {"size": 32, "meta": {}})
            await ctx.tick().repeat(32)
            assert dram_memory[ 0: 4] == b"\x10\x32\x54\x76", dram_memory.hex()
            assert dram_memory[28:32] == b"\x66\x66\x77\x77", dram_memory.hex()

            await stream_assert(ctx, dut.o_blocks,
                {"size":  8, "meta": {"marker": Marker.Trigger, "offset": 16}})
            await ctx.tick().repeat(32)
            assert dram_memory[32:36] == b"\xA0\xA1\xA2\xA3", dram_memory.hex()

            await stream_assert(ctx, dut.o_blocks,
                {"size": 24, "meta": {}})
            await ctx.tick().repeat(32)
            assert dram_memory[60:64] == b"\xE0\xE1\xE2\xE3", dram_memory.hex()

            await stream_assert(ctx, dut.o_blocks,
                {"size": 4, "meta": {"marker": Marker.Overflow}})
            await ctx.tick().repeat(32)
            assert dram_memory[0:4] == b"\xF0\xF1\xF2\xF3", dram_memory.hex()

            await stream_assert(ctx, dut.o_blocks,
                {"size": 4, "meta": {"marker": Marker.Complete}})
            await ctx.tick().repeat(32)
            assert dram_memory[4:8] == b"\xD0\xD1\xD2\xD3", dram_memory.hex()

        with self.run_test(m) as sim:
            sim.add_testbench(testbench_samples)
            sim.add_testbench(testbench_blocks)

    def test_reader(self):
        m, dram_memory, dram_bus = self._Module_with_dram(size=0x40)
        m.submodules.arb    = arb = Arbiter(queue_bytes=0x40, burst_bytes=0x20)
        m.submodules.reader = dut = Reader(dram_range=range(len(dram_memory)), burst_bytes=32)
        wiring.connect(m, arb.dram,   dram_bus)
        wiring.connect(m, dut.r_data, arb.r_data)
        wiring.connect(m, dut.r_cmd,  arb.r_cmd)

        dram_memory[:] = bytes(range(64))

        async def testbench_ranges(ctx):
            await stream_put(ctx, dut.i_blocks, {"skip": 0, "size": 32,
                                                 "meta": {"marker": Marker.Trigger, "offset": 1}})
            await stream_put(ctx, dut.i_blocks, {"skip": 1, "size": 28})
            await stream_put(ctx, dut.i_blocks, {"skip": 0, "size":  8,
                                                 "meta": {"marker": Marker.Complete, "offset": 8}})

        async def testbench_octets(ctx):
            for index, expected in enumerate([
                *range(0,  32),
            ]):
                assert (payload := await stream_get(ctx, dut.o_octets)) == {"data": expected}, \
                    f"[{index}]: {payload['data']:02x} != {expected:02x}"

            await stream_assert(ctx, dut.o_octets, {"data": 0x81})
            await stream_assert(ctx, dut.o_octets, {"end":  1})

            for index, expected in enumerate([
                *range(60, 64),
                *range(0,   4),
            ]):
                assert (payload := await stream_get(ctx, dut.o_octets)) == {"data": expected}, \
                    f"[{index}]: {payload['data']:02x} != {expected:02x}"

            await stream_assert(ctx, dut.o_octets, {"data": 0xC8})
            await stream_assert(ctx, dut.o_octets, {"end":  1})

        with self.run_test(m) as sim:
            sim.add_testbench(testbench_ranges, background=True)
            sim.add_testbench(testbench_octets)

    def test_write_control(self):
        dut = WriteControl(
            writer_shape=1,
            writer_ratio=2,
            reader_shape=1,
            reader_ratio=1,
            max_credits=10,
        )

        async def testbench_main(ctx):
            ctx.set(dut.free_running, 1)
            ctx.set(dut.prolog_size, 6)

            await stream_put(ctx, dut.i_writer, 0)
            assert ctx.get(dut.credits) == 2
            await stream_put(ctx, dut.i_writer, 0)
            assert ctx.get(dut.credits) == 4
            await stream_put(ctx, dut.i_writer, 0)
            assert ctx.get(dut.credits) == 6
            await stream_put(ctx, dut.i_writer, 0)
            assert ctx.get(dut.credits) == 6

            ctx.set(dut.free_running, 0)

            await stream_put(ctx, dut.i_reader, 0)
            assert ctx.get(dut.credits) == 5
            await stream_put(ctx, dut.i_reader, 0)
            assert ctx.get(dut.credits) == 4

            await stream_put(ctx, dut.i_writer, 0)
            assert ctx.get(dut.credits) == 6
            await stream_put(ctx, dut.i_writer, 0)
            assert ctx.get(dut.credits) == 8
            await stream_put(ctx, dut.i_writer, 0)
            assert ctx.get(dut.credits) == 10
            await stream_put(ctx, dut.i_writer, 0)
            assert not ctx.get(dut.i_writer.ready)

        async def testbench_w_sink(ctx):
            while True:
                await stream_get(ctx, dut.o_writer)

        async def testbench_r_sink(ctx):
            while True:
                await stream_get(ctx, dut.o_reader)

        with self.run_test(dut) as sim:
            sim.add_testbench(testbench_main)
            sim.add_testbench(testbench_w_sink, background=True)
            sim.add_testbench(testbench_r_sink, background=True)

    def test_integration(self):
        pins = io.SimulationPort("i", 8)

        m, _dram_memory, dram_bus = self._Module_with_dram(size=0x100)
        m.submodules.core = dut = AnalyzerCore(
            dram_range=range(0x1000), burst_bytes=0x20, queue_bytes=0x40,
            data_format=DigitalFormat(width=8, stride=8), pins=pins)
        wiring.connect(m, dut.dram, dram_bus)

        async def testbench_ctrl(ctx):
            ctx.set(dut.control.sampler.divisor, 1)

            ctx.set(dut.control.readout.prolog_size, 8)
            ctx.set(dut.control.readout.epilog_size, 8)

            # pins==0x40
            ctx.set(dut.control.trigger[5], {"active": 1, "value": 1, "level": 0})

            await stream_put(ctx, dut.control.events, Event.EnableTrig)

        async def testbench_i(ctx):
            for value in range(0x80):
                await ctx.tick()
                await ctx.tick()
                ctx.set(pins.i, value&0xff)

        async def testbench_o(ctx):
            for idx, expected in enumerate([
                {"data": 0x1A}, {"data": 0x1B}, {"data": 0x1C}, {"data": 0x1D},
                {"data": 0x1E}, {"data": 0x1F}, {"data": 0x20}, {"data": 0x21},
                {"data": 0x80|16}, {"end": 1},
                {"data": 0x22}, {"data": 0x23}, {"data": 0x24}, {"data": 0x25},
                {"data": 0x26}, {"data": 0x27}, {"data": 0x28}, {"data": 0x29},
                {"data": 0xC0}, {"end": 1},
            ]):
                await stream_assert(ctx, dut.samples, expected, f"[{idx}]")

        with self.run_test(m) as sim:
            sim.add_testbench(testbench_ctrl)
            sim.add_testbench(testbench_i)
            sim.add_testbench(testbench_o)

    def prepare_test_applet(self, assembly: SimulationAssembly):
        async def testbench_pins(ctx):
            pin = assembly.get_pin("A0")

            for _ in range(514):
                await ctx.tick()

            # shift phase wrt sampling clock slightly
            ctx.set(pin.i, 1)
            for _ in range(5):
                await ctx.tick()
            ctx.set(pin.i, 0)

        assembly.add_testbench(testbench_pins, background=True)

    @applet_v2_simulation_test(prepare=prepare_test_applet, args=["X=A0:7"])
    async def test_applet_capture(self, applet: AnalyzerApplet, ctx):
        iface = applet.analyzer_iface

        self.assertEqual(await iface.identify(), b"GLA0")
        self.assertEqual(await iface.get_buffer_size(), 0x1000000)
        self.assertEqual(await iface.get_data_format(), DigitalFormat(width=8, stride=8))
        self.assertEqual(await iface.get_probe_names(), [f"X{i}" for i in range(8)])

        await iface.set_prolog_size(9)
        await iface.set_epilog_size(21)

        self.assertEqual(await iface.get_ref_frequency(), 1_000_000)
        await iface.set_sampling_rate(200_000)

        await iface.use_basic_trigger({0: DigitalTrigger.RisingEdge})
        await iface.arm_trigger()

        data = await iface.read_sample_block()
        self.assertEqual(list(data.samples), [0x00000000] * 8 + [0x01000000])
        self.assertEqual(data.marker, Marker.Trigger)
        self.assertEqual(data.offset, 24)

        data = await iface.read_sample_block()
        self.assertEqual(list(data.samples), [0x00000000] * 21)
        self.assertEqual(data.marker, Marker.Complete)

    @applet_v2_simulation_test(prepare=prepare_test_applet,
        args=["A0:7,B0:7,C0:7,D0:7", "--buffer-size=512"])
    async def test_applet_overflow(self, applet: AnalyzerApplet, ctx):
        iface = applet.analyzer_iface

        await iface.set_epilog_size(4096)
        await iface.force_trigger()
        data = await iface.read_sample_block()
        self.assertEqual(data.marker, Marker.Trigger)
        data = await iface.read_sample_block()
        self.assertEqual(data.marker, Marker.Overflow)

        await iface.interrupt()
        await iface.force_trigger()
        data = await iface.read_sample_block()
        self.assertEqual(data.marker, Marker.Trigger)
