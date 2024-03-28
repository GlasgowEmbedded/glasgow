from amaranth import *

from ... import *
from . import ControlN64Applet


class ControlN64AppletTestCase(GlasgowAppletTestCase, applet=ControlN64Applet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
