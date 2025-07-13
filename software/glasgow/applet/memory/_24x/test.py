import unittest

from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_hardware_test
from . import Memory24xApplet


class Memory24xAppletTestCase(GlasgowAppletV2TestCase, applet=Memory24xApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds("-W 2")

    @applet_v2_hardware_test(args="-V 3.3 -W 1 -P 4", mocks=["m24x_iface._i2c_iface"])
    async def test_hardware_1wide(self, applet):
        await applet.m24x_iface.write(0x100 - 9, b"mary had a little lamb")
        assert await applet.m24x_iface.read(0x100 - 9, 22) == b"mary had a little lamb"

    @applet_v2_hardware_test(args="-V 3.3 -W 2 -A 0x57", mocks=["m24x_iface._i2c_iface"])
    async def test_hardware_2wide(self, applet):
        await applet.m24x_iface.write(5, b"mary had a little lamb")
        assert await applet.m24x_iface.read(5, 22) == b"mary had a little lamb"
