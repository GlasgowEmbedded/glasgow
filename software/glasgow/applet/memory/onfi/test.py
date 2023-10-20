from ... import *
from . import MemoryONFIApplet


class MemoryONFIAppletTestCase(GlasgowAppletTestCase, applet=MemoryONFIApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--port", "AB"])
