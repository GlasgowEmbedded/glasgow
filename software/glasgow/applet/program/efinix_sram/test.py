from amaranth import *
from amaranth.sim import SimulatorContext


from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_simulation_test
from . import ProgramEfinixSRAMApplet


class ProgramEfinixSRAMAppletAppletTestCase(GlasgowAppletV2TestCase, applet=ProgramEfinixSRAMApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=[
            "--creset", "A0", "--cs", "A1", "--cck", "A2",
            "--freset", "A4", "--cbus", "A5,A6,A7", "--cdi", "B0"
        ])

    @applet_v2_simulation_test(args=[
        "--creset", "A0", "--cs", "A1", "--cck", "A2",
        "--freset", "A4", "--cbus", "A5,A6,A7", "--cdi", "B0", "--frequency", "1000"
    ])
    async def test_iface(self, applet: ProgramEfinixSRAMApplet, ctx: SimulatorContext):
        applet.efinix_iface._delay = ctx.delay
        await applet.efinix_iface.load(b"\x00\x01\xaa\x55\x80\xff")

    @applet_v2_simulation_test(args=[
        "--creset", "A0", "--cs", "A1", "--cck", "A2",
        "--freset", "A4", "--cbus", "A5,A6,A7", "--cdi",
        "B0,B1,B2,B3,B4,B5,B6,B7", "--frequency", "1000"
    ])
    async def test_iface_8bit(self, applet: ProgramEfinixSRAMApplet, ctx: SimulatorContext):
        applet.efinix_iface._delay = ctx.delay
        await applet.efinix_iface.load(b"\x00\x01\xaa\x55\x80\xff")
