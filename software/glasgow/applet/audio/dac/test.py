from ... import *
from . import AudioDACApplet


class AudioDACAppletTestCase(GlasgowAppletTestCase, applet=AudioDACApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--unsigned"])
