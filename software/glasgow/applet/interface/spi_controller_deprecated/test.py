import types
from amaranth import *
from amaranth.lib import io

from ... import *
from . import SPIControllerApplet


class SPIControllerAppletTestCase(GlasgowAppletTestCase, applet=SPIControllerApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--sck",  "A0", "--cs",   "A1",
                                "--copi", "A2", "--cipo", "A3"])

    def setup_loopback(self, target, parsed_args):
        self.applet.build(target, parsed_args)
        target.assembly.connect_pins("A2", "A3")

    @applet_simulation_test("setup_loopback",
                            ["--sck",  "A0", "--cs",   "A1",
                             "--copi", "A2", "--cipo", "A3",
                             "--frequency", "10"])
    async def test_loopback(self, device, parsed_args, ctx):
        spi_iface = await self.applet.run(device, parsed_args)

        cs = device.assembly.get_pin("A1")
        self.assertEqual(ctx.get(cs.o), 1)
        async with spi_iface.select():
            await ctx.tick().repeat(2)
            self.assertEqual(ctx.get(cs.o), 0)
            result = await spi_iface.exchange([0xAA, 0x55, 0x12, 0x34])
            self.assertEqual(result, bytearray([0xAA, 0x55, 0x12, 0x34]))
        await ctx.tick()
        self.assertEqual(ctx.get(cs.o), 1)
