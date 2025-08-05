import unittest

from amaranth import *
from amaranth.sim import Simulator
from amaranth.lib import io

from glasgow.gateware.ports import PortGroup
from glasgow.gateware.stream import stream_put, stream_assert
from glasgow.gateware.mdio import *


class MDIOTarget:
    def __init__(self, ports):
        self.ports = ports

    async def _get(self, ctx):
        _, bit_o, bit_oe = await ctx.posedge(self.ports.mdc.o) \
            .sample(self.ports.mdio.o, self.ports.mdio.oe)
        assert bit_oe == 1, "get() on undriven bus"
        return bit_o

    async def _put(self, ctx, bit):
        await ctx.posedge(self.ports.mdc.o)
        await ctx.delay(150e-9)
        ctx.set(self.ports.mdio.i, bit)

    async def header(self, ctx, phy_addr, reg_addr, *, is_write):
        preamble = 0
        while await self._get(ctx) == 1: # 1111...10
            preamble += 1
        assert preamble >= 32, f"short preamble ({preamble} cycles)"
        assert await self._get(ctx) == 1, f"invalid start"

        rw0 = await self._get(ctx)
        rw1 = await self._get(ctx)
        match rw0, rw1, is_write:
            case (0, 1, True):  pass
            case (1, 0, False): pass
            case _: assert False, \
                f"invalid preamble ({rw0} {rw1}) for {'write' if is_write else 'read'}"

        actual_phy_addr = 0
        for _ in range(5):
            actual_phy_addr = (actual_phy_addr << 1) | await self._get(ctx)
        assert actual_phy_addr == phy_addr, \
            f"phy addr: actual {actual_phy_addr}, expected {phy_addr}"

        actual_reg_addr = 0
        for _ in range(5):
            actual_reg_addr = (actual_reg_addr << 1) | await self._get(ctx)
        assert actual_reg_addr == reg_addr, \
            f"reg addr: actual {actual_reg_addr}, expected {reg_addr}"

    async def read(self, ctx, phy_addr, reg_addr, data):
        await self.header(ctx, phy_addr, reg_addr, is_write=False)

        await self._put(ctx, 0) # turnaround

        for _ in range(16):
            await self._put(ctx, bool(data & 0x8000))
            data <<= 1

        await ctx.posedge(self.ports.mdc.o) # turnaround

    async def write(self, ctx, phy_addr, reg_addr, data):
        await self.header(ctx, phy_addr, reg_addr, is_write=True)

        assert await self._get(ctx) == 1
        assert await self._get(ctx) == 0

        actual_data = 0
        for _ in range(16):
            actual_data = (actual_data << 1) | await self._get(ctx)
        assert actual_data == data, \
            f"data: actual {actual_data:016b}, expected {data:016b}"


class Scenario:
    def __init__(self):
        self.ports = PortGroup()
        self.ports.mdc  = io.SimulationPort("o",  1, name="mdc")
        self.ports.mdio = io.SimulationPort("io", 1, name="mdio")

        self.dut = Controller(self.ports)
        self.tgt = MDIOTarget(self.ports)

    def run(self):
        for divisor in (0, 1, 2):
            async def d_testbench(ctx, divisor=divisor):
                ctx.set(self.dut.divisor, divisor)

            sim = Simulator(self.dut)
            sim.add_clock(1e-6)
            sim.add_testbench(d_testbench)
            sim.add_testbench(self.i_testbench)
            sim.add_testbench(self.o_testbench)
            sim.add_testbench(self.t_testbench)
            with sim.write_vcd("mdio_scenario.vcd"):
                sim.run()


class WriteScenario(Scenario):
    async def i_testbench(self, ctx):
        await stream_put(ctx, self.dut.i_stream, {
            "type": Request.Write,
            "phy":  0,
            "reg":  0,
            "data": 0xf005,
        })
        await stream_put(ctx, self.dut.i_stream, {
            "type": Request.Write,
            "phy":  0b11001,
            "reg":  0b01100,
            "data": 0x2137,
        })

    async def o_testbench(self, ctx):
        pass

    async def t_testbench(self, ctx):
        await self.tgt.write(ctx, phy_addr=0x00, reg_addr=0x00, data=0xf005)
        await self.tgt.write(ctx, phy_addr=0x19, reg_addr=0x0c, data=0x2137)


class ReadScenario(Scenario):
    async def i_testbench(self, ctx):
        await stream_put(ctx, self.dut.i_stream, {
            "type": Request.Read,
            "phy":  0,
            "reg":  0,
        })
        await stream_put(ctx, self.dut.i_stream, {
            "type": Request.Read,
            "phy":  0b11001,
            "reg":  0b01100,
        })

    async def o_testbench(self, ctx):
        await stream_assert(ctx, self.dut.o_stream, {
            "data": 0xf005,
        })
        await stream_assert(ctx, self.dut.o_stream, {
            "data": 0x2137,
        })

    async def t_testbench(self, ctx):
        await self.tgt.read(ctx, phy_addr=0x00, reg_addr=0x00, data=0xf005)
        await self.tgt.read(ctx, phy_addr=0x19, reg_addr=0x0c, data=0x2137)


class MDIOControllerTestCase(unittest.TestCase):
    def test_write(self):
        WriteScenario().run()

    def test_read(self):
        ReadScenario().run()
