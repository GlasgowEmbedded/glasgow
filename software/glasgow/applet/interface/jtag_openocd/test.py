from ... import *
from . import JTAGOpenOCDApplet


class JTAGOpenOCDAppletTestCase(GlasgowAppletTestCase, applet=JTAGOpenOCDApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
