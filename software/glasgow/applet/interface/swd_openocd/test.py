from ... import *
from . import SWDOpenOCDApplet


class SWDOpenOCDAppletTestCase(GlasgowAppletTestCase, applet=SWDOpenOCDApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
