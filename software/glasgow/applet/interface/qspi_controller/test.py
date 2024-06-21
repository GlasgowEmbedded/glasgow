from amaranth import *

from ... import *
from . import QSPIControllerApplet


class QSPIControllerAppletTestCase(GlasgowAppletTestCase, applet=QSPIControllerApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
