from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test
from . import STUSB4500NVMApplet


class STUSB4500NVMAppletTestCase(GlasgowAppletV2TestCase, applet=STUSB4500NVMApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
