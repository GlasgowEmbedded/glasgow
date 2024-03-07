from ... import *
from . import LevelTimeoutApplet


class LevelTimeoutAppletTestCase(GlasgowAppletTestCase, applet=LevelTimeoutApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=[])
