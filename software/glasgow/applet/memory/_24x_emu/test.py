from ... import *
from . import Memory24xEmuApplet


class Memory24xEmuAppletTestCase(GlasgowAppletTestCase, applet=Memory24xEmuApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["-A", "0b1010000"])
