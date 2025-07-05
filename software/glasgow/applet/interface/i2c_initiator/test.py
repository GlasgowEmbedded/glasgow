from amaranth import *

from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_simulation_test
from . import I2CInitiatorApplet



class I2CInitiatorAppletTestCase(GlasgowAppletV2TestCase, applet=I2CInitiatorApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
