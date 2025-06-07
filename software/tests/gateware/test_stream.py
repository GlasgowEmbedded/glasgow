import unittest

from amaranth import *
from amaranth.sim import Simulator

from glasgow.gateware.stream import PacketQueue, stream_put, stream_assert


class PacketQueueTestCase(unittest.TestCase):
    def run_scenario(self, dut, i_testbench, o_testbench):
        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(i_testbench)
        sim.add_testbench(o_testbench)
        with sim.write_vcd("packet_queue.vcd"):
            sim.run()

    def run_io_check(self, packets, **kwargs):
        dut = PacketQueue(8, **kwargs)

        async def i_testbench(ctx):
            for packet in packets:
                await stream_put(ctx, dut.i, packet)

        async def o_testbench(ctx):
            for packet in packets:
                await stream_assert(ctx, dut.o, packet)

        self.run_scenario(dut, i_testbench, o_testbench)

    def test_size_1(self):
        self.run_io_check(data_depth=8, size_depth=2, packets=[
            {"data": 0x01, "first": 1, "last": 1},
        ])

    def test_size_2(self):
        self.run_io_check(data_depth=8, size_depth=2, packets=[
            {"data": 0x01, "first": 1, "last": 0},
            {"data": 0x02, "first": 0, "last": 1},
        ])

    def test_size_3(self):
        self.run_io_check(data_depth=8, size_depth=2, packets=[
            {"data": 0x01, "first": 1, "last": 0},
            {"data": 0x02, "first": 0, "last": 0},
            {"data": 0x03, "first": 0, "last": 1},
        ])

    def test_2_packets(self):
        self.run_io_check(data_depth=8, size_depth=2, packets=[
            {"data": 0x01, "first": 1, "last": 1},
            {"data": 0x02, "first": 1, "last": 1},
        ])

    def test_2_big_packets(self):
        self.run_io_check(data_depth=8, size_depth=2, packets=[
            {"data": 0x01, "first": 1, "last": 0},
            {"data": 0x02, "first": 0, "last": 0},
            {"data": 0x03, "first": 0, "last": 1},
            {"data": 0x04, "first": 1, "last": 0},
            {"data": 0x05, "first": 0, "last": 0},
            {"data": 0x06, "first": 0, "last": 1},
        ])

    def test_non_power_of_2(self):
        self.run_io_check(data_depth=5, size_depth=2, packets=[
            {"data": 0x01, "first": 1, "last": 0},
            {"data": 0x02, "first": 0, "last": 0},
            {"data": 0x03, "first": 0, "last": 1},
            {"data": 0x04, "first": 1, "last": 0},
            {"data": 0x05, "first": 0, "last": 0},
            {"data": 0x06, "first": 0, "last": 1},
        ])

    def test_packet_reset(self):
        dut = PacketQueue(8, data_depth=8, size_depth=2)

        async def i_testbench(ctx):
            await stream_put(ctx, dut.i, {"data": 0x01, "first": 1, "last": 0})
            await stream_put(ctx, dut.i, {"data": 0x02, "first": 0, "last": 0})
            await stream_put(ctx, dut.i, {"data": 0x03, "first": 1, "last": 1})

        async def o_testbench(ctx):
            await stream_assert(ctx, dut.o, {"data": 0x03, "first": 1, "last": 1})

        self.run_scenario(dut, i_testbench, o_testbench)

    def test_full(self):
        data_depth = 8
        dut = PacketQueue(8, data_depth=data_depth, size_depth=2)

        async def i_testbench(ctx):
            for n in range(data_depth - 1):
                await stream_put(ctx, dut.i, {
                    "data": (1 + n), "first": (n == 0), "last": (n == data_depth - 2)
                })
            assert ctx.get(dut.i.ready) == 0
            await stream_put(ctx, dut.i, {"data": 0xff, "first": 1, "last": 1})
            assert ctx.get(dut.i.ready) == 0
            await stream_put(ctx, dut.i, {"data": 0xfe, "first": 1, "last": 1})

        async def o_testbench(ctx):
            await ctx.tick().repeat(data_depth * 2)
            for n in range(data_depth - 1):
                await stream_assert(ctx, dut.o, {
                    "data": (1 + n), "first": (n == 0), "last": (n == data_depth - 2)
                })
            await stream_assert(ctx, dut.o, {"data": 0xff, "first": 1, "last": 1})
            await stream_assert(ctx, dut.o, {"data": 0xfe, "first": 1, "last": 1})

        self.run_scenario(dut, i_testbench, o_testbench)
