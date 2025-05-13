from ... import *
from . import VideoRGBInputApplet


class VideoRGBInputAppletTestCase(GlasgowAppletTestCase, applet=VideoRGBInputApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--r", "0:4", "--g", "5:9", "--b", "10:14",
                                "--dck", "15", "--columns", "160", "--rows", "144",
                                "--vblank", "960e-6"])
