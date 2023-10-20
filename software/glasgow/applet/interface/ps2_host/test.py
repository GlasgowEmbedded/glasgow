from ... import *
from . import PS2HostApplet


class PS2HostAppletTestCase(GlasgowAppletTestCase, applet=PS2HostApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
