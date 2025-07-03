from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test
from . import PS2HostApplet


class PS2HostAppletTestCase(GlasgowAppletV2TestCase, applet=PS2HostApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
