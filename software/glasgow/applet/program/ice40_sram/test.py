from ... import *
from . import ProgramICE40SRAMApplet


class ProgramICE40SRAMAppletTestCase(GlasgowAppletTestCase, applet=ProgramICE40SRAMApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--pin-reset", "0", "--pin-done", "1",
                                "--pin-sck",   "2", "--pin-cs",   "3",
                                "--pin-copi",  "4"])
