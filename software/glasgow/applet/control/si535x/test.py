import importlib_resources

from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_hardware_test
from . import ControlSi535xApplet


class ControlSi535xAppletTestCase(GlasgowAppletV2TestCase, applet=ControlSi535xApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    @applet_v2_hardware_test(mocks=["si535x_iface._i2c_iface"], args=["-V", "3.3"])
    async def test_si5351a(self, applet: ControlSi535xApplet):
        with importlib_resources.open_text(__name__, "fixtures/si5351a-registers.txt") as file:
            await applet.si535x_iface.configure_si5351(
                sequence=applet.si535x_iface.parse_file(file),
                enable=0x01)
