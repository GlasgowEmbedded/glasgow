from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test
from . import GeneratePRNNoiseApplet


class GeneratePRNNoiseAppletTestCase(GlasgowAppletV2TestCase, applet=GeneratePRNNoiseApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(["--out", "A0", "-V", "3.3"])
