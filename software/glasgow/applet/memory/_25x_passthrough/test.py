from amaranth import *

from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test
from . import Memory25xPassThroughApplet


class Memory25xPassThroughAppletTestCase(GlasgowAppletV2TestCase,
                                         applet=Memory25xPassThroughApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds("--chip w25q80dv")
        self.assertBuilds("--chip w25q80dv -d")
        self.assertBuilds("--chip mx25l6436f")
