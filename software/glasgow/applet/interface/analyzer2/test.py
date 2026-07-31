from contextlib import contextmanager

from amaranth import *
from amaranth.lib import io, wiring
from amaranth.sim import Simulator

from glasgow.gateware.stream import stream_put, stream_get, stream_assert
from glasgow.gateware import octoram
from glasgow.applet import GlasgowAppletV2TestCase
from . import AnalyzerApplet, Sampler, Trigger, Packer, Writer, Reader, FlowControl, AnalyzerCore


class AnalyzerAppletTestCase(GlasgowAppletV2TestCase, applet=AnalyzerApplet):
    # @synthesis_test
    # def test_build(self):
    #     self.assertBuilds()

    @contextmanager
    def run_test(self, dut, name="test"):
        sim = Simulator(dut)
        sim.add_clock(1e-6)
        yield sim
        with sim.write_vcd(f"{name}.vcd"):
            sim.run()

    def test_sampler(self):
        pins = io.SimulationPort("i", 32)
        dut = Sampler(pins)

        async def testbench_pins(ctx):
            for value in range(0, 64):
                ctx.set(pins.i, value)
                await ctx.tick()

        for divisor in (0, 1, 4):
            async def testbench_samples(ctx):
                ctx.set(dut.divisor, divisor)
                await ctx.tick()
                for expected in range(divisor, 64, divisor + 1):
                    await stream_assert(ctx, dut.o_samples, {"data": expected})

            with self.run_test(dut) as sim:
                sim.add_testbench(testbench_pins, background=True)
                sim.add_testbench(testbench_samples)

    def test_trigger(self):
        dut = Trigger()

        async def testbench_samples(ctx):
            for value in range(0, 64):
                await stream_put(ctx, dut.i_samples, {"data": value})

        for name, trigger_modes, trigger_actives in (
            # data[1] -> level(1)
            ("level", [
                (1, Trigger.Mode.const({"active": 1, "value": 1, "level": 1})),
            ], [
                0, 0, 1, 1, 0, 0,
            ]),
            # data[1] -> posedge(1)
            ("posedge", [
                (1, Trigger.Mode.const({"active": 1, "value": 1, "level": 0})),
            ], [
                0, 0, 1, 0, 0, 0,
            ]),
        ):
            async def testbench_triggers(ctx):
                ctx.set(dut.active, 1)
                for index, mode in trigger_modes:
                    ctx.set(dut.mode[index], mode)
                for value, active in zip(range(0, 64), trigger_actives):
                    await stream_assert(ctx, dut.o_samples, {"data": value, "trig": active})

            with self.subTest(name=name):
                with self.run_test(dut) as sim:
                    sim.add_testbench(testbench_samples, background=True)
                    sim.add_testbench(testbench_triggers)

    def test_packer_samples_per_word(self):
        def check_width(width, per_word):
            packer = Packer(width=width)
            packer._MustUse__used = True
            assert packer.samples_per_word == per_word

        check_width(1,  32)
        check_width(2,  16)
        check_width(3,  8)
        check_width(4,  8)
        check_width(5,  4)
        check_width(8,  4)
        check_width(9,  2)
        check_width(16, 2)
        check_width(17, 1)
        check_width(32, 1)

    def test_packer_format(self):
        for width, offset, results in [
            (32, 2, [
                {"data": [0x00,0x00,0x00,0x00], "trig": {"active": 0}},
                {"data": [0x01,0x00,0x00,0x00], "trig": {"active": 0}},
                {"data": [0x02,0x00,0x00,0x00], "trig": {"active": 1, "offset": 0}},
            ]),
            (1, 5, [
                {"data": [0xAA,0xAA,0xAA,0xAA], "trig": {"active": 1, "offset": 5}},
            ]),
            (1, 32, [
                {"data": [0xAA,0xAA,0xAA,0xAA], "trig": {"active": 0}},
                {"data": [0xAA,0xAA,0xAA,0xAA], "trig": {"active": 1, "offset": 0}},
            ]),
            (4, 3, [
                {"data": [0x10,0x32,0x54,0x76], "trig": {"active": 1, "offset": 12}},
                {"data": [0x98,0xBA,0xDC,0xFE], "trig": {"active": 0}},
            ]),
        ]:
            dut = Packer(width=width)

            async def testbench_triggers(ctx):
                await ctx.tick()
                for value in range(0, 64):
                    await stream_put(ctx, dut.i_samples, {"data": value, "trig": value == offset})

            async def testbench_packed(ctx):
                for result in results:
                    await stream_assert(ctx, dut.o_packed, result)

            with self.subTest(width=width, offset=offset):
                with self.run_test(dut) as sim:
                    sim.add_testbench(testbench_triggers, background=True)
                    sim.add_testbench(testbench_packed)

    def test_writer(self):
        m = Module()
        m.submodules.writer = dut  = Writer(dram_range=range(0, 64))
        m.submodules.dram   = dram = octoram.SimulationController(64)
        wiring.connect(m, dut.dram, dram.bus)

        async def testbench_packed(ctx):
            for packed in [
                {"data": [0x10,0x32,0x54,0x76], "trig": {"active": 0}},
                {"data": [0x98,0xBA,0xDC,0xFE], "trig": {"active": 0}},
                {"data": [0x00,0x11,0x22,0x33], "trig": {"active": 0}},
                {"data": [0x44,0x55,0x66,0x77], "trig": {"active": 0}},

                {"data": [0x00,0x00,0x11,0x11], "trig": {"active": 0}},
                {"data": [0x22,0x22,0x33,0x33], "trig": {"active": 0}},
                {"data": [0x44,0x44,0x55,0x55], "trig": {"active": 0}},
                {"data": [0x66,0x66,0x77,0x77], "trig": {"active": 0}},

                {"data": [0xA0,0xA1,0xA2,0xA3], "trig": {"active": 0}},
                {"data": [0xB0,0xB1,0xB2,0xB3], "trig": {"active": 1, "offset": 16}},

                {"data": [0x00,0x00,0x11,0x11], "trig": {"active": 0}},
                {"data": [0x22,0x22,0x33,0x33], "trig": {"active": 0}},
                {"data": [0x44,0x44,0x55,0x55], "trig": {"active": 0}},
                {"data": [0x66,0x66,0x77,0x77], "trig": {"active": 0}},

                {"data": [0x00,0x00,0x11,0x11], "trig": {"active": 0}},
                {"data": [0xE0,0xE1,0xE2,0xE3], "trig": {"active": 0}},
            ]:
                await stream_put(ctx, dut.i_packed, packed)

        async def testbench_blocks(ctx):
            await ctx.tick().repeat(32)
            assert dram.memory[0:4] == b"\x00\x00\x00\x00", dram.memory.hex()
            await stream_assert(ctx, dut.o_blocks,
                {"addr": 0x0000, "size": 32, "trig": {"active": 0}})

            await ctx.tick().repeat(32)
            assert dram.memory[0:4] == b"\x10\x32\x54\x76", dram.memory.hex()
            await stream_assert(ctx, dut.o_blocks,
                {"addr": 0x0020, "size":  8, "trig": {"active": 1, "offset": 16}})

            await ctx.tick().repeat(32)
            assert dram.memory[32:36] == b"\xA0\xA1\xA2\xA3", dram.memory.hex()

            await stream_assert(ctx, dut.o_blocks,
                {"addr": 0x0028, "size": 24, "trig": {"active": 0}})
            await ctx.tick().repeat(32)
            assert dram.memory[60:64] == b"\xE0\xE1\xE2\xE3", dram.memory.hex()

        with self.run_test(m) as sim:
            sim.add_testbench(testbench_packed)
            sim.add_testbench(testbench_blocks)
            sim.add_testbench(dram.testbench, background=True)

    def test_reader(self):
        m = Module()
        m.submodules.reader = dut  = Reader(dram_range=range(0, 64))
        m.submodules.dram   = dram = octoram.SimulationController(64)
        wiring.connect(m, dut.dram, dram.bus)

        dram.memory[:] = bytes(range(64))

        async def testbench_ranges(ctx):
            await stream_put(ctx, dut.i_ranges, {"addr": 0,  "size": 32})
            await stream_put(ctx, dut.i_ranges, {"addr": 60, "size":  8})

        async def testbench_octets(ctx):
            for index, expected in enumerate([
                *range(0,  32),
                *range(60, 64),
                *range(0,   4),
            ]):
                assert (data := await stream_get(ctx, dut.o_octets)) == expected, \
                    f"[{index}]: {data:02x} != {expected:02x}"

        with self.run_test(m) as sim:
            sim.add_testbench(testbench_ranges, background=True)
            sim.add_testbench(testbench_octets)
            sim.add_testbench(dram.testbench, background=True)

    def test_flow_control(self):
        dut = FlowControl(
            writer_shape=1,
            writer_ratio=2,
            reader_shape=1,
            reader_ratio=1,
            max_credits=10,
        )

        async def testbench_main(ctx):
            ctx.set(dut.free_run, 1)
            ctx.set(dut.initial, 6)

            await stream_put(ctx, dut.i_writer, 0)
            assert ctx.get(dut.credits) == 2
            await stream_put(ctx, dut.i_writer, 0)
            assert ctx.get(dut.credits) == 4
            await stream_put(ctx, dut.i_writer, 0)
            assert ctx.get(dut.credits) == 6
            await stream_put(ctx, dut.i_writer, 0)
            assert ctx.get(dut.credits) == 6

            ctx.set(dut.free_run, 0)

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
            assert not ctx.get(dut.overflow)
            await stream_put(ctx, dut.i_writer, 0)
            assert ctx.get(dut.credits) == 10
            assert ctx.get(dut.overflow)

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

        m = Module()
        m.submodules.core = dut  = AnalyzerCore(pins=pins, dram_range=range(0x100))
        m.submodules.dram = dram = octoram.SimulationController(0x100)
        wiring.connect(m, dut.dram, dram.bus)

        async def testbench_ctrl(ctx):
            # pins==0x40
            ctx.set(dut.triggers[5], {"active": 1, "value": 1, "level": 0})

            ctx.set(dut.prolog_size, 8)
            ctx.set(dut.epilog_size, 8)

        async def testbench_i(ctx):
            for value in range(0x100):
                await ctx.tick()
                ctx.set(pins.i, value&0xff)

        async def testbench_o(ctx):
            for expected in range(0x1a, 0x21):
            # for expected in range(0x1a, 0x21+8+1):
                assert (actual := await stream_get(ctx, dut.samples)), \
                    f"{actual:02x} != {expected:02x}"

        with self.run_test(m) as sim:
            sim.add_testbench(testbench_ctrl)
            sim.add_testbench(testbench_i)
            sim.add_testbench(testbench_o)
            sim.add_testbench(dram.testbench, background=True)
