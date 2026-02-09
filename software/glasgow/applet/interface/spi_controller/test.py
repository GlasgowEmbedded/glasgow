from amaranth import *

from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_simulation_test
from . import SPIControllerApplet


class SPIControllerAppletTestCase(GlasgowAppletV2TestCase, applet=SPIControllerApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    def setup_loopback(self, assembly):
        assembly.connect_pins("A2", "A3")

    @applet_v2_simulation_test(prepare=setup_loopback,
                               args=["--sck",  "A0", "--cs",   "A1",
                                     "--copi", "A2", "--cipo", "A3"])
    async def test_loopback(self, applet, ctx):
        cs = applet.assembly.get_pin("A1")
        self.assertEqual(ctx.get(cs.o), 1)
        async with applet.spi_iface.select():
            result = await applet.spi_iface.exchange([0xAA, 0x55, 0x12, 0x34])
            self.assertEqual(ctx.get(cs.o), 0)
            self.assertEqual(result, bytearray([0xAA, 0x55, 0x12, 0x34]))
        await ctx.tick().repeat(10)
        self.assertEqual(ctx.get(cs.o), 1)
