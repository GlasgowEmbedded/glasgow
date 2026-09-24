from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test
from . import ControlTPS6598xApplet


class ControlTPS6598xAppletTestCase(GlasgowAppletV2TestCase, applet=ControlTPS6598xApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
