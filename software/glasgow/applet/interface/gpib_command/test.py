from ... import *
from . import GPIBCommandApplet

class GPIBCommandAppletTestCase(GlasgowAppletTestCase, applet=GPIBCommandApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
