from ... import *
from . import VideoWS2812OutputApplet


class VideoWS2812OutputAppletTestCase(GlasgowAppletTestCase, applet=VideoWS2812OutputApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--out", "A0:3", "-c", "1024"])
