from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test
from glasgow.applet import applet_v2_simulation_test, applet_v2_hardware_test

from . import SWDProbeException, SWDProbeApplet


class SWDProbeAppletTestCase(GlasgowAppletV2TestCase, applet=SWDProbeApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    @applet_v2_simulation_test()
    async def test_read_dpidr_floating(self, applet, ctx):
        try:
            await applet.swd_iface.initialize()
        except SWDProbeException as exn:
            assert exn.kind == SWDProbeException.Kind.Error

    @applet_v2_hardware_test(args="-V 3.3", mock="swd_iface._pipe")
    async def test_loopback_hw(self, applet):
        await applet.swd_iface.initialize()
