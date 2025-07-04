from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test

from . import ProbeRsApplet


class ProbeRsAppletTestCase(GlasgowAppletV2TestCase, applet=ProbeRsApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
