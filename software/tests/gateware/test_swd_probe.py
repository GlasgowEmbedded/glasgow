import unittest

from amaranth import *
from amaranth.sim import Simulator
from amaranth.lib import io, wiring

from glasgow.gateware.ports import PortGroup
from glasgow.gateware.stream import stream_get, stream_put, stream_assert
from glasgow.gateware.swd_probe import *


class SWDTarget:
    def __init__(self, ports):
        self.ports = ports

    async def nop(self, ctx):
        await ctx.posedge(self.ports.swclk.o)

    async def get(self, ctx):
        _, bit_o, bit_oe = await ctx.posedge(self.ports.swclk.o) \
            .sample(self.ports.swdio.o, self.ports.swdio.oe)
        # assert bit_oe == 1, "get() on undriven bus"
        return bit_o

    async def put(self, ctx, bit):
        await ctx.negedge(self.ports.swclk.o)
        ctx.set(self.ports.swdio.i, bit)
        await ctx.posedge(self.ports.swclk.o)

    async def assert_reset(self, ctx):
        count = 0
        while await self.get(ctx) == 1:
            count += 1
        assert await self.get(ctx) == 0
        assert count >= 50, f"runt line reset ({count} cycles)"

    async def assert_packet(self, ctx, *, ap_ndp: int, r_nw: int, addr: int):
        assert await self.get(ctx) == 1, "start"
        assert await self.get(ctx) == ap_ndp
        assert await self.get(ctx) == r_nw
        assert await self.get(ctx) == (addr >> 2) & 1
        assert await self.get(ctx) == (addr >> 3) & 1
        parity = ap_ndp ^ r_nw ^ (addr >> 2) & 1 ^ (addr >> 3) & 1
        assert await self.get(ctx) == parity
        assert await self.get(ctx) == 0, "stop"
        assert await self.get(ctx) == 1, "park"
        await self.nop(ctx)

    async def ack(self, ctx, ack: Ack, *, error=False):
        await self.put(ctx, ((ack.value >> 0) & 1) ^ error)
        await self.put(ctx, ((ack.value >> 1) & 1) ^ error)
        await self.put(ctx, ((ack.value >> 2) & 1) ^ error)

    async def assert_wdata(self, ctx, data: int):
        value = 0
        await self.nop(ctx)
        for offset in range(32):
            value |= await self.get(ctx) << offset
        parity = await self.get(ctx)
        assert value == data
        assert parity == format(data, "b").count("1") & 1

    async def rdata(self, ctx, data: int, *, error=False):
        for offset in range(32):
            await self.put(ctx, (data >> offset) & 1)
        await self.put(ctx, (format(data, "b").count("1") & 1) ^ error)
        await self.nop(ctx)


class Scenario:
    dut_cls = None

    def __init__(self):
        self.ports = PortGroup()
        self.ports.swclk = io.SimulationPort("o",  1, name="swclk")
        self.ports.swdio = io.SimulationPort("io", 1, name="swdio")

        self.dut = self.dut_cls(self.ports)
        self.tgt = SWDTarget(self.ports)

    def run(self):
        sim = Simulator(self.dut)
        sim.add_clock(1e-6)
        sim.add_testbench(self.i_testbench)
        sim.add_testbench(self.o_testbench)
        sim.add_testbench(self.t_testbench)
        with sim.write_vcd("swd_scenario.vcd"):
            sim.run()


class ReadDPIDRScenario(Scenario):
    dut_cls = Driver

    async def i_testbench(self, ctx):
        await stream_put(ctx, self.dut.i_words, {
            "type": Request.Header,
            "hdr":  {"ap_ndp": 0, "r_nw": 1, "addr": 0x0}
        })
        await stream_put(ctx, self.dut.i_words, {
            "type": Request.DataRd
        })

    async def o_testbench(self, ctx):
        await stream_assert(ctx, self.dut.o_words, {
            "type": Result.Ack,
            "ack":  Ack.OK,
        })
        await stream_assert(ctx, self.dut.o_words, {
            "type": Result.Data,
            "data": 0x12345679,
        })

    async def t_testbench(self, ctx):
        await self.tgt.assert_packet(ctx, ap_ndp=0, r_nw=1, addr=0)
        await self.tgt.ack(ctx, Ack.OK)
        await self.tgt.rdata(ctx, 0x12345679)


