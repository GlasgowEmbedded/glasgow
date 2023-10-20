from ... import *
from . import VideoRGBInputApplet


class VideoRGBInputAppletTestCase(GlasgowAppletTestCase, applet=VideoRGBInputApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--pins-r", "0:4", "--pins-g", "5:9", "--pins-b", "10:14",
                                "--pin-dck", "15", "--columns", "160", "--rows", "144",
                                "--vblank", "960e-6"])
