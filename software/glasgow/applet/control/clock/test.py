from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test

from . import ControlClockApplet


class ControlClockAppletTestCase(GlasgowAppletV2TestCase, applet=ControlClockApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
