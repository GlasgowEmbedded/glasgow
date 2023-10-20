from ... import *
from . import ProgramICE40FlashApplet


class ProgramICE40FlashAppletTestCase(GlasgowAppletTestCase, applet=ProgramICE40FlashApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
