from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_simulation_test

from . import EthernetRGMIIApplet


class EthernetRGMIIAppletTestCase(GlasgowAppletV2TestCase, applet=EthernetRGMIIApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    def prepare_loopback(self, assembly):
        a0 = assembly.get_pin("A0")
        async def tb_phy_clk(ctx):
            while True:
                ctx.set(a0.i, ~ctx.get(a0.i))
                await ctx.delay(1e-7)
        assembly.add_testbench(tb_phy_clk, background=True)

        assembly.connect_pins("A1", "A7")
        assembly.connect_pins("A2", "B0")
        assembly.connect_pins("A3", "B1")
        assembly.connect_pins("A4", "B2")
        assembly.connect_pins("A5", "B3")

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
