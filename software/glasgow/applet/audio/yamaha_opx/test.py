from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test
from . import AudioYamahaOPxApplet


class AudioYamahaOPxAppletTestCase(GlasgowAppletV2TestCase, applet=AudioYamahaOPxApplet):
    @synthesis_test
    def test_build_opl2(self):
        self.assertBuilds(args=["--device", "OPL2"])

    @synthesis_test
    def test_build_opl3(self):
        self.assertBuilds(args=["--device", "OPL3"])

    @synthesis_test
    def test_build_opm(self):
        self.assertBuilds(args=["--device", "OPM"])

    @synthesis_test
    def test_build_opl(self):
        self.assertBuilds(args=["--device", "OPL", "--a", "B0"])

    @synthesis_test
    def test_build_optional_pins(self):
        self.assertBuilds(args=["--device", "OPL3", "--cs", "LED0", "--ic", "LED1"], revision="C0")
