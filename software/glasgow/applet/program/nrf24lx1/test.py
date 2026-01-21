from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test
from . import ProgramNRF24Lx1Applet


class ProgramNRF24Lx1AppletTestCase(GlasgowAppletV2TestCase, applet=ProgramNRF24Lx1Applet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
