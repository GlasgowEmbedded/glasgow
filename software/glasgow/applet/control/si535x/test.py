from importlib_resources import files

from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_hardware_test
from . import ControlSi535xApplet


class ControlSi535xAppletTestCase(GlasgowAppletV2TestCase, applet=ControlSi535xApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    @applet_v2_hardware_test(mocks=["si535x_iface._i2c_iface"], args=["-V", "3.3"])
    async def test_si5351a(self, applet: ControlSi535xApplet):
        register_file = (
            files(__name__).joinpath("fixtures/si5351a-registers.txt").open()
        )
        await applet.si535x_iface.configure_si5351(
            sequence=applet.si535x_iface.parse_file(register_file), enable=0x01
        )
