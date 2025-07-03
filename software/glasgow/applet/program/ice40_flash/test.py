from ... import *
from . import ProgramICE40FlashApplet


class ProgramICE40FlashAppletTestCase(GlasgowAppletV2TestCase, applet=ProgramICE40FlashApplet):
    @synthesis_test
    def test_build_with_done(self):
        self.assertBuilds(args=["--done", "A7"])

    @synthesis_test
    def test_build_without_done(self):
        self.assertBuilds(args=["--done", "-"])
