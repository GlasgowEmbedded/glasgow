from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test

from . import AUDApplet


class AUDAppletTestCase(GlasgowAppletV2TestCase, applet=AUDApplet):
    hardware_args = "-V 5 --audata A0:3 --audsync A4 --audck A5 --audmd A6 --audrst A7 --address 0xfff98000 --size 0x8000 --output dump_fff98000.bin"

    @synthesis_test
    def test_build(self):
        self.assertBuilds(self.hardware_args)
