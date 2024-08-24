import unittest
import random
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

async def stream_get_maybe(ctx, stream):
    ctx.set(stream.ready, 1)
    _, _, payload, stream_valid = await ctx.tick().sample(stream.payload, stream.valid)
    ctx.set(stream.ready, 0)
    if stream_valid:
        return payload
    else:
        return None

async def stream_put(ctx, stream, payload):
    ctx.set(stream.payload, payload)
    ctx.set(stream.valid, 1)
    await ctx.tick().until(stream.ready)
    ctx.set(stream.valid, 0)

class IOStreamTimeoutError(Exception):
    pass

class IOStreamTestCase(unittest.TestCase):
    def _subtest_sdr_input_sampled_correctly(self, o_valid_bits, i_en_bits, i_ready_bits, timeout_clocks=None):
        """ This is a latency-agnostic test, that verifies that the IOStreamer samples the inputs at the same time as the output signals change """
        ports = PortGroup()
        ports.clk_out = io.SimulationPort("o", 1)
        ports.data_in = io.SimulationPort("i", 8)

        if timeout_clocks is None:
            timeout_clocks = len(o_valid_bits) + len(i_ready_bits) + 20

        dut = IOStreamer({
            "clk_out": ("o", 1),
            "data_in": ("i", 8),
        }, ports, meta_layout=4)

        expected_sample = []
        actually_sampled = []
        i_stream_consumer_finished = False

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
                await ctx.changed(ports.clk_out.o)
                value = ctx.get(ports.data_in.i)
                expected_sample.append(value)

        async def i_stream_consumer_tb(ctx):
            """
            This testbench saves all the samples coming in over i_stream
            """
            nonlocal i_stream_consumer_finished
            for i_ready_bit in i_ready_bits:
                if i_ready_bit == "1":
                    payload = await stream_get_maybe(ctx,dut.i_stream)
                    if payload is not None:
                        actually_sampled.append(payload.port.data_in.i)
                else:
                    await ctx.tick()
            i_stream_consumer_finished = True


        async def check_timeout_tb(ctx):
            await ctx.tick().repeat(timeout_clocks)
            raise IOStreamTimeoutError("Testcase timeout")

        async def main_testbench(ctx):
            """
            This testbench is the producer for o_stream, and it also serves as the main orchestrator
            for the entire testcase. After it produces the stimulus, it waits a number of clock cycles
            to make sure any input latency has passed, and then it verifies that the expected number
            of bytes has been received, and that the expected values have been sampled.
            """
            await ctx.tick()

            expected_samples_count = 0
            o_bit = 0

            for i in range(len(o_valid_bits)):
                o_valid_bit = 1 if o_valid_bits[i] == "1" else 0
                i_en_bit = 1 if i_en_bits[i] == "1" else 0
                if o_valid_bit:
                    if i_en_bit:
                        expected_samples_count += 1
                        o_bit ^= 1
                    await stream_put(ctx, dut.o_stream, {
                        "meta": i,
                        "i_en": i_en_bit,
                        "port": {
                            "clk_out": {
                                "o": o_bit,
                            }
                        }
                    })
                else:
                    await ctx.tick()

            while not i_stream_consumer_finished:
                await ctx.tick()

            assert len(actually_sampled) == expected_samples_count # This should be checked as well, because a
            # possible failure mode is if IOStreamer never generates clock edges. We don't want to end up
            # comparing two empty lists against eachother.
            assert actually_sampled == expected_sample, (f"Expected [" +
                    ", ".join(f"0x{s:02x}" for s in expected_sample) +
                    "] Got [" +
                    ", ".join(f"0x{s:02x}" for s in actually_sampled) + "]")

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(main_testbench)
        sim.add_testbench(i_stream_consumer_tb, background=True)
        sim.add_testbench(input_generator_tb, background=True)
        sim.add_testbench(save_expected_sample_values_tb, background=True)
        sim.add_testbench(check_timeout_tb, background=True)
        with sim.write_vcd("test.vcd", fs_per_delta=1):
            sim.run()

    def test_sdr_input_sampled_correctly(self):
        self._subtest_sdr_input_sampled_correctly(
            o_valid_bits = "111111111",
            i_en_bits    = "010101010",
            i_ready_bits = "111111111" + ("1"*20))

    def _subtest_ddr_input_sampled_correctly(self, o_valid_bits, i_en_bits, i_ready_bits, timeout_clocks=None):
        """ This is a latency-agnostic test, that verifies that the IOStreamer samples the inputs at the same time as the output signals change """
        ports = PortGroup()
        ports.clk_out = io.SimulationPort("o", 1)
        ports.data_in = io.SimulationPort("i", 8)

        if timeout_clocks is None:
            timeout_clocks = len(o_valid_bits) + len(i_ready_bits) + 20

        CLK_PERIOD = 1e-6

        dut = IOStreamer({
            "clk_out": ("o", 1),
            "data_in": ("i", 8),
        }, ports, ratio=2, meta_layout=4)

        expected_sample = []
        actually_sampled = []
        i_stream_consumer_finished = False

        async def input_generator_tb(ctx):
            """
            This generates input values at the the half-time between every falling/rising clock edge.
            This is to make it very obvious what value should be sampled by each DDR edge.
            Exactly which of these values will be sampled depends on the latency of the dut,
            which this testcase is agnostic about.
            """
            cnt = 0xff
            while True:
                ctx.set(ports.data_in.i, cnt)
                await ctx.tick()
                await ctx.delay(CLK_PERIOD/4)
                cnt = (cnt - 1) & 0xff
                ctx.set(ports.data_in.i, cnt)
                await ctx.delay(CLK_PERIOD/2) # half a clock cycle
                cnt = (cnt - 1) & 0xff

        async def save_expected_sample_values_tb(ctx):
            """
            This testbench looks at the clk_out port and when it sees a positive edge it knows that
            IOStreamer is expected to sample the input signal, so the current state of the data_in port
            becomes one of the expected sampled values. This is saved into expected_sample[] to be compared
            later, when the sample actually arrives back on i_stream.
            The way we look for the rising edge is a bit hairy, because the current implementation of
            DDRBufferCanBeSimulated can generate glitches, so we wait DELAY_TO_AVOID_GLITCHES after
            the clock edge, to make sure any glitches are resolved.
            Because this is a DDR test, we also wait half a clock to save the other edge as well.
            """
            while True:
                DELAY_TO_AVOID_GLITCHES = CLK_PERIOD/10

                await ctx.posedge(ports.clk_out.o[0])
                await ctx.delay(DELAY_TO_AVOID_GLITCHES)
                while ctx.get(ports.clk_out.o[0]) == 0:
                    await ctx.posedge(ports.clk_out.o[0])
                    await ctx.delay(DELAY_TO_AVOID_GLITCHES)

                value_phase_0 = ctx.get(ports.data_in.i)

                await ctx.delay(CLK_PERIOD / 2)

                value_phase_1 = ctx.get(ports.data_in.i)

                expected_sample.append((value_phase_0, value_phase_1))

        async def i_stream_consumer_tb(ctx):
            """
            This testbench saves all the samples coming in over i_stream
            """
            nonlocal i_stream_consumer_finished
            for i_ready_bit in i_ready_bits:
                if i_ready_bit == "1":
                    payload = await stream_get_maybe(ctx,dut.i_stream)
                    if payload is not None:
                        data = payload.port.data_in.i[0], payload.port.data_in.i[1]
                        actually_sampled.append(data)
                else:
                    await ctx.tick()
            i_stream_consumer_finished = True

        async def check_timeout_tb(ctx):
            await ctx.tick().repeat(timeout_clocks)
            raise IOStreamTimeoutError("Testcase timeout")

        async def main_testbench(ctx):
            """
            This testbench is the producer for o_stream, and it also serves as the main orchestrator
            for the entire testcase. After it produces the stimulus, it waits a number of clock cycles
            to make sure any input latency has passed, and then it verifies that the expected number
            of bytes has been received, and that the expected values have been sampled.
            """
            await ctx.tick()

            expected_samples_count = 0

            for i in range(len(o_valid_bits)):
                o_valid_bit = 1 if o_valid_bits[i] == "1" else 0
                i_en_bit = 1 if i_en_bits[i] == "1" else 0
                if o_valid_bit:
                    if i_en_bit:
                        expected_samples_count += 1
                    await stream_put(ctx, dut.o_stream, {
                        "meta": i,
                        "i_en": i_en_bit,
                        "port": {
                            "clk_out": {
                                "o": (i_en_bit, 0),
                            }
                        }
                    })
                else:
                    await ctx.tick()

            while not i_stream_consumer_finished:
                await ctx.tick()

            assert len(actually_sampled) == expected_samples_count # This should be checked as well, because a
            # possible failure mode is if IOStreamer never generates clock edges. We don't want to end up
            # comparing two empty lists against eachother.

            assert actually_sampled == expected_sample, (f"Expected [" +
                    ", ".join(f"(0x{s0:02x}, 0x{s1:02x})" for s0, s1 in expected_sample) +
                    "] Got [" +
                    ", ".join(f"(0x{s0:02x}, 0x{s1:02x})" for s0, s1 in actually_sampled) + "]")

        sim = Simulator(dut)
        sim.add_clock(CLK_PERIOD)
        sim.add_testbench(main_testbench)
        sim.add_testbench(i_stream_consumer_tb, background=True)
        sim.add_testbench(input_generator_tb, background=True)
        sim.add_testbench(save_expected_sample_values_tb, background=True)
        sim.add_testbench(check_timeout_tb, background=True)
        with sim.write_vcd("test.vcd", fs_per_delta=1):
            sim.run()

    def test_ddr_input_sampled_correctly(self):
        self._subtest_ddr_input_sampled_correctly(
            o_valid_bits = "111111111",
            i_en_bits    = "010101010",
            i_ready_bits = "111111111" + ("1"*20))

    def _subtest_sdr_and_ddr_input_sampled_correctly(self, o_valid_bits, i_en_bits, i_ready_bits, timeout_clocks=None):
        self._subtest_sdr_input_sampled_correctly(o_valid_bits, i_en_bits, i_ready_bits, timeout_clocks)
        self._subtest_ddr_input_sampled_correctly(o_valid_bits, i_en_bits, i_ready_bits, timeout_clocks)

    def _get_random_bit_string(self, cnt_bits):
        rint = random.getrandbits(cnt_bits)
        return f"{{:0{cnt_bits}b}}".format(rint)

    def test_random(self):
        random.seed(123) # Make the test consistent from run to run
        repeats = 10
        cnt_bits = 100
        for i in range(repeats):
            self._subtest_sdr_and_ddr_input_sampled_correctly(
                o_valid_bits = self._get_random_bit_string(cnt_bits),
                i_en_bits    = self._get_random_bit_string(cnt_bits),
                i_ready_bits = self._get_random_bit_string(cnt_bits) + "1" * cnt_bits)

    def test_i_ready_low_blocks_when_sampling_inputs(self):
        try:
            self._subtest_sdr_input_sampled_correctly(
                o_valid_bits = "011111111",
                i_en_bits    = "011111111",
                i_ready_bits = "")
        except IOStreamTimeoutError:
            pass
        else:
            assert False, "Testcase should have timed out"

        try:
            self._subtest_ddr_input_sampled_correctly(
                o_valid_bits = "011111111",
                i_en_bits    = "011111111",
                i_ready_bits = "")
        except IOStreamTimeoutError:
            pass
        else:
            assert False, "Testcase should have timed out"


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
