import types
from amaranth import *

from ... import *
from . import SPIControllerApplet


class SPIControllerAppletTestCase(GlasgowAppletTestCase, applet=SPIControllerApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--pin-sck",  "0", "--pin-cs",   "1",
                                "--pin-copi", "2", "--pin-cipo", "3"])

    def setup_loopback(self):
        self.build_simulated_applet()
        mux_iface = self.applet.mux_interface
        m = Module()
        m.d.comb += mux_iface.pads.cipo_t.i.eq(mux_iface.pads.copi_t.o)
        self.target.add_submodule(m)

    @applet_simulation_test("setup_loopback",
                            ["--pin-sck",  "0", "--pin-cs", "1",
                             "--pin-copi", "2", "--pin-cipo",   "3",
                             "--frequency", "5000"])
    @types.coroutine
    def test_loopback(self):
        mux_iface = self.applet.mux_interface
        spi_iface = yield from self.run_simulated_applet()

        self.assertEqual((yield mux_iface.pads.cs_t.o), 1)
        result = yield from spi_iface.transfer([0xAA, 0x55, 0x12, 0x34])
        self.assertEqual(result, bytearray([0xAA, 0x55, 0x12, 0x34]))
        self.assertEqual((yield mux_iface.pads.cs_t.o), 1)
