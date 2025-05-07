from amaranth import *

from ... import *
from . import GPIBControllerApplet

class GPIBControllerAppletTestCase(GlasgowAppletTestCase, applet=GPIBCommandApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
