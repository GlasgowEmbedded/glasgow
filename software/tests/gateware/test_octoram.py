import unittest
from contextlib import contextmanager

from amaranth import *
from amaranth.sim import Simulator, BrokenTrigger
from amaranth.lib import io

from glasgow.gateware.ports import PortGroup
from glasgow.gateware.stream import stream_get, stream_put
from glasgow.gateware.octoram import *


def simulate_psram(ports, *, data=bytearray(0x100000), part="APS51208N-OBR"):
    class CSDeasserted(Exception):
        pass

    async def watch_cs(cs_o, triggers):
        try:
            *values, posedge_cs_o = await triggers.posedge(cs_o)
        except BrokenTrigger: # Workaround for amaranth-lang/amaranth#1508
            # Both our original trigger and posedge of cs happened at the same time.
            # Prioritize CS being deasserted.
            raise CSDeasserted
        if posedge_cs_o == 1:
            raise CSDeasserted
        return values

    async def bus_nop(ctx):
        cs, clk, dq, dqs = ports.cs, ports.clk, ports.dq, ports.dqs
        await watch_cs(cs.o, ctx.posedge(clk.o))
        await watch_cs(cs.o, ctx.negedge(clk.o))

    async def bus_get(ctx, *, with_dqs=False):
        cs, clk, dq, dqs = ports.cs, ports.clk, ports.dq, ports.dqs
        _, dq0_oe, dq0_o, dqs0_oe, dqs0_o = \
            await watch_cs(cs.o, ctx.posedge(clk.o).sample(
                dq.oe, dq.o, dqs.oe, dqs.o))
        _, dq1_oe, dq1_o, dqs1_oe, dqs1_o = \
            await watch_cs(cs.o, ctx.negedge(clk.o).sample(
                dq.oe, dq.o, dqs.oe, dqs.o))
        assert (dq0_oe, dq1_oe) == (0xff, 0xff)
        if with_dqs:
            assert (dqs0_oe, dqs1_oe) == (1, 1)
            return dq0_o, dqs0_o, dq1_o, dqs1_o
        else:
            return dq0_o, dq1_o

    async def bus_put(ctx, data0, data1):
        cs, clk, dq, dqs = ports.cs, ports.clk, ports.dq, ports.dqs
        _, dq0_oe, dqs0_oe = \
            await watch_cs(cs.o, ctx.posedge(clk.o).sample(dq.oe, dqs.oe))
        ctx.set(dq.i, data0); ctx.set(dqs.i, 1)
        _, dq1_oe, dqs1_oe = \
            await watch_cs(cs.o, ctx.negedge(clk.o).sample(dq.oe, dqs.oe))
        ctx.set(dq.i, data1); ctx.set(dqs.i, 0)
        assert (dq0_oe, dqs0_oe, dq1_oe, dqs1_oe) == (0, 0, 0, 0)

    async def testbench_aps51208n_obr(ctx):
        latency  = 5
        col_mask = 0x7ff

        await ctx.negedge(ports.cs.o)
        while True:
            try:
                inst0, _     = await bus_get(ctx)
                addr3, addr2 = await bus_get(ctx)
                addr1, addr0 = await bus_get(ctx)
                addr = (addr3<<24)|(addr2<<16)|(addr1<<8)|(addr0<<0)

                if inst0 == 0xff: # Reset
                    continue

                elif inst0 == 0xA0: # Sync Write (2K Linear Burst)
                    for _ in range(latency - 1):
                        await bus_nop(ctx)

                    while True:
                        data0, mask0, data1, mask1 = await bus_get(ctx, with_dqs=True)
                        if not mask0: data[addr+0] = data0
                        if not mask1: data[addr+1] = data1
                        addr = (addr & ~col_mask) | ((addr + 2) & col_mask)

                elif inst0 == 0x20: # Sync Read (2K Linear Burst)
                    for _ in range((latency << 1) - 1):
                        await bus_nop(ctx)

                    while True:
                        data0 = data[addr+0]
                        data1 = data[addr+1]
                        addr = (addr & ~col_mask) | ((addr + 2) & col_mask)
                        await bus_put(ctx, data0, data1)

            except CSDeasserted:
                await ctx.negedge(ports.cs.o)
                continue

    match part:
        case "APS51208N-OBR": return testbench_aps51208n_obr
        case _: assert False


