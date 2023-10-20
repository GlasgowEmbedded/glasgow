from ... import *
from . import JTAGPinoutApplet


class JTAGPinoutAppletTestCase(GlasgowAppletTestCase, applet=JTAGPinoutApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--pins-jtag", "0:3"])
