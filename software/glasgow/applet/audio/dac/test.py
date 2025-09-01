from amaranth import *
from amaranth.sim import SimulatorContext

from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_simulation_test
from . import AudioDACApplet


class AudioDACAppletTestCase(GlasgowAppletV2TestCase, applet=AudioDACApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--unsigned"])

    @applet_v2_simulation_test(args=["--unsigned"])
    async def test_dc(self, applet: AudioDACApplet, ctx: SimulatorContext):
        resolution = 256
        out_pin = applet.assembly.get_pin("A0")
        await applet.pcm_iface.modulation_clock.set_frequency(1/applet.assembly.sys_clk_period)
        sample_period = applet.assembly.sys_clk_period * resolution
        await applet.pcm_iface.sample_clock.set_frequency(1/sample_period)

        async def count_pulses_per_period(val):
            await applet.pcm_iface.write([val])
            # Ensure that the dac channel updated with val
            await ctx.delay(sample_period*1.1)
            count = 0
            for _ in range(resolution):
                await ctx.tick()
                count += ctx.get(out_pin.o)
            return count

        for val in (0, 128, 255):
            assert val == await(count_pulses_per_period(val))
