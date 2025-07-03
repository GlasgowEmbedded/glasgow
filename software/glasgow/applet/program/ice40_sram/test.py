from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test
from . import ProgramICE40SRAMApplet


class ProgramICE40SRAMAppletTestCase(GlasgowAppletV2TestCase, applet=ProgramICE40SRAMApplet):
    @synthesis_test
    def test_build_with_done(self):
        self.assertBuilds(args=["--done", "A7"])

    @synthesis_test
    def test_build_without_done(self):
        self.assertBuilds(args=["--done", "-"])
