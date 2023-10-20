from ... import *
from . import MemoryPROMApplet


class MemoryPROMAppletTestCase(GlasgowAppletTestCase, applet=MemoryPROMApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
