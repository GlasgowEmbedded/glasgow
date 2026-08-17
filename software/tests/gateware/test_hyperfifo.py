import unittest

from amaranth import *
from amaranth.lib import wiring
from amaranth.sim import Simulator

from glasgow.gateware.stream import stream_get, stream_put
from glasgow.gateware import octoram
from glasgow.gateware.hyperfifo import HyperFIFO


class IntegrationTestCase(unittest.TestCase):
    def setUp(self):
        self.dut = HyperFIFO(spill_base=0, spill_size=0x1000)

    def run_test(self, testbench_w, testbench_r):
        m = Module()

        m.submodules.dut = dut = self.dut
        m.submodules.mem = mem = octoram.SimulationController(0x2000)
        wiring.connect(m, dut.dram, mem.bus)

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench_w)
        sim.add_testbench(testbench_r)
        sim.add_testbench(mem.testbench, background=True)
        with sim.write_vcd("test_hyperfifo.vcd"):
            sim.run()

    def test_backpressure_0(self):
        async def testbench_w(ctx):
            for value in range(8):
                await stream_put(ctx, self.dut.w_data, value)

        async def testbench_r(ctx):
            for value in range(8):
                assert (actual := await stream_get(ctx, self.dut.r_data)) == value, \
                    f"{actual:02x} != {value:02x}"

        self.run_test(testbench_w, testbench_r)

    def test_backpressure_1(self):
        async def testbench_w(ctx):
            for value in range(8):
                await stream_put(ctx, self.dut.w_data, value)

        async def testbench_r(ctx):
            for value in range(8):
                assert (actual := await stream_get(ctx, self.dut.r_data)) == value, \
                    f"{actual:02x} != {value:02x}"
                await ctx.tick()

        self.run_test(testbench_w, testbench_r)

    def test_backpressure_2(self):
        async def testbench_w(ctx):
            for value in range(8):
                await stream_put(ctx, self.dut.w_data, value)

        async def testbench_r(ctx):
            for value in range(8):
                assert (actual := await stream_get(ctx, self.dut.r_data)) == value, \
                    f"{actual:02x} != {value:02x}"
                await ctx.tick()
                await ctx.tick()

        self.run_test(testbench_w, testbench_r)

    def test_dram_spill(self):
        size = 0x800

        async def testbench_w(ctx):
            for count in range(size):
                await stream_put(ctx, self.dut.w_data, count&0xff)
                if count % 32 == 0:
                    await ctx.tick().repeat(10) # reduce duty cycle, can't keep up with 100%

        async def testbench_r(ctx):
            await ctx.tick().repeat(512) # simulate a latency spile
            for count in range(size):
                assert (actual := await stream_get(ctx, self.dut.r_data)) == count&0xff, \
                    f"{actual:02x} != {count&0xff:02x}"
                if count % 64 == 0:
                    await ctx.tick().repeat(10) # simulate more latency spikes

        self.run_test(testbench_w, testbench_r)
