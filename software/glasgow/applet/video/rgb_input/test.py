from unittest.mock import AsyncMock, Mock

from amaranth.lib import io
from amaranth.sim import Simulator

from glasgow.applet import GlasgowAppletError, GlasgowAppletV2TestCase, synthesis_test, async_test
from glasgow.gateware.ports import PortGroup

from . import (VideoRGBInputApplet, VideoRGBInputComponent, VideoRGBInputInterface,
               VideoRGBInputRow)


class VideoRGBInputAppletTestCase(GlasgowAppletV2TestCase, applet=VideoRGBInputApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--r", "A0:4", "--g", "A5:7,B0:1", "--b", "B2:6",
                                "--dck", "B7", "--columns", "160", "--rows", "144",
                                "--vblank", "960e-6"])

    @async_test
    async def test_read_row(self):
        iface = object.__new__(VideoRGBInputInterface)
        iface._pipe = AsyncMock()
        iface._pipe.recv.side_effect = [bytes([value]) for value in
                                       (1, 31, 0, 0xc3, 17, 4, 0xbe, 2)]
        self.assertEqual(await iface.read_row(), VideoRGBInputRow(1, 145, True))
        self.assertEqual(await iface.read_row(), VideoRGBInputRow(31, 2, False))

    def test_invalid_configuration(self):
        for rows, columns, vblank in (
            (0, 160, 960e-6), (257, 160, 960e-6), (144, 0, 960e-6),
            (144, 160, 0), (144, 160, -1),
            (144, 160, float("nan")), (144, 160, float("inf")),
        ):
            with self.subTest(rows=rows, columns=columns, vblank=vblank):
                with self.assertRaises(GlasgowAppletError):
                    VideoRGBInputInterface(Mock(), Mock(), r=(), g=(), b=(), dck=None,
                                           rows=rows, columns=columns, vblank=vblank)

    def test_capture(self):
        ports = PortGroup(
            r=io.SimulationPort("i", 5),
            g=io.SimulationPort("i", 5),
            b=io.SimulationPort("i", 5),
            dck=io.SimulationPort("i", 1),
        )
        dut = VideoRGBInputComponent(rows=2, columns=2, vblank=32e-6,
                                    ports=ports, sys_clk_freq=1e6)
        captured = []

        async def monitor(ctx):
            while True:
                _, _, valid, ready, data = await ctx.tick().sample(
                    dut.o_stream.valid, dut.o_stream.ready, dut.o_stream.payload)
                if valid and ready:
                    captured.append(data)

        async def testbench(ctx):
            ctx.set(dut.o_stream.ready, 1)

            async def pixel(r, g, b):
                ctx.set(ports.dck.i, 0)
                ctx.set(ports.r.i, r)
                ctx.set(ports.g.i, g)
                ctx.set(ports.b.i, b)
                await ctx.tick().repeat(12)
                ctx.set(ports.dck.i, 1)
                await ctx.tick().repeat(12)

            # The first pixel of a frame is skipped by this LCD capture protocol.
            await pixel(0, 0, 0)
            await pixel(1, 2, 3)
            await pixel(4, 5, 6)
            await pixel(0, 0, 0) # row boundary clock
            await pixel(7, 8, 9)
            await pixel(10, 11, 12)
            self.assertEqual(captured, [0x82, 0, 1, 2, 3, 4, 5, 6,
                                        0x82, 1, 7, 8, 9, 10, 11, 12])

            # Holding DCK high through blanking resets row/column state.
            await ctx.tick().repeat(40)
            await pixel(0, 0, 0)
            await pixel(13, 14, 15)
            self.assertEqual(captured[-5:], [0x84, 0, 13, 14, 15])

            # Overflow drops the rest of the frame and is reported in the next frame.
            ctx.set(dut.o_stream.ready, 0)
            await pixel(16, 17, 18)
            await ctx.tick().repeat(40)
            ctx.set(dut.o_stream.ready, 1)
            await pixel(0, 0, 0)
            await pixel(19, 20, 21)
            self.assertEqual(captured[-5:], [0xc6, 0, 19, 20, 21])

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(monitor, background=True)
        sim.add_testbench(testbench)
        sim.run()
