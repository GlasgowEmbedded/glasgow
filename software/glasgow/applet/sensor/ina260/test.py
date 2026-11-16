from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test
from . import SensorINA260Applet


class SensorINA260AppletTestCase(GlasgowAppletV2TestCase, applet=SensorINA260Applet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
