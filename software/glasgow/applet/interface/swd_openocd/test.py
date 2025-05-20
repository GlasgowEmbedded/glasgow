from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test
from . import SWDOpenOCDApplet


class SWDOpenOCDAppletTestCase(GlasgowAppletV2TestCase, applet=SWDOpenOCDApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    @synthesis_test
    def test_build_srst(self):
        self.assertBuilds("--srst A7")