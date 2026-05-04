from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test
from . import SensorQMC5883PApplet


class SensorQMC5883PAppletTestCase(GlasgowAppletV2TestCase, applet=SensorQMC5883PApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
