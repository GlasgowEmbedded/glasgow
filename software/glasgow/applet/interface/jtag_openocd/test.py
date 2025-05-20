from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test
from . import JTAGOpenOCDApplet


class JTAGOpenOCDAppletTestCase(GlasgowAppletV2TestCase, applet=JTAGOpenOCDApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    @synthesis_test
    def test_build_trst_srst(self):
        self.assertBuilds("--trst A6 --srst A7")
