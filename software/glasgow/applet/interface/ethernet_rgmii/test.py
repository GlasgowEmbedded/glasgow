from ... import GlasgowAppletV2TestCase, synthesis_test
from . import EthernetRGMIIApplet


class EthernetRGMIIAppletTestCase(GlasgowAppletV2TestCase, applet=EthernetRGMIIApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
