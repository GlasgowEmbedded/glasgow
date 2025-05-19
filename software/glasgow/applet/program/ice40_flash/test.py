from ... import *
from . import ProgramICE40FlashApplet


class ProgramICE40FlashAppletTestCase(GlasgowAppletV2TestCase, applet=ProgramICE40FlashApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds("--reset B0 --done B1")
