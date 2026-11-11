import asyncio
import logging
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from amaranth.hdl import Fragment
from amaranth.lib import io
from amaranth.sim import Simulator
from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test
from . import VideoWS2812OutputApplet, WS2812OutputInterface, VideoWS2812OutputComponent


class VideoWS2812OutputAppletTestCase(GlasgowAppletV2TestCase, applet=VideoWS2812OutputApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--out", "A0:3", "-c", "1024"])


class WS2812OutputInterfaceTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_write_frames(self):
        iface = object.__new__(WS2812OutputInterface)
        iface.frame_size = 6
        iface._pipe = SimpleNamespace(send=AsyncMock(), flush=AsyncMock())
        await iface.write(bytes(12))
        iface._pipe.send.assert_awaited_once_with(bytes(12))
        iface._pipe.flush.assert_awaited_once()
        with self.assertRaises(ValueError):
            await iface.write(bytes(5))
        self.assertEqual(iface._pipe.send.await_count, 1)

    async def test_socket_frames_and_disconnect(self):
        # A partial frame from one client must not be combined with the next client's data.
        endpoint = SimpleNamespace(recv=AsyncMock(side_effect=[
            b"abc", b"def", b"x", EOFError(), b"123456789012", asyncio.CancelledError()
        ]))
        iface = SimpleNamespace(frame_size=6, buffer_size=96, write=AsyncMock())
        applet = SimpleNamespace(leds_iface=iface, logger=logging.getLogger(__name__))
        with patch(f"{VideoWS2812OutputApplet.__module__}.ServerEndpoint",
                   new=AsyncMock(return_value=endpoint)):
            with self.assertRaises(asyncio.CancelledError):
                await VideoWS2812OutputApplet.run(applet, SimpleNamespace(endpoint="tcp::1234"))
        self.assertEqual([call.args[0] for call in iface.write.await_args_list],
                         [b"abcdef", b"123456789012"])
        self.assertEqual([call.args for call in endpoint.recv.await_args_list],
                         [(), (3,), (), (5,), (), ()])


class VideoWS2812OutputComponentTestCase(unittest.TestCase):
    def test_pixel_formats(self):
        for name, (in_size, out_size, convert) in WS2812OutputInterface.pixel_formats.items():
            with self.subTest(pixel_format=name):
                port = io.SimulationPort("o", 2)
                component = VideoWS2812OutputComponent(
                    SimpleNamespace(out=port), 1, in_size, out_size, convert)
                # Use the hardware clock frequency so the serializer timing is exercised unchanged.
                fragment = Fragment.get(component,
                    platform=SimpleNamespace(default_clk_frequency=48_000_000))
                sim = Simulator(fragment)
                sim.add_clock(1 / 48_000_000)
                pixels = [bytes([0x12, 0x34, 0x56, 0x78][:in_size]),
                          bytes([0x9a, 0xbc, 0xde, 0xf0][:in_size])]
                expected = [bytes([p[1], p[0], p[2]]) +
                            (bytes([p[3] if in_size == 4 else 0]) if out_size == 4 else b"")
                            for p in pixels]

                async def bench(ctx):
                    for byte in b"".join(pixels):
                        ctx.set(component.i_stream.payload, byte)
                        ctx.set(component.i_stream.valid, 1)
                        await ctx.tick().until(component.i_stream.ready)
                    ctx.set(component.i_stream.valid, 0)
                    for bit in range(out_size * 8):
                        await ctx.tick().until(port.o == 3)
                        # Zero pulses last 5 cycles; one pulses last 37 cycles.
                        await ctx.tick().repeat(10)
                        value = ctx.get(port.o)
                        for string in range(2):
                            expected_bit = (expected[string][bit // 8] >> (7 - bit % 8)) & 1
                            self.assertEqual((value >> string) & 1, expected_bit)
                        await ctx.tick().until(port.o == 0)
                    await ctx.tick().repeat(14_500)
                    self.assertEqual(ctx.get(port.o), 0)
                    self.assertEqual(ctx.get(component.i_stream.ready), 1)

                sim.add_testbench(bench)
                sim.run()
