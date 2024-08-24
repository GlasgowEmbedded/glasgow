from ... import *
from . import ControlGPIOApplet


class ControlGPIOAppletTestCase(GlasgowAppletTestCase, applet=ControlGPIOApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
