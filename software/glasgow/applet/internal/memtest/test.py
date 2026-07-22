from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_simulation_test

from . import MemoryTestApplet, Pattern


class MemoryTestAppletTestCase(GlasgowAppletV2TestCase, applet=MemoryTestApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    @applet_v2_simulation_test()
    async def test_simulation(self, applet: MemoryTestApplet, ctx):
        region = range(0x000, 0x800, 0x200)

        # `iface.run()` would run `asyncio.sleep()`, which we don't support.
        for iface in applet.memtest_ifaces:
            await iface._start_addr.set(region.start)
            await iface._stop_addr.set(region.stop)
            await iface._block_size.set(region.step)
            for pattern in Pattern:
                await iface._pattern.set(pattern)
                await iface._active.set(1)
                while (await iface._cycles.get()) < 1:
                    await ctx.tick()
                errors = await iface._errors.get()
                assert errors == 0
                await iface._active.set(0)
                await ctx.tick()