class IntegrationTestCase(unittest.TestCase):
    def setUp(self):
        ports = self.ports = PortGroup()
        ports.cs  = ~io.SimulationPort("o",  1)
        ports.clk =  io.SimulationPort("o",  1)
        ports.dq  =  io.SimulationPort("io", 8)
        ports.dqs =  io.SimulationPort("io", 1)

        self.traces = [
            ports.cs.o,
            ports.clk.o,
            ports.dq.oe,
            ports.dq.o,
            ports.dq.i,
            ports.dqs.oe,
            ports.dqs.o,
            ports.dqs.i,
        ]

    @contextmanager
    def run_test(self, dut, name="test"):
        testbench_psram = simulate_psram(self.ports)

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        yield sim
        sim.add_testbench(testbench_psram, background=True)
        with sim.write_vcd(f"{name}.vcd", f"{name}.gtkw", traces=self.traces):
            sim.run()

    def test_streamer(self):
        dut = Streamer(self.ports, half_rate=True)

        async def testbench_input(ctx):
            async def bus_idle():
                await stream_put(ctx, dut.i_stream,
                    {"oper": Operation.Idle})

            async def bus_put(oper, *, data=[0, 0], mask=[0, 0]):
                await stream_put(ctx, dut.i_stream,
                    {"oper": oper, "chip": 1, "data": data, "mask": mask})

            await ctx.tick()
            await bus_idle()

            await bus_put(Operation.Write, data=[0xA0, 0x00])
            await bus_put(Operation.Write, data=[0x00, 0x00])
            await bus_put(Operation.Write, data=[0x00, 0x04])
            for _ in range(4):
                await bus_put(Operation.Idle)
            await bus_put(Operation.Write, data=[0x11, 0x22])
            await bus_put(Operation.Write, data=[0x33, 0x44], mask=[1, 0])
            await bus_idle()

            await bus_put(Operation.Write, data=[0x20, 0x00])
            await bus_put(Operation.Write, data=[0x00, 0x00])
            await bus_put(Operation.Write, data=[0x00, 0x02])
            for _ in range(9):
                await bus_put(Operation.Idle)
            for _ in range(5):
                await bus_put(Operation.Read)
            await bus_idle()

        async def testbench_output(ctx):
            async def bus_get():
                payload = await stream_get(ctx, dut.o_stream)
                return payload.data[0], payload.data[1]

            assert (value := await bus_get()) == (0x00, 0x00), f"{value[0]:02x}, {value[1]:02x}"
            assert (value := await bus_get()) == (0x11, 0x22), f"{value[0]:02x}, {value[1]:02x}"
            assert (value := await bus_get()) == (0x00, 0x44), f"{value[0]:02x}, {value[1]:02x}"
            assert (value := await bus_get()) == (0x00, 0x00), f"{value[0]:02x}, {value[1]:02x}"

        with self.run_test(dut) as sim:
            sim.add_testbench(testbench_input)
            sim.add_testbench(testbench_output)

    @contextmanager
    def run_controller_test(self, dut):
        m = Module()
        m.submodules.dut = dut

        # Add dummy `sync` domain for testing SimulationController.
        m.d.sync += Signal().eq(0)

        async def testbench_command(ctx):
            ctx.set(dut.latency, 5)
            await ctx.tick()

            await stream_put(ctx, dut.bus.commands, {
                "type": Command.WriteMemRow,
                "addr": 0x4,
                "size": 2,
            })
            await stream_put(ctx, dut.bus.commands, {
                "type": Command.ReadMemRow,
                "addr": 0x2,
                "size": 4,
            })
            # test epoch mechanism
            await stream_put(ctx, dut.bus.commands, {
                "type": Command.ReadMemRow,
                "addr": 0x4,
                "size": 1,
            })

        async def testbench_input(ctx):
            await stream_put(ctx, dut.bus.w_data,
                [{"data": 0x11, "mask": 0}, {"data": 0x22, "mask": 0}])
            await stream_put(ctx, dut.bus.w_data,
                [{"data": 0x33, "mask": 1}, {"data": 0x44, "mask": 0}])

        async def testbench_output(ctx):
            assert (value := await stream_get(ctx, dut.bus.r_data)) == \
                [{"data": 0x00}, {"data": 0x00}], f"{value}"
            assert (value := await stream_get(ctx, dut.bus.r_data)) == \
                [{"data": 0x11}, {"data": 0x22}], f"{value}"
            assert (value := await stream_get(ctx, dut.bus.r_data)) == \
                [{"data": 0x00}, {"data": 0x44}], f"{value}"
            assert (value := await stream_get(ctx, dut.bus.r_data)) == \
                [{"data": 0x00}, {"data": 0x00}], f"{value}"
            assert (value := await stream_get(ctx, dut.bus.r_data)) == \
                [{"data": 0x11}, {"data": 0x22}], f"{value}"

        with self.run_test(m) as sim:
            sim.add_testbench(testbench_command)
            sim.add_testbench(testbench_input)
            sim.add_testbench(testbench_output)
            yield sim

    def test_controller(self):
        with self.run_controller_test(Controller(self.ports, half_rate=True)):
            pass

    def test_sim_controller(self):
        with self.run_controller_test(ctrl := SimulationController(0x100000)) as sim:
            sim.add_testbench(ctrl.testbench, background=True)
