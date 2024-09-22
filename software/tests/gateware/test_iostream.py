import unittest
import random
from amaranth import *
from amaranth.sim import Simulator
from amaranth.lib import io

from glasgow.gateware.ports import PortGroup
from glasgow.gateware.iostream import IOStreamerTop

MAX_SKIDBUFFER_SIZE = 4

async def stream_get(ctx, stream):
    """
    This helper coroutine takes one payload from the stream.
    If a payload is not available it waits as many clocks cycles as
    needed stream.valid goes high.
    """
    ctx.set(stream.ready, 1)
    payload, = await ctx.tick().sample(stream.payload).until(stream.valid)
    ctx.set(stream.ready, 0)
    return payload

async def stream_get_maybe(ctx, stream):
    """
    This helper coroutine takes one payload from the stream,
    if it is available at the next clock cycle. If a payload is not
    available, then time is advanced by only a single clock cycle,
    and this coroutine returns None.
    """
    ctx.set(stream.ready, 1)
    _, _, payload, stream_valid = await ctx.tick().sample(stream.payload, stream.valid)
    ctx.set(stream.ready, 0)
    if stream_valid:
        return payload
    else:
        return None

async def stream_put(ctx, stream, payload):
    """
    This helper coroutine presents a payload to the specified stream,
    and waits as many clock cycles as it takes for the payload to be accepted.
    """
    ctx.set(stream.payload, payload)
    ctx.set(stream.valid, 1)
    await ctx.tick().until(stream.ready)
    ctx.set(stream.valid, 0)

class IOStreamTimeoutError(Exception):
    """
    Custom exception class to make it easy to catch just this exception, for tests
    that are expected to fail with a timeout.
    """
    pass

