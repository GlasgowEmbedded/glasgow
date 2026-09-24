from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test
from . import StUsb4500NvmApplet


class StUsb4500NvmAppletTestCase(GlasgowAppletV2TestCase, applet=StUsb4500NvmApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