class WriteDPBANKSELScenario(Scenario):
    dut_cls = Driver

    async def i_testbench(self, ctx):
        await stream_put(ctx, self.dut.i_words, {
            "type": Request.Header,
            "hdr":  {"ap_ndp": 0, "r_nw": 0, "addr": 0x8}
        })
        await stream_put(ctx, self.dut.i_words, {
            "type": Request.DataWr,
            "data": 0xf0,
        })

    async def o_testbench(self, ctx):
        await stream_assert(ctx, self.dut.o_words, {
            "type": Result.Ack,
            "ack":  Ack.OK,
        })

    async def t_testbench(self, ctx):
        await self.tgt.assert_packet(ctx, ap_ndp=0, r_nw=0, addr=0x8)
        await self.tgt.ack(ctx, Ack.OK)
        await self.tgt.assert_wdata(ctx, 0xf0)


class WaitScenario(Scenario):
    dut_cls = Driver

    async def i_testbench(self, ctx):
        await stream_put(ctx, self.dut.i_words, {
            "type": Request.Header,
            "hdr":  {"ap_ndp": 1, "r_nw": 0, "addr": 0xC}
        })
        await stream_put(ctx, self.dut.i_words, {
            "type": Request.NoData,
        })

        await stream_put(ctx, self.dut.i_words, {
            "type": Request.Header,
            "hdr":  {"ap_ndp": 1, "r_nw": 0, "addr": 0xC}
        })
        await stream_put(ctx, self.dut.i_words, {
            "type": Request.DataWr,
            "data": 0x11223344,
        })

    async def o_testbench(self, ctx):
        await stream_assert(ctx, self.dut.o_words, {
            "type": Result.Ack,
            "ack":  Ack.WAIT,
        })
        await stream_assert(ctx, self.dut.o_words, {
            "type": Result.Ack,
            "ack":  Ack.OK,
        })

    async def t_testbench(self, ctx):
        await self.tgt.assert_packet(ctx, ap_ndp=1, r_nw=0, addr=0xC)
        await self.tgt.ack(ctx, Ack.WAIT)
        await self.tgt.nop(ctx)

        await self.tgt.assert_packet(ctx, ap_ndp=1, r_nw=0, addr=0xC)
        await self.tgt.ack(ctx, Ack.OK)
        await self.tgt.assert_wdata(ctx, 0x11223344)


class FaultScenario(Scenario):
    dut_cls = Driver

    async def i_testbench(self, ctx):
        await stream_put(ctx, self.dut.i_words, {
            "type": Request.Header,
            "hdr":  {"ap_ndp": 1, "r_nw": 1, "addr": 0xC}
        })
        await stream_put(ctx, self.dut.i_words, {
            "type": Request.NoData,
        })

        await stream_put(ctx, self.dut.i_words, {
            "type": Request.Sequence,
            "len":  32,
            "data": 0xffffffff,
        })
        await stream_put(ctx, self.dut.i_words, {
            "type": Request.Sequence,
            "len":  20,
            "data": 0x3ffff,
        })

        await stream_put(ctx, self.dut.i_words, {
            "type": Request.Header,
            "hdr":  {"ap_ndp": 0, "r_nw": 1, "addr": 0x0}
        })
        await stream_put(ctx, self.dut.i_words, {
            "type": Request.DataRd
        })

        await stream_put(ctx, self.dut.i_words, {
            "type": Request.Header,
            "hdr":  {"ap_ndp": 1, "r_nw": 1, "addr": 0xC}
        })
        await stream_put(ctx, self.dut.i_words, {
            "type": Request.DataRd
        })

    async def o_testbench(self, ctx):
        await stream_assert(ctx, self.dut.o_words, {
            "type": Result.Ack,
            "ack":  Ack.FAULT,
        })

        await stream_assert(ctx, self.dut.o_words, {
            "type": Result.Ack,
            "ack":  Ack.OK,
        })
        await stream_assert(ctx, self.dut.o_words, {
            "type": Result.Data,
            "data": 0x12345678,
        })

        await stream_assert(ctx, self.dut.o_words, {
            "type": Result.Ack,
            "ack":  Ack.OK,
        })
        await stream_assert(ctx, self.dut.o_words, {
            "type": Result.Data,
            "data": 0x10204080,
        })

    async def t_testbench(self, ctx):
        await self.tgt.assert_packet(ctx, ap_ndp=1, r_nw=1, addr=0xC)
        await self.tgt.ack(ctx, Ack.FAULT)
        await self.tgt.nop(ctx)
        await self.tgt.assert_reset(ctx)

        await self.tgt.assert_packet(ctx, ap_ndp=0, r_nw=1, addr=0x0)
        await self.tgt.ack(ctx, Ack.OK)
        await self.tgt.rdata(ctx, 0x12345678)

        await self.tgt.assert_packet(ctx, ap_ndp=1, r_nw=1, addr=0xC)
        await self.tgt.ack(ctx, Ack.OK)
        await self.tgt.rdata(ctx, 0x10204080)


