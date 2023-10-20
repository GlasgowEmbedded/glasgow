from ... import *
from . import VGAOutputApplet


class VGAOutputAppletTestCase(GlasgowAppletTestCase, applet=VGAOutputApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--port", "B"])
