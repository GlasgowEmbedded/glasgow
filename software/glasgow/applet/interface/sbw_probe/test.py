from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test
from . import SpyBiWireProbeApplet


class SpyBiWireProbeAppletTestCase(GlasgowAppletV2TestCase, applet=SpyBiWireProbeApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
