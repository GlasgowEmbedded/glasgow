from ... import *
from . import ProgramECP5SRAMApplet


class ProgramECP5SRAMAppletTestCase(GlasgowAppletTestCase, applet=ProgramECP5SRAMApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
