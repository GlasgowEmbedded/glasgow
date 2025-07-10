from amaranth import *

from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_simulation_test
from . import I2CControllerApplet



class I2CControllerAppletTestCase(GlasgowAppletV2TestCase, applet=I2CControllerApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
