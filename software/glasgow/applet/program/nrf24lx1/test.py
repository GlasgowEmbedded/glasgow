from ... import *
from . import ProgramNRF24Lx1Applet

# -------------------------------------------------------------------------------------------------

class ProgramNRF24Lx1AppletTestCase(GlasgowAppletTestCase, applet=ProgramNRF24Lx1Applet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
