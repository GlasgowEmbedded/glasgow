from glasgow.simulation.assembly import SimulationAssembly
from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_simulation_test
from . import SensorHCSR04Applet


class SensorHCSR04AppletTestCase(GlasgowAppletV2TestCase, applet=SensorHCSR04Applet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    def prepare(self, assembly: SimulationAssembly):
        trig = assembly.get_pin("A0")
        echo = assembly.get_pin("A1")

        async def sensor_model(ctx):
            await ctx.tick()
            while True:
                await ctx.posedge(trig.o)
                await ctx.tick().repeat(1000)
                ctx.set(echo.i, 1)
                await ctx.tick().repeat(2500)
                ctx.set(echo.i, 0)

        assembly.add_testbench(sensor_model, background=True)

    @applet_v2_simulation_test(prepare=prepare, args=["--trig", "A0", "--echo", "A1"])
    async def test_sim(self, applet, ctx):
        await applet.hcsr04_iface._start.set(1)
        await ctx.tick().repeat(20000)
        assert (await applet.hcsr04_iface._distance) == 2500
