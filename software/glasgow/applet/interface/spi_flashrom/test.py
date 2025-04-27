from amaranth import *

from ... import *
from . import SPIFlashromApplet


class SPIFlashromAppletTestCase(GlasgowAppletTestCase, applet=SPIFlashromApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()