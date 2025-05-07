from amaranth import *

from ... import *
from . import GPIBControllerApplet

class GPIBControllerAppletTestCase(GlasgowAppletTestCase, applet=GPIBControllerApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
