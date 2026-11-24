from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_simulation_test
from . import JTAGPinoutApplet


class JTAGPinoutAppletTestCase(GlasgowAppletV2TestCase, applet=JTAGPinoutApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--pins", "A0:3"])

    # 24 pins, so that some of the pins are not addressable with a 16-bit word.
    @applet_v2_simulation_test(args=["--pins", "A0:7,B0:7,C0:7"])
    async def test_wide_words(self, applet, ctx):
        pins = [applet.assembly.get_pin(f"{port}{index}") for port in "ABC" for index in range(8)]
        iface = applet.jtag_iface

        await iface.set_oe(1 << 20 | 1 << 3)
        await iface.set_o(1 << 20)
        await iface.set_o_1(1 << 23)
        await iface.set_o_0(1 << 20)
        await iface._pipe.flush()
        await ctx.tick().repeat(50)
        assert [ctx.get(pin.oe) for pin in pins] == [int(i in (3, 20)) for i in range(24)]
        assert [ctx.get(pin.o) for pin in pins][20:] == [0, 0, 0, 1]

        ctx.set(pins[22].i, 1)
        ctx.set(pins[1].i, 1)
        await ctx.tick().repeat(5)
        assert await iface.get_i() == 1 << 22 | 1 << 1
