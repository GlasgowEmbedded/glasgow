from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test
from . import JTAGPinoutApplet


class JTAGPinoutAppletTestCase(GlasgowAppletV2TestCase, applet=JTAGPinoutApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--pins", "A0:3"])