class ControllerScenario(Scenario):
    dut_cls = Controller

    async def i_testbench(self, ctx):
        await stream_put(ctx, self.dut.i_stream, {
            "cmd":  Command.Sequence,
            "len":  32,
            "data": 0xffffffff,
        })
        await stream_put(ctx, self.dut.i_stream, {
            "cmd":  Command.Sequence,
            "len":  20,
            "data": 0x3ffff,
        })
        await stream_put(ctx, self.dut.i_stream, {
            "hdr":  {"ap_ndp": 0, "r_nw": 1, "addr": 0x0}
        })
        await stream_put(ctx, self.dut.i_stream, {
            "hdr":  {"ap_ndp": 1, "r_nw": 1, "addr": 0xC}
        })
        await stream_put(ctx, self.dut.i_stream, {
            "hdr":  {"ap_ndp": 1, "r_nw": 1, "addr": 0xC}
        })
        await stream_put(ctx, self.dut.i_stream, {
            "hdr":  {"ap_ndp": 1, "r_nw": 1, "addr": 0xC}
        })
        await stream_put(ctx, self.dut.i_stream, {
            "hdr":  {"ap_ndp": 1, "r_nw": 1, "addr": 0x4}
        })
        await stream_put(ctx, self.dut.i_stream, {
            "hdr":  {"ap_ndp": 1, "r_nw": 1, "addr": 0x4}
        })
        await stream_put(ctx, self.dut.i_stream, {
            "hdr":  {"ap_ndp": 1, "r_nw": 1, "addr": 0x4}
        })
        await stream_put(ctx, self.dut.i_stream, {
            "hdr":  {"ap_ndp": 1, "r_nw": 0, "addr": 0xC},
            "data": 0x01010102,
        })

    async def o_testbench(self, ctx):
        await stream_assert(ctx, self.dut.o_stream, {
            "rsp":  Response.Data,
            "ack":  Ack.OK,
            "data": 0x12345678
        })
        await stream_assert(ctx, self.dut.o_stream, {
            "rsp":  Response.Data,
            "ack":  Ack.OK,
            "data": 0x10204080
        })
        await stream_assert(ctx, self.dut.o_stream, {
            "rsp":  Response.Data,
            "ack":  Ack.OK,
            "data": 0x11223344
        })
        await stream_assert(ctx, self.dut.o_stream, {
            "rsp":  Response.Data,
            "ack":  Ack.OK,
            "data": 0x11223345
        })
        await stream_assert(ctx, self.dut.o_stream, {
            "rsp":  Response.NoData,
            "ack":  Ack.FAULT
        })
        await stream_assert(ctx, self.dut.o_stream, {
            "rsp":  Response.Error,
        })
        await stream_assert(ctx, self.dut.o_stream, {
            "rsp":  Response.Error,
        })
        await stream_assert(ctx, self.dut.o_stream, {
            "rsp":  Response.NoData,
            "ack":  Ack.OK
        })

    async def t_testbench(self, ctx):
        await self.tgt.assert_reset(ctx)

        await self.tgt.assert_packet(ctx, ap_ndp=0, r_nw=1, addr=0x0)
        await self.tgt.ack(ctx, Ack.OK)
        await self.tgt.rdata(ctx, 0x12345678)

        await self.tgt.assert_packet(ctx, ap_ndp=1, r_nw=1, addr=0xC)
        await self.tgt.ack(ctx, Ack.OK)
        await self.tgt.rdata(ctx, 0x10204080)

        await self.tgt.assert_packet(ctx, ap_ndp=1, r_nw=1, addr=0xC)
        await self.tgt.ack(ctx, Ack.OK)
        await self.tgt.rdata(ctx, 0x11223344)

        await self.tgt.assert_packet(ctx, ap_ndp=1, r_nw=1, addr=0xC)
        await self.tgt.ack(ctx, Ack.WAIT)
        await self.tgt.nop(ctx)

        await self.tgt.assert_packet(ctx, ap_ndp=1, r_nw=1, addr=0xC)
        await self.tgt.ack(ctx, Ack.WAIT)
        await self.tgt.nop(ctx)

        await self.tgt.assert_packet(ctx, ap_ndp=1, r_nw=1, addr=0xC)
        await self.tgt.ack(ctx, Ack.OK)
        await self.tgt.rdata(ctx, 0x11223345)

        await self.tgt.assert_packet(ctx, ap_ndp=1, r_nw=1, addr=0x4)
        await self.tgt.ack(ctx, Ack.FAULT)
        await self.tgt.nop(ctx)

        await self.tgt.assert_packet(ctx, ap_ndp=1, r_nw=1, addr=0x4)
        await self.tgt.ack(ctx, Ack.OK)
        await self.tgt.rdata(ctx, 0x11223345, error=True)

        await self.tgt.assert_packet(ctx, ap_ndp=1, r_nw=1, addr=0x4)
        await self.tgt.ack(ctx, Ack.OK, error=True)

        await self.tgt.assert_packet(ctx, ap_ndp=1, r_nw=0, addr=0xC)
        await self.tgt.ack(ctx, Ack.OK)
        await self.tgt.assert_wdata(ctx, 0x01010102)


