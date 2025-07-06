from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test
from . import RadioNRF24L01Applet


class RadioNRF24L01AppletTestCase(GlasgowAppletV2TestCase, applet=RadioNRF24L01Applet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
