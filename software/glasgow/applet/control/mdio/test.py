from glasgow.arch.ieee802_3 import *
from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_hardware_test

from . import ControlMDIOApplet


class ControlMDIOAppletTestCase(GlasgowAppletV2TestCase, applet=ControlMDIOApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    # Requires a Microchip LAN8670 PHY connected, with a 50 MHz clock provided at REF_CLK pin.
    @applet_v2_hardware_test(mock="mdio_iface._pipe", args="-V A=3.3")
    async def test_microchip_lan8670(self, applet: ControlMDIOApplet):
        assert await applet.mdio_iface.c22_read(0, REG_PHY_ID1_addr) == 0x0007
        assert await applet.mdio_iface.c22_read(0, REG_PHY_ID2_addr) == 0xc165

        await applet.mdio_iface.c22_write(0, REG_BASIC_CONTROL_addr, 0x4000)
        assert await applet.mdio_iface.c22_read(0, REG_BASIC_CONTROL_addr) == 0x4000
        await applet.mdio_iface.c22_write(0, REG_BASIC_CONTROL_addr, 0x0000)

        await applet.mdio_iface.c45_write(0, 1, 0x08F9, 0x4000)
        assert await applet.mdio_iface.c45_read(0, 1, 0x08F9) == 0x4000
        await applet.mdio_iface.c45_write(0, 1, 0x08F9, 0x0000)
