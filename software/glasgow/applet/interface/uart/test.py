from amaranth import *

from ... import *
from . import UARTApplet


class UARTAppletTestCase(GlasgowAppletTestCase, applet=UARTApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    def setup_loopback(self):
        self.build_simulated_applet()
        mux_iface = self.applet.mux_interface
        m = Module()
        ports = mux_iface.subtarget.ports
        m.d.comb += ports.rx.i.eq(ports.tx.o)
        self.target.add_submodule(m)

    @applet_simulation_test("setup_loopback", ["--keep-voltage", "--baud", "5000000"])
    async def test_loopback(self):
        uart_iface = await self.run_simulated_applet()
        await uart_iface.write(bytes([0xAA, 0x55]))
        self.assertEqual(await uart_iface.read(2), bytes([0xAA, 0x55]))
