from glasgow.simulation.assembly import SimulationAssembly
from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_simulation_test
from . import CalibrateClockApplet


class CalibrateClockAppletTestCase(GlasgowAppletV2TestCase, applet=CalibrateClockApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(["--ref-pin", "A0", "--ref-freq", "1000", "-V", "3.3"])

    # Simulation clock is 1 MHz. Use a 1 kHz reference (toggle every 500 ticks)
    # and a 1 ms gate time (1 ref edge per gate) so the gate fires after ~1000 ticks.
    simulation_args = ["--ref-pin", "A0", "--ref-freq", "1000", "--gate-time", "0.001",
                       "--nominal-sys-clk", "1e6", "-V", "3.3"]

    def prepare_ref_clock(self, assembly: SimulationAssembly):
        ref_pin = assembly.get_pin("A0")

        async def drive_ref(ctx):
            # Toggle ref pin every 500 cycles to produce a 1 kHz signal
            # relative to the 1 MHz simulation clock.
            while True:
                ctx.set(ref_pin.i, 1)
                await ctx.tick().repeat(500)
                ctx.set(ref_pin.i, 0)
                await ctx.tick().repeat(500)

        assembly.add_testbench(drive_ref, background=True)

    @applet_v2_simulation_test(prepare=prepare_ref_clock, args=simulation_args)
    async def test_measure_sys_clk(self, applet: CalibrateClockApplet, ctx):
        result = await applet.cal_iface.measure()
        # In simulation all clocks are exact, so sys_ppm should be 0.
        self.assertAlmostEqual(result["sys_ppm"], 0.0, delta=10.0)
        self.assertAlmostEqual(result["gate_time_sec"], 0.001, delta=0.01)
        self.assertIsNone(result["ext_hz"])
        self.assertIsNone(result["ext_ppm"])
