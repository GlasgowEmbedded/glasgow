from ... import *
from . import RadioNRF24L01Applet


class RadioNRF24L01AppletTestCase(GlasgowAppletTestCase, applet=RadioNRF24L01Applet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
