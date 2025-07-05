from ... import *
from . import I2CInitiatorApplet


class I2CInitiatorAppletTestCase(GlasgowAppletTestCase, applet=I2CInitiatorApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
