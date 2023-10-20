from ... import *
from . import SensorHX711Applet


class SensorHX711AppletTestCase(GlasgowAppletTestCase, applet=SensorHX711Applet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
