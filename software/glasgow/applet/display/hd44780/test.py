from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test
from . import DisplayHD44780Applet


class DisplayHD44780AppletTestCase(GlasgowAppletV2TestCase, applet=DisplayHD44780Applet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
