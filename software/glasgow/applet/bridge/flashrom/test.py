from amaranth import *

from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test
from . import FlashromApplet


class FlashromAppletTestCase(GlasgowAppletV2TestCase, applet=FlashromApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