class JTAGToSWDScenario(Scenario):
    dut_cls = Controller

    async def i_testbench(self, ctx):
        await stream_put(ctx, self.dut.i_stream, {
            "cmd":  Command.Sequence,
            "len":  16,
            "data": 0xE79E,
        })

    async def o_testbench(self, ctx):
        pass

    async def t_testbench(self, ctx):
        # 0111 1001 1110 0111
        assert await self.tgt.get(ctx) == 0
        assert await self.tgt.get(ctx) == 1
        assert await self.tgt.get(ctx) == 1
        assert await self.tgt.get(ctx) == 1
        assert await self.tgt.get(ctx) == 1
        assert await self.tgt.get(ctx) == 0
        assert await self.tgt.get(ctx) == 0
        assert await self.tgt.get(ctx) == 1
        assert await self.tgt.get(ctx) == 1
        assert await self.tgt.get(ctx) == 1
        assert await self.tgt.get(ctx) == 1
        assert await self.tgt.get(ctx) == 0
        assert await self.tgt.get(ctx) == 0
        assert await self.tgt.get(ctx) == 1
        assert await self.tgt.get(ctx) == 1
        assert await self.tgt.get(ctx) == 1


class SWDTestCase(unittest.TestCase):
    def test_read_dpidr(self):
        ReadDPIDRScenario().run()

    def test_write_dpbanksel(self):
        WriteDPBANKSELScenario().run()

    def test_wait(self):
        WaitScenario().run()

    def test_fault(self):
        FaultScenario().run()

    def test_controller(self):
        ControllerScenario().run()

    def test_jtag_to_swd(self):
        JTAGToSWDScenario().run()
