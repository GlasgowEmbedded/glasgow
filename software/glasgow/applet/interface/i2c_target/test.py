from ... import *
from . import I2CTargetApplet


class I2CTargetAppletTestCase(GlasgowAppletTestCase, applet=I2CTargetApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["-A", "0b1010000"])
