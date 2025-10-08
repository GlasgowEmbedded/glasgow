import unittest
import random
from amaranth import *
from amaranth.sim import Simulator
from amaranth.lib import io

from glasgow.gateware.ports import PortGroup
from glasgow.gateware.iostream import IOStreamer
from glasgow.gateware.stream import stream_put, stream_get_maybe
from collections import deque


def delay_signal_by_amount(simulator, source_signal, destination_signal, amount_seconds, init=None):
    """A generic utility function to delay a signal by an arbitrary amount of time in simulation.

    This acts more like a transmission line, so if the signal changes many times withing a period
    shorter than `amount seconds`, those changes are going to be observable on the output signal
    (Except for changes that take 0 time).
    """
    values_in_flight = deque()
    trigger_output_driver = Signal()

    async def source_signal_monitor_tb(ctx):
        async for _, value in ctx.changed(source_signal).sample(source_signal):
            increment = type(ctx._engine.now)(amount_seconds * 1e15)
            values_in_flight.append((ctx._engine.now + increment, value))
            ctx.set(trigger_output_driver, 1 ^ ctx.get(trigger_output_driver))

    async def destination_signal_driver_tb(ctx):
        if init is not None:
            ctx.set(destination_signal, init)
        while True:
            await ctx.changed(trigger_output_driver)
            while values_in_flight:
                attime, value = values_in_flight.popleft()
                if attime < ctx._engine.now:
                    assert False, "Error: trying to change signal in the past?"
                if attime > ctx._engine.now:
                    await ctx.delay((attime - ctx._engine.now) * 1e-15)
                ctx.set(destination_signal, value)

    simulator.add_testbench(destination_signal_driver_tb, background=True)
    simulator.add_testbench(source_signal_monitor_tb, background=True)


OFFSETS_TO_TEST = (0, 1, 2, 10)


class IOStreamerTestCase(unittest.TestCase):
    def _subtest_iostreamer(self, i_valid_bits, o_ready_bits, ratio=1, offset=0):
        """A roundtrip-latency-agnostic test, that verifies that the IOStreamer samples the inputs
        at the same time as the output signals change (+ specified offset is clock/half-clock
        cycles, depending on ratio). The output data is fed back as input data, delayed by the
        amount of time specified by offset (+10% of a clock period to prevent any simulation race
        conditions), and so the list of received samples is offset-invariant. The intent of the
        `_bits` arguments is to specify a usage pattern that can be randomized, in order to
        hopefully fully test all corner cases.

        i_valid_bits: is a string of "1"s and "0"s. Each character refers to one (or more) internal
            clock cycles. "1" means to send a payload, and "0" means to leave `i` stream idle for 1
            clock cycle. When sending a payload `i` stream is waited upon if it's not ready, so each
            "1" might take more than one internal clock cycle. A "0" always takes a single internal
            clock cycle.

        o_ready_bits: is a string of "1"s and "0"s, and it specifies on which internal clock cycle
            the `o` stream is ready or not. Each character refers to a single clock cycle, and if
            the stream does not have a payload available at the releavant clock cycle, then the
            coroutine that consumes `o` stream payloads moves on to the next character in this
            string.

        ratio, offset: Configuration of IOStreamer
        """
        assert ratio in (1, 2)

        ports = PortGroup()
        data_width = 8
        ports.data_out = io.SimulationPort("o", data_width)
        ports.data_in  = io.SimulationPort("i", data_width)

        CLOCK_PERIOD = 1e-6

        init_value = 0x55

        dut = IOStreamer(ports, ratio=ratio, meta_layout=data_width, offset=offset,
                         init={"data_out": {"o": init_value}})

        active_cycles = i_valid_bits.count("1")
        expected_samples_count = active_cycles * ratio
        data_to_send = [random.randrange(1 << data_width) for _ in range(expected_samples_count)]
        if i_valid_bits[0] == "1" and o_ready_bits[0] == "1":
            # This is the initial state of the FFs from FFBuffer:
            first_data_to_receive = 0
        else:
            # This is from the "init" parameter of IOStreamer:
            first_data_to_receive = init_value
        data_to_receive = [first_data_to_receive] + data_to_send[:-1]
        meta_to_send = [random.randrange(1 << data_width) for _ in range(active_cycles)]

        expected_sample = []
        actually_sampled = []

        async def o_stream_consumer_tb(ctx):
            meta_index = data_index = 0
            for o_ready_bit in o_ready_bits:
                if o_ready_bit == "1":
                    payload = await stream_get_maybe(ctx, dut.o)
                    if payload is not None:
                        assert payload.meta == meta_to_send[meta_index]
                        meta_index += 1
                        for j in range(ratio):
                            assert payload.port.data_in.i[j] == data_to_receive[data_index], \
                                "Wrong data received (index,actual,expecred) = " + \
                                f"{j},0x{payload.port.data_in.i[j]:02x},0x{data_to_receive[data_index]:02x}"
                            data_index += 1
                else:
                    await ctx.tick()
            assert data_index == expected_samples_count, \
                    f"Wrong number of sample received: " + \
                    f"{data_index} (expected: {expected_samples_count})"

        async def i_stream_producer_tb(ctx):
            meta_index = data_index = 0
            for i_valid_bit in i_valid_bits:
                if i_valid_bit == "1":
                    await stream_put(ctx, dut.i, {
                        "meta": meta_to_send[meta_index],
                        "port": {
                            "data_out": {
                                "o": data_to_send[data_index:data_index+ratio],
                            }
                        }
                    })
                    meta_index += 1
                    data_index += ratio
                else:
                    await ctx.tick()

        sim = Simulator(dut)
        sim.add_clock(CLOCK_PERIOD)
        sim.add_testbench(o_stream_consumer_tb)
        sim.add_testbench(i_stream_producer_tb)
        delay_signal_by_amount(sim, ports.data_out.o, ports.data_in.i,
                               (offset + 0.1) * CLOCK_PERIOD / ratio, init=0xaa)
        with sim.write_vcd("test.vcd", fs_per_delta=1):
            sim.run()

    def test_basic(self):
        random.seed(123) # Make the test consistent from run to run
        for ratio in (1, 2):
            for offset in OFFSETS_TO_TEST:
                with self.subTest(ratio=ratio, offset=offset):
                    self._subtest_iostreamer(
                        i_valid_bits = "111111111",
                        o_ready_bits = "111111111" + ("1"*20),
                        ratio = ratio,
                        offset = offset)

    def _get_random_bit_string(self, cnt_bits):
        rint = random.getrandbits(cnt_bits)
        return f"{{:0{cnt_bits}b}}".format(rint)

    def test_random(self):
        random.seed(123) # Make the test consistent from run to run
        repeats = 4
        cnt_bits = 100
        for ratio in (1, 2):
            for offset in OFFSETS_TO_TEST:
                for i in range(repeats):
                    with self.subTest(ratio=ratio, offset=offset, repeat=i):
                        self._subtest_iostreamer(
                            i_valid_bits = self._get_random_bit_string(cnt_bits),
                            o_ready_bits = self._get_random_bit_string(cnt_bits) + "1" * cnt_bits,
                            ratio = ratio,
                            offset = offset)
