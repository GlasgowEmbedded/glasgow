from amaranth import *

from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test
from . import QSPIControllerApplet


class QSPIControllerAppletTestCase(GlasgowAppletV2TestCase, applet=QSPIControllerApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
