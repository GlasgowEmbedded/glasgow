from amaranth import *

from ... import *
from . import UARTApplet


class UARTAppletTestCase(GlasgowAppletV2TestCase, applet=UARTApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    def prepare_loopback(self, assembly):
        assembly.connect_pins("A0", "A1")

    @applet_v2_simulation_test(prepare=prepare_loopback, args="--baud 9600")
    async def test_loopback(self, applet, ctx):
        await applet.uart_iface.write(bytes([0xAA, 0x55]))
        self.assertEqual(await applet.uart_iface.read(2), bytes([0xAA, 0x55]))

    # This test is here mainly to test the test machinery.
    @applet_v2_hardware_test(args="-V 3.3 --baud 9600", mock="uart_iface")
    async def test_loopback_hw(self, applet):
        await applet.uart_iface.write(bytes([0xAA, 0x55]))
        self.assertEqual(await applet.uart_iface.read(2), bytes([0xAA, 0x55]))
