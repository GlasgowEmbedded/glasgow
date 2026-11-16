from ... import *
from . import MemoryONFIApplet


class MemoryONFIAppletTestCase(GlasgowAppletV2TestCase, applet=MemoryONFIApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    @synthesis_test
    def test_build_rev_c3(self):
        self.assertBuilds(revision="C3")

    def test_stream_commands(self):
        from amaranth.lib import io
        from amaranth.sim import Simulator
        from glasgow.gateware.ports import PortGroup
        from . import MemoryONFIComponent, CMD_SELECT, CMD_CONTROL, CMD_READ, CMD_WRITE, CMD_WAIT

        ports = PortGroup(io=io.SimulationPort("io", 8), ce=io.SimulationPort("o", 2),
            cle=io.SimulationPort("o", 1), ale=io.SimulationPort("o", 1),
            re=io.SimulationPort("o", 1), we=io.SimulationPort("o", 1),
            r_b=io.SimulationPort("i", 1))
        dut = MemoryONFIComponent(ports)

        async def bench(ctx):
            async def send(*data):
                for byte in data:
                    ctx.set(dut.i_stream.payload, byte)
                    ctx.set(dut.i_stream.valid, 1)
                    await ctx.tick().until(dut.i_stream.ready)
                ctx.set(dut.i_stream.valid, 0)

            ctx.set(ports.r_b.i, 1)
            await send(CMD_SELECT, 1, CMD_CONTROL, 7)
            await ctx.tick().until(dut.flush)
            self.assertEqual(ctx.get(ports.ce.o), 1)
            self.assertEqual(ctx.get(ports.cle.o), 1)
            self.assertEqual(ctx.get(ports.ale.o), 1)

            await send(CMD_WRITE, 1, 0, 0xa5)
            await ctx.tick().until(ports.io.oe)
            self.assertEqual(ctx.get(ports.io.o), 0xa5)
            await ctx.tick().until(dut.flush)

            ctx.set(ports.io.i, 0x69)
            await send(CMD_READ, 2, 0)
            for _ in range(2):
                await ctx.tick().until(dut.o_stream.valid)
                # Output must remain valid and stable while the host applies backpressure.
                await ctx.tick().repeat(8)
                self.assertEqual(ctx.get(dut.o_stream.valid), 1)
                self.assertEqual(ctx.get(dut.o_stream.payload), 0x69)
                self.assertEqual(ctx.get(ports.io.oe), 0)
                ctx.set(dut.o_stream.ready, 1)
                await ctx.tick()
                ctx.set(dut.o_stream.ready, 0)
            await ctx.tick().until(dut.flush)

            ctx.set(ports.r_b.i, 0)
            await ctx.tick().repeat(4)
            await send(CMD_WAIT)
            await ctx.tick().repeat(12)
            self.assertEqual(ctx.get(dut.flush), 0)
            ctx.set(ports.r_b.i, 1)
            await ctx.tick().until(dut.flush)
            await send(CMD_READ, 0, 0, CMD_WRITE, 0, 0)
            await ctx.tick().until(dut.flush)
            self.assertEqual(ctx.get(dut.o_stream.valid), 0)

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(bench)
        sim.run()

    @applet_v2_hardware_test(args=["-V", "3.3"], mocks=["onfi_iface._pipe"])
    async def test_read_flushes_commands(self, applet: MemoryONFIApplet):
        self.assertEqual(await applet.onfi_iface.read_onfi_signature(), b"ONFI")
