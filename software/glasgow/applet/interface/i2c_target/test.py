from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test
from . import I2CTargetApplet


class I2CTargetAppletTestCase(GlasgowAppletV2TestCase, applet=I2CTargetApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["-A", "0b1010000"])

    @synthesis_test
    def test_build_pulls(self):
        self.assertBuilds(args=["-A", "0x50", "--pulls"])
