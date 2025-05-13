from ... import *
from . import ProgramICE40SRAMApplet


class ProgramICE40SRAMAppletTestCase(GlasgowAppletTestCase, applet=ProgramICE40SRAMApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--reset", "0", "--done", "1",
                                "--sck",   "2", "--cs",   "3",
                                "--copi",  "4"])
