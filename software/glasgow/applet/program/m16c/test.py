from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test
from . import ProgramM16CApplet


class ProgramM16CAppletTestCase(GlasgowAppletV2TestCase, applet=ProgramM16CApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    @synthesis_test
    def test_build_with_cnvss(self):
        self.assertBuilds(args=["--cnvss", "A3"])

    @synthesis_test
    def test_build_without_reset(self):
        self.assertBuilds(args=["--reset", "-"])
