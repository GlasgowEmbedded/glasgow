from ... import *
from . import VideoRGBInputApplet


class VideoRGBInputAppletTestCase(GlasgowAppletTestCase, applet=VideoRGBInputApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--r", "A0:4", "--g", "A5:7,B0:1", "--b", "B2:6",
                                "--dck", "B7", "--columns", "160", "--rows", "144",
                                "--vblank", "960e-6"])
