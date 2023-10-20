from ... import *
from . import VideoHub75OutputApplet


class VideoHub75OutputAppletTestCase(GlasgowAppletTestCase, applet=VideoHub75OutputApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
