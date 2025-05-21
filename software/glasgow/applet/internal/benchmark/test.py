from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test
from . import BenchmarkApplet


class BenchmarkAppletTestCase(GlasgowAppletV2TestCase, applet=BenchmarkApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
