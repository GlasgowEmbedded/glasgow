from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test
from . import SensorPMSx003Applet


class SensorPMSx003AppletTestCase(GlasgowAppletV2TestCase, applet=SensorPMSx003Applet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
