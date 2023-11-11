from ... import *
from . import ControlServoApplet


class ControlServoAppletTestCase(GlasgowAppletTestCase, applet=ControlServoApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
