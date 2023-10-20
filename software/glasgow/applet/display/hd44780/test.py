from ... import *
from . import DisplayHD44780Applet


class DisplayHD44780AppletTestCase(GlasgowAppletTestCase, applet=DisplayHD44780Applet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
