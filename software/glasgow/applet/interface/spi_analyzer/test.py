from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_simulation_test

from . import SPIAnalyzerApplet


class SPIAnalyzerAppletTestCase(GlasgowAppletV2TestCase, applet=SPIAnalyzerApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
