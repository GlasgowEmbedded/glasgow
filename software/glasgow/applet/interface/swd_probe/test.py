from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_simulation_test

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
