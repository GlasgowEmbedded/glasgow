from ... import *
from . import DisplayPDIApplet


class DisplayPDIAppletTestCase(GlasgowAppletTestCase, applet=DisplayPDIApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
