import types
from amaranth import *
from amaranth.lib import io

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
        ports = mux_iface._subtargets[0].ports
        m = Module()
        m.d.comb += ports.cipo.i.eq(ports.copi.o)
        self.target.add_submodule(m)

    @applet_simulation_test("setup_loopback",
                            ["--pin-sck",  "0", "--pin-cs", "1",
                             "--pin-copi", "2", "--pin-cipo",   "3",
                             "--frequency", "5000"])
    @types.coroutine
    def test_loopback(self):
        mux_iface = self.applet.mux_interface
        spi_iface = yield from self.run_simulated_applet()

        ports = mux_iface._subtargets[0].ports
        self.assertEqual((yield ports.cs.o), 1)
        select_cm = spi_iface.select()
        yield from select_cm.__aenter__() # no `async with` in applet simulation tests :(
        yield; yield;
        self.assertEqual((yield ports.cs.o), 0)
        result = yield from spi_iface.exchange([0xAA, 0x55, 0x12, 0x34])
        self.assertEqual(result, bytearray([0xAA, 0x55, 0x12, 0x34]))
        yield from select_cm.__aexit__(None, None, None)
        yield; yield;
        self.assertEqual((yield ports.cs.o), 1)
