from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test

from . import VideoHub75OutputApplet


class VideoHub75OutputAppletTestCase(GlasgowAppletV2TestCase, applet=VideoHub75OutputApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
