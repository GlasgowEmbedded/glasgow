from ... import *
from . import FixedThroughputApplet


class FixedThroughputAppletTestCase(GlasgowAppletTestCase, applet=FixedThroughputApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
