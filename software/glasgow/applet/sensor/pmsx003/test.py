from ... import *
from . import SensorPMSx003Applet


class SensorPMSx003AppletTestCase(GlasgowAppletTestCase, applet=SensorPMSx003Applet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
