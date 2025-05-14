from ... import *
from . import ProgramICE40SRAMApplet


class ProgramICE40SRAMAppletTestCase(GlasgowAppletTestCase, applet=ProgramICE40SRAMApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--reset", "A0", "--done", "A1",
                                "--sck",   "A2", "--cs",   "A3",
                                "--copi",  "A4"])
