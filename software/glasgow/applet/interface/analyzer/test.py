from ... import *
from . import AnalyzerApplet


class AnalyzerAppletTestCase(GlasgowAppletTestCase, applet=AnalyzerApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
