import argparse

from unittest.mock import AsyncMock, Mock, patch

from amaranth.lib import io
from amaranth.sim import Simulator

from glasgow.applet import (GlasgowAppletV2TestCase, GlasgowAppletError, synthesis_test, async_test,
                            applet_v2_simulation_test, applet_v2_hardware_test)
from glasgow.gateware.ports import PortGroup

from . import MemoryPROMApplet, MemoryPROMBus, MemoryPROMComponent, MemoryPROMInterface, _Command


class MemoryPROMAppletTestCase(GlasgowAppletV2TestCase, applet=MemoryPROMApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    @synthesis_test
    def test_build_indirect(self):
        self.assertBuilds(args=["--a", "B0:1", "--a-clk", "B2", "--a-si", "B3",
                                "--a-lat", "B4", "--oe", "B5", "--we", "B6",
                                "--ce", "B7", "--a-bits", "16"])

    @applet_v2_simulation_test(args="--a B0:3 --oe B4 --we B5 --ce B6")
    async def test_read_pipe(self, applet, ctx):
        for bit in range(8):
            ctx.set(applet.assembly.get_pin(f"A{bit}").i, (0xa5 >> bit) & 1)
        self.assertEqual(list(await applet.prom_iface.read(3, 2)), [0xa5, 0xa5])

    @applet_v2_hardware_test(
        args="-V 3.3 --dq A0:7,B0 --a B1:2 --a-clk B3 --a-si B4 --a-bits 16",
        mocks=["prom_iface._pipe"])
    async def test_interface(self, applet: MemoryPROMApplet):
        iface = applet.prom_iface
        self.assertEqual(list(await iface.read(0x123, 2)), [0x1234, 0xabcd])
        with patch("glasgow.applet.memory.prom.random.shuffle", side_effect=lambda x: x.reverse()):
            self.assertEqual(list(await iface.read_shuffled(0x123, 2)), [0xabcd, 0x1234])
        await iface.write(0x123, [0x0100, 0x0203])
        await iface.poll()
        self.assertEqual(list(await iface.read(0, 0)), [])
        self.assertEqual(list(await iface.read_shuffled(0, 0)), [])

    @async_test
    async def test_health_sweep_voltage(self):
        assembly = Mock()
        assembly.device.set_voltage = AsyncMock()
        applet = MemoryPROMApplet(assembly)
        applet.prom_iface = Mock()
        applet.prom_iface.read = AsyncMock(return_value=MemoryPROMInterface.Data(b"\xff", 1))
        args = argparse.Namespace(operation="health", mode="sweep", a_bits=0, dq=range(8),
                                  samples=0, voltage_step=0.05)
        for ports in ("AB", "ABCD"):
            with self.subTest(ports=ports):
                assembly.device.all_ports = ports
                args.voltage = 5.0
                await applet.run(args)
                assembly.device.set_voltage.assert_awaited_with(ports, 5.0)
        args.voltage = None
        with self.assertRaises(GlasgowAppletError):
            await applet.run(args)

    def test_commands(self):
        ports = PortGroup(dq=io.SimulationPort("io", 8), a=io.SimulationPort("o", 4),
                          a_clk=None, a_si=None, a_lat=None,
                          ce=io.SimulationPort("o", 1), oe=io.SimulationPort("o", 1),
                          we=io.SimulationPort("o", 1))
        bus = MemoryPROMBus(ports, 4, 1e6, 1e6)
        dut = MemoryPROMComponent(bus, 1e6, 1e-6, 2e-6, 1e-6)
        writes = []

        async def monitor(ctx):
            last_we = 0
            while True:
                _, _, we, a, d = await ctx.tick().sample(bus.we, bus.a, bus.d)
                if last_we and not we:
                    writes.append((a, d))
                last_we = we

        async def testbench(ctx):
            async def send(data):
                for byte in data:
                    ctx.set(dut.i_stream.payload, byte)
                    ctx.set(dut.i_stream.valid, 1)
                    for _ in range(100):
                        _, _, ready = await ctx.tick().sample(dut.i_stream.ready)
                        if ready:
                            break
                    else:
                        self.fail("command input stalled")
                ctx.set(dut.i_stream.valid, 0)

            async def receive(value):
                for _ in range(100):
                    if ctx.get(dut.o_stream.valid):
                        break
                    await ctx.tick()
                else:
                    self.fail("response stalled")
                # Backpressure must retain both the response and its value.
                await ctx.tick().repeat(3)
                self.assertTrue(ctx.get(dut.o_stream.valid))
                self.assertEqual(ctx.get(dut.o_stream.payload), value)
                ctx.set(dut.o_stream.ready, 1)
                await ctx.tick()
                ctx.set(dut.o_stream.ready, 0)

            ctx.set(ports.dq.i, 0xa5)
            await send([_Command.SEEK, 3, _Command.READ])
            await receive(0xa5)
            self.assertEqual(ctx.get(bus.a), 3)
            self.assertEqual(ctx.get(ports.oe.o), 0)
            self.assertEqual(ctx.get(ports.dq.oe), 0)
            await send([_Command.QUEUE, _Command.WRITE, 0, 0,
                        _Command.INCR, _Command.WRITE, 0x5a])
            await ctx.tick().repeat(10)
            self.assertEqual(writes, [])
            await send([_Command.QUEUE, _Command.RUN])
            for _ in range(100):
                if len(writes) == 2:
                    break
                await ctx.tick()
            self.assertEqual(writes, [(3, 0), (4, 0x5a)])
            ctx.set(ports.dq.i, 0x5a)
            await send([_Command.POLL])
            await receive(0) # poll response payload is unused
            await ctx.tick().repeat(3)
            self.assertTrue(ctx.get(dut.o_flush))
            self.assertEqual(ctx.get(ports.ce.o), 0)

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(monitor, background=True)
        sim.add_testbench(testbench)
        sim.run()
