from ... import *
from . import SpyBiWireProbeApplet


class SpyBiWireProbeAppletTestCase(GlasgowAppletTestCase, applet=SpyBiWireProbeApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
