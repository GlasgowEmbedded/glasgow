from amaranth import *

from ... import *
from . import N64TASApplet


class N64TASAppletTestCase(GlasgowAppletTestCase, applet=N64TASApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
