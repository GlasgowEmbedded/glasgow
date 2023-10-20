from ... import *
from . import SelfTestApplet


class SelfTestAppletTestCase(GlasgowAppletTestCase, applet=SelfTestApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
