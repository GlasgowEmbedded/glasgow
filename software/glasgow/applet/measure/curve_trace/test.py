from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test
from . import CurveTraceApplet


class CurveTraceAppletTestCase(GlasgowAppletV2TestCase, applet=CurveTraceApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(["--port", "A", "-V", "3.3"])
