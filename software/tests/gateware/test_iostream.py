import unittest
from amaranth import *
from amaranth.sim import Simulator
from amaranth.lib import io

from glasgow.gateware.ports import PortGroup
from glasgow.gateware.iostream import IOStreamer


class IOStreamTestCase(unittest.TestCase):
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
            assert ctx.get(dut.i_stream.valid) == 0

            ctx.set(dut.o_stream.p.port.data.oe, 1)
            ctx.set(dut.o_stream.p.meta, 2)
            await ctx.tick()
            assert ctx.get(port.o[0]) == 1
            assert ctx.get(port.oe) == 1
            assert ctx.get(dut.i_stream.valid) == 1
            assert ctx.get(dut.i_stream.p.port.data.i[0]) == 0
            assert ctx.get(dut.i_stream.p.meta) == 1

            ctx.set(dut.o_stream.p.port.data.o[0], 0)
            ctx.set(dut.o_stream.p.i_en, 0)
            await ctx.tick()
            assert ctx.get(port.o[0]) == 0
            assert ctx.get(port.oe) == 1
            assert ctx.get(dut.i_stream.valid) == 1
            assert ctx.get(dut.i_stream.p.port.data.i[0]) == 1
            assert ctx.get(dut.i_stream.p.meta) == 2

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

            ctx.set(dut.o_stream.valid, 1)
            ctx.set(dut.o_stream.p.i_en, 1)

            _, _, o_stream_ready, i_stream_valid = \
                await ctx.tick().sample(dut.o_stream.ready, dut.i_stream.valid)
            assert o_stream_ready == 0
            assert i_stream_valid == 0

            _, _, o_stream_ready, i_stream_valid = \
                await ctx.tick().sample(dut.o_stream.ready, dut.i_stream.valid)
            assert o_stream_ready == 0
            assert i_stream_valid == 0

            ctx.set(dut.o_stream.p.meta, 0b0101)
            ctx.set(dut.i_stream.ready, 1)
            assert ctx.get(dut.o_stream.ready) == 1
            _, _, o_stream_ready, i_stream_valid = \
                await ctx.tick().sample(dut.o_stream.ready, dut.i_stream.valid)
            assert o_stream_ready == 1
            assert i_stream_valid == 0

            ctx.set(dut.o_stream.p.meta, 0b1100)
            ctx.set(port.i, 0b0101)
            _, _, o_stream_ready, i_stream_valid = \
                await ctx.tick().sample(dut.o_stream.ready, dut.i_stream.valid)
            assert o_stream_ready == 1
            assert i_stream_valid == 0
            ctx.set(dut.i_stream.ready, 0)
            assert ctx.get(dut.o_stream.ready) == 0

            ctx.set(port.i, 0b1100)
            _, _, o_stream_ready, i_stream_valid, i_stream_p = \
                await ctx.tick().sample(dut.o_stream.ready, dut.i_stream.valid, dut.i_stream.p)
            assert o_stream_ready == 0
            assert i_stream_valid == 1
            assert i_stream_p.port.data.i == 0b0101, f"{i_stream_p.i:#06b}"
            assert i_stream_p.meta == 0b0101, f"{i_stream_p.meta:#06b}"

            _, _, o_stream_ready, i_stream_valid, i_stream_p = \
                await ctx.tick().sample(dut.o_stream.ready, dut.i_stream.valid, dut.i_stream.p)
            assert o_stream_ready == 0
            assert i_stream_valid == 1
            assert i_stream_p.port.data.i == 0b0101, f"{i_stream_p.i:#06b}"
            assert i_stream_p.meta == 0b0101, f"{i_stream_p.meta:#06b}"

            ctx.set(dut.i_stream.ready, 1)
            _, _, o_stream_ready, i_stream_valid, i_stream_p = \
                await ctx.tick().sample(dut.o_stream.ready, dut.i_stream.valid, dut.i_stream.p)
            assert o_stream_ready == 0
            assert i_stream_valid == 1
            assert i_stream_p.port.data.i == 0b0101, f"{i_stream_p.i:#06b}"
            assert i_stream_p.meta == 0b0101, f"{i_stream_p.meta:#06b}"

            ctx.set(dut.o_stream.p.meta, 0b1001)
            _, _, o_stream_ready, i_stream_valid, i_stream_p = \
                await ctx.tick().sample(dut.o_stream.ready, dut.i_stream.valid, dut.i_stream.p)
            assert o_stream_ready == 0
            assert i_stream_valid == 1
            assert i_stream_p.port.data.i == 0b1100, f"{i_stream_p.i:#06b}"
            assert i_stream_p.meta == 0b1100, f"{i_stream_p.meta:#06b}"

            _, _, o_stream_ready, i_stream_valid, i_stream_p = \
                await ctx.tick().sample(dut.o_stream.ready, dut.i_stream.valid, dut.i_stream.p)
            assert o_stream_ready == 1
            assert i_stream_valid == 0

            ctx.set(port.i, 0b1001)
            _, _, o_stream_ready, i_stream_valid, i_stream_p = \
                await ctx.tick().sample(dut.o_stream.ready, dut.i_stream.valid, dut.i_stream.p)
            assert o_stream_ready == 1
            assert i_stream_valid == 0

            _, _, o_stream_ready, i_stream_valid, i_stream_p = \
                await ctx.tick().sample(dut.o_stream.ready, dut.i_stream.valid, dut.i_stream.p)
            assert o_stream_ready == 1
            assert i_stream_valid == 1
            assert i_stream_p.port.data.i == 0b1001, f"{i_stream_p.i:#06b}"
            assert i_stream_p.meta == 0b1001, f"{i_stream_p.meta:#06b}"

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        with sim.write_vcd("test.vcd", fs_per_delta=1):
            sim.run()
