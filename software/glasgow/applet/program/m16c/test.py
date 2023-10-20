from ... import *
from . import ProgramM16CApplet


class ProgramM16CAppletTestCase(GlasgowAppletTestCase, applet=ProgramM16CApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
