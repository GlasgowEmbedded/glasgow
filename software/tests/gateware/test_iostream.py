import unittest
from amaranth import *
from amaranth.sim import Simulator
from amaranth.lib import io

from glasgow.gateware.ports import PortGroup
from glasgow.gateware.iostream import IOStreamer

async def stream_get(ctx, stream):
    ctx.set(stream.ready, 1)
    payload, = await ctx.tick().sample(stream.payload).until(stream.valid)
    ctx.set(stream.ready, 0)
    return payload

async def stream_put(ctx, stream, payload):
    ctx.set(stream.payload, payload)
    ctx.set(stream.valid, 1)
    await ctx.tick().until(stream.ready)
    ctx.set(stream.valid, 0)

class IOStreamTestCase(unittest.TestCase):
    def test_sdr_input_sampled_correctly(self):
        """ This is a latency-agnostic test, that verifies that the IOStreamer samples the inputs at the same time as the output signals change """
        ports = PortGroup()
        ports.clk_out = io.SimulationPort("o", 1)
        ports.data_in = io.SimulationPort("i", 8)

        dut = IOStreamer({
            "clk_out": ("o", 1),
            "data_in": ("i", 8),
        }, ports, meta_layout=4)

        expected_sample = []
        actually_sampled = []

        async def input_generator_tb(ctx):
            """
            This generates input values on approximately every falling clock edge.
            Exactly which of these values will be sampled depends on the latency of the dut,
            which this testcase is agnostic about.
            """
            cnt = 0xff
            while True:
                ctx.set(ports.data_in.i, cnt)
                await ctx.tick()
                await ctx.delay(0.5e-6) # half a clock cycle
                cnt = (cnt - 1) & 0xff

        async def save_expected_sample_values_tb(ctx):
            """
            This testbench looks at the clk_out port and when it sees a positive edge it knows that
            IOStreamer is expected to sample the input signal, so the current state of the data_in port
            becomes one of the expected sampled values. This is saved into expected_sample[] to be compared
            later, when the sample actually arrives back on i_stream.
            """
            while True:
                await ctx.posedge(ports.clk_out.o[0])
                value = ctx.get(ports.data_in.i)
                expected_sample.append(value)

        async def i_stream_consumer_tb(ctx):
            """
            This testbench saves all the samples coming in over i_stream
            """
            while True:
                payload = await stream_get(ctx,dut.i_stream)
                actually_sampled.append(payload.port.data_in.i)

        async def main_testbench(ctx):
            """
            This testbench is the producer for o_stream, and it also serves as the main orchestrator
            for the entire testcase. After it produces the stimulus, it waits a number of clock cycles
            to make sure any input latency has passed, and then it verifies that the expected number
            of bytes has been received, and that the expected values have been sampled.
            """
            await ctx.tick()

            for i in range(0,8):
                await stream_put(ctx, dut.o_stream, {"meta": i, "i_en": i % 2, "port": { "clk_out": {"o": i % 2}}})

            await stream_put(ctx, dut.o_stream, {"meta": 0, "i_en": 0, "port": { "clk_out": {"o": 0}}})

            for i in range(20):
                await ctx.tick()
            assert len(actually_sampled) == 4 # This should be checked as well, because a possible failure mode is
            # if IOStreamer never generates clock edges. We don't want to end up comparing two empty lists against
            # eachother.
            assert actually_sampled == expected_sample

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(main_testbench)
        sim.add_testbench(i_stream_consumer_tb, background = True)
        sim.add_testbench(input_generator_tb, background=True)
        sim.add_testbench(save_expected_sample_values_tb, background=True)
        with sim.write_vcd("test.vcd", fs_per_delta=1):
            sim.run()

    def test_basic(self):
        ports = PortGroup()
        ports.data = port = io.SimulationPort("io", 1)

        dut = IOStreamer({
            "data": ("io", 1),
        }, ports, meta_layout=4)

        async def testbench(ctx):
            await ctx.tick()

            ctx.set(dut.o_stream.p.port.data.o[0], 1)
            ctx.set(dut.o_stream.p.port.data.oe, 0)
            ctx.set(dut.o_stream.p.i_en, 1)
            ctx.set(dut.o_stream.p.meta, 1)
            ctx.set(dut.o_stream.valid, 1)
            ctx.set(dut.i_stream.ready, 1)
            await ctx.tick()
            assert ctx.get(port.o[0]) == 1
            assert ctx.get(port.oe) == 0
            assert ctx.get(dut.i_stream.valid) == 1
            assert ctx.get(dut.i_stream.p.port.data.i[0]) == 0
            assert ctx.get(dut.i_stream.p.meta) == 1

            ctx.set(dut.o_stream.p.port.data.oe, 1)
            ctx.set(dut.o_stream.p.meta, 2)
            await ctx.tick()
            assert ctx.get(port.o[0]) == 1
            assert ctx.get(port.oe) == 1
            assert ctx.get(dut.i_stream.valid) == 1
            assert ctx.get(dut.i_stream.p.port.data.i[0]) == 0
            assert ctx.get(dut.i_stream.p.meta) == 2

            ctx.set(dut.o_stream.p.meta, 3)
            await ctx.tick()
            assert ctx.get(port.o[0]) == 1
            assert ctx.get(port.oe) == 1
            assert ctx.get(dut.i_stream.valid) == 1
            assert ctx.get(dut.i_stream.p.port.data.i[0]) == 1
            assert ctx.get(dut.i_stream.p.meta) == 3

            ctx.set(dut.o_stream.p.port.data.o[0], 0)
            ctx.set(dut.o_stream.p.i_en, 0)
            await ctx.tick()
            assert ctx.get(port.o[0]) == 0
            assert ctx.get(port.oe) == 1
            assert ctx.get(dut.i_stream.valid) == 0

            ctx.set(dut.o_stream.valid, 0)
            await ctx.tick()
            assert ctx.get(dut.i_stream.valid) == 0

            await ctx.tick()
            assert ctx.get(dut.i_stream.valid) == 0

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        with sim.write_vcd("test.vcd", fs_per_delta=1):
            sim.run()

    def test_skid(self):
        ports = PortGroup()
        ports.data = port = io.SimulationPort("io", 4)

        dut = IOStreamer({
            "data": ("io", 4),
        }, ports, meta_layout=4)

        async def testbench(ctx):
            await ctx.tick()

            ctx.set(dut.i_stream.ready, 1)
            ctx.set(dut.o_stream.valid, 1)
            ctx.set(dut.o_stream.p.i_en, 1)
            ctx.set(dut.o_stream.p.meta, 0b0101)
            ctx.set(port.i, 0b0101)

            await ctx.tick()

            assert ctx.get(dut.i_stream.p.port.data.i) == 0b0101, f"{ctx.get(dut.i_stream.p.port.data.i):#06b}"
            assert ctx.get(dut.i_stream.p.meta) == 0b0101, f"{ctx.get(dut.i_stream.p.meta):#06b}"

            ctx.set(dut.o_stream.p.meta, 0b1111)
            ctx.set(port.i, 0b1111)

            ctx.set(dut.i_stream.ready, 0)

            await ctx.tick().repeat(10)
            # The skid buffer should protect the input stream from changes on the input signal
            assert ctx.get(dut.i_stream.p.port.data.i) == 0b0101, f"{ctx.get(dut.i_stream.p.port.data.i):#06b}"
            assert ctx.get(dut.i_stream.p.meta) == 0b0101, f"{ctx.get(dut.i_stream.p.meta):#06b}"

            ctx.set(dut.i_stream.ready, 1)

            await ctx.tick()

            assert ctx.get(dut.i_stream.p.port.data.i) == 0b1111, f"{ctx.get(dut.i_stream.p.port.data.i):#06b}"
            assert ctx.get(dut.i_stream.p.meta) == 0b1111, f"{ctx.get(dut.i_stream.p.meta):#06b}"

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        with sim.write_vcd("test.vcd", fs_per_delta=1):
            sim.run()
