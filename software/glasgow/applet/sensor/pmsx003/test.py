from ... import *
from . import SensorPMSx003Applet


class PMSx003AppletTestCase(GlasgowAppletTestCase, applet=SensorPMSx003Applet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
