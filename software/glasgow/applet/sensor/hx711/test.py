import itertools

from amaranth import *
from amaranth.sim import SimulatorContext

from glasgow.simulation.assembly import SimulationAssembly
from glasgow.applet import GlasgowAppletV2TestCase, applet_v2_simulation_test, synthesis_test
from . import SensorHX711Applet, HX711Setting


class SensorHX711AppletTestCase(GlasgowAppletV2TestCase, applet=SensorHX711Applet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
        self.assertBuilds("--osc=A2")

    simulation_args = []

    def prepare_target(self, assembly: SimulationAssembly):
        sck = assembly.get_pin("A0")
        din = assembly.get_pin("A1")

        sample_gap = 1.5e-4

        async def testbench(ctx: SimulatorContext):
            async def do_transaction(val: int):
                ctx.set(din.i, 0)
                await ctx.delay(1e-6)

                for i in range(25):
                    prev_sck = ctx.get(sck.o)
                    async for _ in ctx.tick():
                        cur_sck = ctx.get(sck.o)
                        if prev_sck != cur_sck and cur_sck == 1:
                            # posedge
                            break
                        prev_sck = cur_sck

                    if i < 24:
                        ctx.set(din.i, (val >> (23-i)) & 1)

                ctx.set(din.i, 1)

            ctx.set(din.i, 1)
            for val in itertools.count():
                await do_transaction(val)
                await ctx.delay(sample_gap)

        assembly.add_testbench(testbench, background=True)

    @applet_v2_simulation_test(prepare=prepare_target, args=simulation_args)
    async def test_hx711_sim(self, applet: SensorHX711Applet, ctx: SimulatorContext):
        # 100 kHz because simulation clk freq is 1 MHz
        await applet.hx711_iface.sck_clock.set_frequency(int(100e3))
        for i in range(4):
            val = await applet.hx711_iface.sample(HX711Setting.A_128)
            assert val == i
