from types import SimpleNamespace

from amaranth import Cat
from amaranth.lib import io
from amaranth.sim import Simulator

from glasgow.applet import GlasgowAppletError, GlasgowAppletV2TestCase, synthesis_test
from glasgow.simulation.assembly import SimulationAssembly

from . import Modeline, VGAOutputApplet, VGAOutputGenerator, VGATestPattern


class VGAOutputAppletTestCase(GlasgowAppletV2TestCase, applet=VGAOutputApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    def test_invalid_mode(self):
        for arguments in (
            "--h-active 0",
            "--h-sync 0",
            "--v-active 0",
            "--v-sync 0",
            "--h-front -1",
            "--h-back -1",
            "--v-front -1",
            "--v-back -1",
            "--pix-clk-freq 0",
            "--refresh-rate 0",
        ):
            with self.subTest(arguments=arguments):
                args = self._parse_args(arguments, mode="build")
                applet = VGAOutputApplet(SimulationAssembly())
                with self.assertRaises(GlasgowAppletError):
                    applet.build(args)

    def test_timing_and_patterns(self):
        h_active_px = 36
        h_front_px = 1
        h_sync_px = 2
        h_back_px = 1
        v_active_lines = 5
        v_front_lines = 1
        v_sync_lines = 1
        v_back_lines = 1
        h_total_px = h_active_px + h_front_px + h_sync_px + h_back_px
        v_total_lines = v_active_lines + v_front_lines + v_sync_lines + v_back_lines

        def expected_pixel(pattern, x, y):
            if x >= h_active_px or y >= v_active_lines:
                return 0
            match pattern:
                case VGATestPattern.Quilt:
                    return (x >> 5) + (y >> 5)
                case VGATestPattern.Rect:
                    return 0b111 if (
                        x == 0 or y == 0 or
                        x == h_active_px - 1 or y == v_active_lines - 1
                    ) else 0
                case VGATestPattern.Grid:
                    return 0b111 if (x & 0x1f) == 0 or (y & 0x1f) == 0 else 0
                case VGATestPattern.Flag:
                    return (0b110, 0b101, 0b111, 0b101, 0b110)[y]

        for pattern in VGATestPattern:
            with self.subTest(pattern=pattern):
                ports = SimpleNamespace(
                    hs=io.SimulationPort("o", 1),
                    vs=io.SimulationPort("o", 1),
                    r=io.SimulationPort("o", 1),
                    g=io.SimulationPort("o", 1),
                    b=io.SimulationPort("o", 1),
                )
                dut = VGAOutputGenerator(ports=ports, modeline=Modeline(
                    h_front_px=h_front_px,
                    h_sync_px=h_sync_px,
                    h_back_px=h_back_px,
                    h_active_px=h_active_px,
                    v_front_lines=v_front_lines,
                    v_sync_lines=v_sync_lines,
                    v_back_lines=v_back_lines,
                    v_active_lines=v_active_lines,
                ), test_pattern=pattern)

                async def testbench(ctx, dut=dut, pattern=pattern, ports=ports):
                    # Allow the output flip-flops to capture the first pixel.
                    await ctx.tick()
                    for y in range(v_total_lines):
                        for x in range(h_total_px):
                            hs_expected = \
                                h_active_px + h_front_px <= x < \
                                h_active_px + h_front_px + h_sync_px
                            vs_expected = \
                                v_active_lines + v_front_lines <= y < \
                                v_active_lines + v_front_lines + v_sync_lines
                            _, _, hs, vs, rgb = await ctx.tick().sample(
                                ports.hs.o, ports.vs.o, Cat(ports.r.o, ports.g.o, ports.b.o))
                            self.assertEqual(hs, hs_expected, (x, y))
                            self.assertEqual(vs, vs_expected, (x, y))
                            self.assertEqual(
                                rgb, expected_pixel(pattern, x, y), (x, y))

                sim = Simulator(dut)
                sim.add_clock(1e-6)
                sim.add_testbench(testbench)
                sim.run()
