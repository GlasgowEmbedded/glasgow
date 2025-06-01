from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_simulation_test

from . import GPIOException, ControlGPIOApplet


class GPIOAppletTestCase(GlasgowAppletV2TestCase, applet=ControlGPIOApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds("--pins A0:3")

    @applet_v2_simulation_test(args="--pins A0:3")
    async def test_sim(self, applet, ctx):
        a0, a1, a2, a3 = map(applet.assembly.get_pin, ["A0", "A1", "A2", "A3"])

        assert ctx.get(a0.oe) == 0
        await applet.gpio_iface.output(0, 0)
        assert ctx.get(a0.oe) == 1
        assert ctx.get(a0.o)  == 0
        await applet.gpio_iface.output(0, 1)
        assert ctx.get(a0.oe) == 1
        assert ctx.get(a0.o)  == 1
        await applet.gpio_iface.input(0)
        assert ctx.get(a0.oe) == 0
        assert ctx.get(a0.o)  == 1

        assert await applet.gpio_iface.get(1) == 0
        assert await applet.gpio_iface.get_all() == 0b0000
        ctx.set(a1.i, 1)
        await ctx.tick().repeat(5)
        assert await applet.gpio_iface.get(1) == 1
        assert await applet.gpio_iface.get_all() == 0b0010
        ctx.set(a2.i, 1)
        await ctx.tick().repeat(5)
        assert await applet.gpio_iface.get_all() == 0b0110
        assert await applet.gpio_iface.get(0) == 0

        await applet.gpio_iface.output(2, 1)
        assert ctx.get(a2.o) == 1
        await applet.gpio_iface.set(2, 0)
        assert ctx.get(a2.o) == 0

        await applet.gpio_iface.set_all(0b1001)
        assert ctx.get(a0.o) == 1
        assert ctx.get(a1.o) == 0
        assert ctx.get(a2.o) == 0
        assert ctx.get(a3.o) == 1

        with self.assertRaisesRegex(IndexError, r"^pin 5 out of range \[0,4\)$"):
            await applet.gpio_iface.get(5)

        with self.assertRaisesRegex(GPIOException, r"^pin 0 is not configured as an output$"):
            await applet.gpio_iface.set(0, 1)
