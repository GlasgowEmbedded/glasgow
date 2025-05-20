from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test
from . import ControlServoApplet


class ControlServoAppletTestCase(GlasgowAppletV2TestCase, applet=ControlServoApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
