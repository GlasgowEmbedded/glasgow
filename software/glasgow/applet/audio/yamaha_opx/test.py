from ... import *
from . import AudioYamahaOPxApplet


class AudioYamahaOPxAppletTestCase(GlasgowAppletTestCase, applet=AudioYamahaOPxApplet):
    @synthesis_test
    def test_build_opl2(self):
        self.assertBuilds(args=["--device", "OPL2"])

    @synthesis_test
    def test_build_opl3(self):
        self.assertBuilds(args=["--device", "OPL3"])

    @synthesis_test
    def test_build_opm(self):
        self.assertBuilds(args=["--device", "OPM"])
