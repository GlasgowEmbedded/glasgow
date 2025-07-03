from amaranth import *

from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test
from . import SPIFlashromApplet


class SPIFlashromAppletTestCase(GlasgowAppletV2TestCase, applet=SPIFlashromApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
