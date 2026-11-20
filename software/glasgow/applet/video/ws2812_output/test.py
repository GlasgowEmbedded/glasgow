import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from amaranth.hdl import Fragment
from amaranth.lib import io
from amaranth.sim import Simulator
from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_hardware_test
from . import VideoWS2812OutputApplet, WS2812OutputInterface, VideoWS2812OutputComponent


class VideoWS2812OutputAppletTestCase(GlasgowAppletV2TestCase, applet=VideoWS2812OutputApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--out", "A0:3", "-c", "1024"])

    # Fixtures specify expected transport operations; they were not recorded on hardware.
    @applet_v2_hardware_test(args="--out A0:1 --count 1", mocks=["leds_iface._pipe"])
    async def test_write_frames(self, applet):
        self.assertEqual(applet.leds_iface.frame_size, 6)
        self.assertEqual(applet.leds_iface.buffer_size, 96)
        with self.assertRaises(ValueError):
            await applet.leds_iface.write(bytes(5))
        await applet.leds_iface.write(bytes(range(12)))

    @applet_v2_hardware_test(args="--out A0:1 --count 1",
                            mocks=["leds_iface._framerate"])
    async def test_setup_framerate(self, applet):
        await applet.setup(SimpleNamespace(framerate=None))
        await applet.setup(SimpleNamespace(framerate=60))

    @applet_v2_hardware_test(args="--out A0:1 --count 1", mocks=["leds_iface._pipe"])
    async def test_socket_frames_and_disconnect(self, applet):
        # A partial frame from one client must not be combined with the next client's data.
        endpoint = SimpleNamespace(recv=AsyncMock(side_effect=[
            b"abc", b"def", b"x", EOFError(), b"123456789012", asyncio.CancelledError()
        ]))
        with patch(f"{VideoWS2812OutputApplet.__module__}.ServerEndpoint",
                   new=AsyncMock(return_value=endpoint)):
            with self.assertRaises(asyncio.CancelledError):
                await applet.run(SimpleNamespace(endpoint="tcp::1234"))
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
                expected = [(bytes(p) if name == "RGB-BGR" else bytes([p[1], p[0], p[2]])) +
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

    def test_framerate_limiter(self):
        for divisor in (0, 20_000, 40_000):
            with self.subTest(divisor=divisor):
                port = io.SimulationPort("o", 1)
                in_size, out_size, convert = WS2812OutputInterface.pixel_formats["RGB-BRG"]
                component = VideoWS2812OutputComponent(
                    SimpleNamespace(out=port), 1, in_size, out_size, convert)
                fragment = Fragment.get(component,
                    platform=SimpleNamespace(default_clk_frequency=48_000_000))
                sim = Simulator(fragment)
                sim.add_clock(1 / 48_000_000)

                async def bench(ctx):
                    ctx.set(component.framerate_divisor, divisor)
                    # Check two periods, including restarting the elapsed-time counter.
                    for _ in range(2):
                        # Idle time before a frame must not consume its rate limit.
                        await ctx.tick().repeat(50_000)
                        ctx.set(component.i_stream.valid, 1)
                        for _ in range(3):
                            await ctx.tick()
                        ctx.set(component.i_stream.valid, 0)
                        cycles = 3
                        while not ctx.get(component.i_stream.ready):
                            if cycles > 16000:
                                self.assertEqual(ctx.get(port.o), 0)
                            await ctx.tick()
                            cycles += 1
                            self.assertLessEqual(cycles, max(divisor + 2, 17000))
                        # ClockDivisor encodes period minus one. The serializer and reset
                        # interval remain the lower bound when no extra delay is requested.
                        self.assertGreaterEqual(cycles, max(divisor + 1, 14401))
                        if divisor:
                            self.assertEqual(cycles, divisor + 2)

                sim.add_testbench(bench)
                sim.run()
