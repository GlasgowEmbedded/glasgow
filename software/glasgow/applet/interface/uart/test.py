from amaranth import *

from ... import *
from . import UARTApplet


class UARTAppletTestCase(GlasgowAppletTestCase, applet=UARTApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    def setup_loopback(self, target, args):
        self.applet.build(target, args)
        target.assembly.connect_pins("A0", "A1")

    @applet_simulation_test("setup_loopback", ["--baud", "9600"])
    async def test_loopback(self, device, args, ctx):
        uart_iface = await self.applet.run(device, args)
        await uart_iface.write(bytes([0xAA, 0x55]))
        self.assertEqual(await uart_iface.read(2), bytes([0xAA, 0x55]))