class IOStreamTestCase(unittest.TestCase):
    def _subtest_sdr_input_sampled_correctly(self, o_valid_bits, i_en_bits, i_ready_bits, timeout_clocks=None, iready_comb_path=False):
        """
        This is a latency-agnostic test, that verifies that the IOStreamerTop samples the inputs at the same time as the output signals change.

        o_valid_bits: is a string of "1"s and "0"s. Each character refers to one (or more) clock cycles. "1" means to send a payload,
            and "0" means to leave o_stream idle for 1 clock cycle. When sending a payload o_stream is waited upon if it's not ready, so
            each "1" might take more than one clock cycle. A "0" always takes a single clock cycle. During the test all the
            payloads with "1" are guaranteed to be sent, unless the testcase raises an IOStreamTimeoutError.

        i_en_bits: is a string of "1"s and "0"s, and it specifies for each payload, whether to send it with i_en high. The index of the
            character in the i_en_bits string matches the index of the character in the o_valid_bits. That is o_valid_bits, and i_en_bits
            never go out of sync. Setting i_en_bits high for the positions on which o_valid_bits is low has no effect. The value of i_en_bits
            only matters when we're actually sending a payload. Note that having i_en_bits high for a payload also has an effect on the "clock_out"
            pin, to allow the testcase to determine what data is expected to be sampled when it comes back o i_stream. In the case of an SDR test,
            clk_out toggles every time inputs are sampled.

        i_ready_bits: is a string of "1"s and "0"s, and it specifies on which clock cycle the i_stream is ready or not. Each character refers
            to a single clock cycle, and if the stream does not have a payload available at the releavant clock cycle, then the coroutine that
            consumes i_stream payloads moves on to the next character in this string. Make sure to have sufficient "1"s in this string so that all
            sample requests (o_stream payloads with i_en high) that have been launched are collected, otherwise the testcase may fail, in one of two ways:
              - back-pressure on i_stream may result in back-pressure on o_stream, never allowing the full o_valid_bits string to be completely played back,
                and resulting in a timeout.
              - the playback of the o_valid_bits string may complete, however it's possible a number of sample requests that are in flight remain stuck
                in the IOStreamerTop, pending for them to be extracted from the i_stream, and that could result in the testcase declaring that the final
                samples have been lost.
            To make sure a testcase completes, you will see some testcases have a large number of "1"s in this string past the length of o_valid_bits.

        timeout_clocks: The number of clock cycles we expect the testcase to complete. If None (default), then an appropriate amount of clock cycles is
            calculated.

        iready_comb_path: If true, specifies that istream.ready should be controlled combinatorially, and should only go high in response to istream.valid.
            Stream rules allow logic that is connected to the istream to behave this way.
        """
        ports = PortGroup()
        ports.clk_out = io.SimulationPort("o", 1)
        ports.data_in = io.SimulationPort("i", 8)

        if timeout_clocks is None:
            timeout_clocks = len(o_valid_bits) + len(i_ready_bits) + 20

        dut = IOStreamerTop({
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
            This testbench looks at the clk_out port and when it sees a positive or negative edge it knows that
            IOStreamerTop is expected to sample the input signal, so the current state of the data_in port
            becomes one of the expected sampled values. This is saved into expected_sample[] to be compared
            later, when the sample actually arrives back on i_stream.
            """
            while True:
                _, value = await ctx.changed(ports.clk_out.o).sample(ports.data_in.i)
                expected_sample.append(value)

        async def i_stream_consumer_tb(ctx):
            """
            This testbench saves all the samples coming in over i_stream
            """
            nonlocal i_stream_consumer_finished
            for i_ready_bit in i_ready_bits:
                if i_ready_bit == "1" and (not iready_comb_path or ctx.get(dut.i_stream.valid)):
                    payload = await stream_get_maybe(ctx,dut.i_stream)
                    if payload is not None:
                        actually_sampled.append(payload[0].actual.port.data_in.i)
                        assert payload[0].actual.i_valid
                else:
                    await ctx.tick()
            i_stream_consumer_finished = True


        async def check_timeout_tb(ctx):
            """
            This testbench ends the testcase if the given number of timeout clock cycles has elapsed.
            """
            await ctx.tick().repeat(timeout_clocks)
            raise IOStreamTimeoutError("Testcase timeout")

        async def main_testbench(ctx):
            """
            This testbench is the producer for o_stream, and it also serves as the main orchestrator
            for the entire testcase. After it produces the stimulus, it waits for the i_stream_consumer_tb
            to finish (which may take longer to potentially consume in-flight sampled payloads due to the
            latency of the dut). and then it verifies that the expected number of bytes has been received,
            and that the expected values have been sampled.
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
                    await stream_put(ctx, dut.o_stream, [{
                        "meta": i,
                        "actual": {
                            "i_en": i_en_bit,
                            "port": {
                                "clk_out": {
                                    "o": o_bit,
                                }
                            }
                        }
                    }])
                else:
                    await ctx.tick()

            while not i_stream_consumer_finished:
                await ctx.tick()

            assert len(actually_sampled) == expected_samples_count # This should be checked as well, because a
            # possible failure mode is if IOStreamerTop never generates clock edges. We don't want to end up
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

    def _subtest_ddr_input_sampled_correctly(self, o_valid_bits, i_en_bits, i_ready_bits, timeout_clocks=None, iready_comb_path=False):
        """
        This is a latency-agnostic test, that verifies that the IOStreamerTop samples the inputs at the same time as the output signals change.

        o_valid_bits: is a string of "1"s and "0"s. Each character refers to one (or more) internal clock cycles. "1" means to send a payload,
            and "0" means to leave o_stream idle for 1 clock cycle. When sending a payload o_stream is waited upon if it's not ready, so
            each "1" might take more than one internal clock cycle. A "0" always takes a single internal clock cycle. During the test all the
            payloads with "1" are guaranteed to be sent, unless the testcase raises an IOStreamTimeoutError.

        i_en_bits: is a string of "1"s and "0"s, and it specifies for each payload, whether to send it with i_en high. The index of the
            character in the i_en_bits string matches the index of the character in the o_valid_bits. That is o_valid_bits, and i_en_bits
            never go out of sync. Setting i_en_bits high for the positions on which o_valid_bits is low has no effect. The value of i_en_bits
            only matters when we're actually sending a payload. Note that having i_en_bits high for a payload also has an effect on the "clock_out"
            pin, to allow the testcase to determine what data is expected to be sampled when it comes back o i_stream. In the case of a DDR test,
            clk_out toggles twice every time inputs are sampled, and the edges on which it toggles specify exactly at what time the inputs
            are sampled.

        i_ready_bits: is a string of "1"s and "0"s, and it specifies on which internal clock cycle the i_stream is ready or not. Each character refers
            to a single clock cycle, and if the stream does not have a payload available at the releavant clock cycle, then the coroutine that
            consumes i_stream payloads moves on to the next character in this string. Make sure to have sufficient "1"s in this string so that all
            sample requests (o_stream payloads with i_en high) that have been launched are collected, otherwise the testcase may fail, in one of two ways:
              - back-pressure on i_stream may result in back-pressure on o_stream, never allowing the full o_valid_bits string to be completely played back,
                and resulting in a timeout.
              - the playback of the o_valid_bits string may complete, however it's possible a number of sample requests that are in flight remain stuck
                in the IOStreamerTop, pending for them to be extracted from the i_stream, and that could result in the testcase declaring that the final
                samples have been lost.
            To make sure a testcase completes, you will see some testcases have a large number of "1"s in this string past the length of o_valid_bits.

        timeout_clocks: The number of clock cycles we expect the testcase to complete. If None (default), then an appropriate amount of clock cycles is
            calculated.

        iready_comb_path: If true, specifies that istream.ready should be controlled combinatorially, and should only go high in response to istream.valid.
            Stream rules allow logic that is connected to the istream to behave this way.
        """

        ports = PortGroup()
        ports.clk_out = io.SimulationPort("o", 1)
        ports.data_in = io.SimulationPort("i", 8)

        if timeout_clocks is None:
            timeout_clocks = len(o_valid_bits) + len(i_ready_bits) + 20

        CLK_PERIOD = 1e-6

        dut = IOStreamerTop({
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
            IOStreamerTop is expected to sample the input signal, so the current state of the data_in port
            becomes one of the expected sampled values. This is saved into expected_sample[] to be compared
            later, when the sample actually arrives back on i_stream.
            """
            while True:
                _, value_phase_0 = await ctx.posedge(ports.clk_out.o).sample(ports.data_in.i)
                _, value_phase_1 = await ctx.negedge(ports.clk_out.o).sample(ports.data_in.i)
                expected_sample.append((value_phase_0, value_phase_1))

        async def i_stream_consumer_tb(ctx):
            """
            This testbench saves all the samples coming in over i_stream
            """
            nonlocal i_stream_consumer_finished
            for i_ready_bit in i_ready_bits:
                if i_ready_bit == "1" and (not iready_comb_path or ctx.get(dut.i_stream.valid)):
                    payload = await stream_get_maybe(ctx,dut.i_stream)
                    if payload is not None:
                        data = payload[0].actual.port.data_in.i, payload[1].actual.port.data_in.i
                        assert payload[0].actual.i_valid
                        assert payload[1].actual.i_valid
                        actually_sampled.append(data)
                else:
                    await ctx.tick()
            i_stream_consumer_finished = True

        async def check_timeout_tb(ctx):
            """
            This testbench ends the testcase if the given number of timeout clock cycles has elapsed.
            """
            await ctx.tick().repeat(timeout_clocks)
            raise IOStreamTimeoutError("Testcase timeout")

        async def main_testbench(ctx):
            """
            This testbench is the producer for o_stream, and it also serves as the main orchestrator
            for the entire testcase. After it produces the stimulus, it waits for the i_stream_consumer_tb
            to finish (which may take longer to potentially consume in-flight sampled payloads due to the
            latency of the dut). and then it verifies that the expected number of bytes has been received,
            and that the expected values have been sampled.
            """
            await ctx.tick()

            expected_samples_count = 0

            for i in range(len(o_valid_bits)):
                o_valid_bit = 1 if o_valid_bits[i] == "1" else 0
                i_en_bit = 1 if i_en_bits[i] == "1" else 0
                if o_valid_bit:
                    if i_en_bit:
                        expected_samples_count += 1
                    await stream_put(ctx, dut.o_stream, [
                    {
                        "meta": i,
                        "actual": {
                            "i_en": i_en_bit,
                            "port": {
                                "clk_out": {
                                    "o": i_en_bit,
                                }
                            }
                        }
                    },
                    {
                        "meta": i,
                        "actual": {
                            "i_en": i_en_bit,
                            "port": {
                                "clk_out": {
                                    "o": 0,
                                }
                            }
                        }
                    },
                    ])
                else:
                    await ctx.tick()

            while not i_stream_consumer_finished:
                await ctx.tick()

            assert len(actually_sampled) == expected_samples_count # This should be checked as well, because a
            # possible failure mode is if IOStreamerTop never generates clock edges. We don't want to end up
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

    def _subtest_sdr_and_ddr_input_sampled_correctly(self, o_valid_bits, i_en_bits, i_ready_bits, timeout_clocks=None, iready_comb_path=False):
        self._subtest_sdr_input_sampled_correctly(o_valid_bits, i_en_bits, i_ready_bits, timeout_clocks, iready_comb_path)
        self._subtest_ddr_input_sampled_correctly(o_valid_bits, i_en_bits, i_ready_bits, timeout_clocks, iready_comb_path)

    def test_i_ready_low_doesnt_block_when_not_sampling_inputs(self):
        """
        This testcase ensures that if i_stream is blocked, we can still perform
        non-sampling updates, as long as we never try to sample.
        """
        self._subtest_sdr_and_ddr_input_sampled_correctly(
            o_valid_bits = "010101010",
            i_en_bits    = "000000000",
            i_ready_bits = "")

    def test_i_ready_low_doesnt_block_when_iready_combinatorial(self):
        """
        This testcase ensures that an i_stream consumer, which is following
        stream rules, and is allowed to generate ready like this:
        ```m.d.comb += ready.eq(valid)```, will not cause the system to lock up
        """
        self._subtest_sdr_and_ddr_input_sampled_correctly(
            o_valid_bits = "0111100000" + (("0" * MAX_SKIDBUFFER_SIZE) + "0") * 4,
            i_en_bits    = "0111100000" + (("0" * MAX_SKIDBUFFER_SIZE) + "0") * 4,
            i_ready_bits = "0000000000" + (("0" * MAX_SKIDBUFFER_SIZE) + "1") * 4, iready_comb_path = True)

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

        dut = IOStreamerTop({
            "data": ("io", 1),
        }, ports, meta_layout=4)

        async def testbench(ctx):
            await ctx.tick()

            ctx.set(dut.o_stream.p[0].actual.port.data.o, 1)
            ctx.set(dut.o_stream.p[0].actual.port.data.oe, 0)
            ctx.set(dut.o_stream.p[0].actual.i_en, 1)
            ctx.set(dut.o_stream.p[0].meta, 1)
            ctx.set(dut.o_stream.valid, 1)
            ctx.set(dut.i_stream.ready, 1)
            await ctx.tick()
            assert ctx.get(port.o[0]) == 1
            assert ctx.get(port.oe) == 0
            assert ctx.get(dut.i_stream.valid) == 1
            assert ctx.get(dut.i_stream.p[0].actual.port.data.i[0]) == 0
            assert ctx.get(dut.i_stream.p[0].meta) == 1

            ctx.set(dut.o_stream.p[0].actual.port.data.oe, 1)
            ctx.set(dut.o_stream.p[0].meta, 2)
            await ctx.tick()
            assert ctx.get(port.o[0]) == 1
            assert ctx.get(port.oe) == 1
            assert ctx.get(dut.i_stream.valid) == 1
            assert ctx.get(dut.i_stream.p[0].actual.port.data.i[0]) == 0
            assert ctx.get(dut.i_stream.p[0].meta) == 2

            ctx.set(dut.o_stream.p[0].meta, 3)
            await ctx.tick()
            assert ctx.get(port.o[0]) == 1
            assert ctx.get(port.oe) == 1
            assert ctx.get(dut.i_stream.valid) == 1
            assert ctx.get(dut.i_stream.p[0].actual.port.data.i[0]) == 1
            assert ctx.get(dut.i_stream.p[0].meta) == 3

            ctx.set(dut.o_stream.p[0].actual.port.data.o[0], 0)
            ctx.set(dut.o_stream.p[0].actual.i_en, 0)
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

        dut = IOStreamerTop({
            "data": ("io", 4),
        }, ports, meta_layout=4)

        async def testbench(ctx):
            await ctx.tick()

            ctx.set(dut.i_stream.ready, 1)
            ctx.set(dut.o_stream.valid, 1)
            ctx.set(dut.o_stream.p[0].actual.i_en, 1)
            ctx.set(dut.o_stream.p[0].meta, 0b0101)
            ctx.set(port.i, 0b0101)

            await ctx.tick()

            assert ctx.get(dut.i_stream.p[0].actual.port.data.i) == 0b0101, f"{ctx.get(dut.i_stream.p[0].actual.port.data.i):#06b}"
            assert ctx.get(dut.i_stream.p[0].meta) == 0b0101, f"{ctx.get(dut.i_stream.p[0].meta):#06b}"

            ctx.set(dut.o_stream.p[0].meta, 0b1111)
            ctx.set(port.i, 0b1111)

            ctx.set(dut.i_stream.ready, 0)

            await ctx.tick().repeat(10)
            # The skid buffer should protect the input stream from changes on the input signal
            assert ctx.get(dut.i_stream.p[0].actual.port.data.i) == 0b0101, f"{ctx.get(dut.i_stream.p[0].actual.port.data.i):#06b}"
            assert ctx.get(dut.i_stream.p[0].meta) == 0b0101, f"{ctx.get(dut.i_stream.p[0].meta):#06b}"

            ctx.set(dut.i_stream.ready, 1)

            await ctx.tick()

            assert ctx.get(dut.i_stream.p[0].actual.port.data.i) == 0b1111, f"{ctx.get(dut.i_stream.p[0].actual.port.data.i):#06b}"
            assert ctx.get(dut.i_stream.p[0].meta) == 0b1111, f"{ctx.get(dut.i_stream.p[0].meta):#06b}"

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        with sim.write_vcd("test.vcd", fs_per_delta=1):
            sim.run()
