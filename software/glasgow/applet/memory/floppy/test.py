from ... import *
from . import MemoryFloppyApplet


class MemoryFloppyAppletTestCase(GlasgowAppletTestCase, applet=MemoryFloppyApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
