from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_simulation_test

from . import EthernetRMIIApplet


class EthernetRMIIAppletTestCase(GlasgowAppletV2TestCase, applet=EthernetRMIIApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args="--crs-dv B2")

    def prepare_loopback(self, assembly):
        assembly.connect_pins("A0", "A3")
        assembly.connect_pins("A1", "A4")
        assembly.connect_pins("A2", "A5")

    @applet_v2_simulation_test(prepare=prepare_loopback)
    async def test_loopback(self, applet, ctx):
        await applet.eth_iface.send(bytes.fromhex("""
            ffffffffffffccd9ac6b18130806
            0001080006040001ccd9ac6b1813c0a800d6000000000000c0a8007c
        """))
        assert await applet.eth_iface.recv() == bytes.fromhex("""
            ffffffffffffccd9ac6b18130806
            0001080006040001ccd9ac6b1813c0a800d6000000000000c0a8007c
            000000000000000000000000000000000000
        """)
