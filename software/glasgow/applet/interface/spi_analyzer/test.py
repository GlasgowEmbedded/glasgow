import logging

from amaranth import *
from amaranth.lib import wiring, io
from amaranth.sim import Simulator

from glasgow.simulation.assembly import SimulationAssembly
from glasgow.gateware.ports import PortGroup
from glasgow.gateware.stream import StreamFIFO, stream_get, stream_put
from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_simulation_test
from . import SPIAnalyzerFrontend, SPIAnalyzerComponent, SPIAnalyzerInterface, SPIAnalyzerApplet


logger = logging.getLogger(__name__)


class SPIAnalyzerAppletTestCase(GlasgowAppletV2TestCase, applet=SPIAnalyzerApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    def spi_testbench(self, ports):
        async def testbench(ctx):
            transactions = [
                ([0,1,1,0,0,0,0,1],                  [1,1,1,1,0,0,1,1]),
                ([0,0,0,0,0,0,0,1, 0,0,0,0,0,0,1,0], [0,0,0,0,0,0,1,1, 0,0,0,0,0,1,0,0]),
                ([0,0,0,1,0,0,0,0],                  [0,0,0,1,0,0,0,0]),
            ]
            for copi_seq, cipo_seq in transactions:
                await ctx.delay(3e-7)
                ctx.set(ports.cs.i, 0)
                for copi, cipo in zip(copi_seq, cipo_seq):
                    await ctx.delay(3e-7)
                    ctx.set(ports.sck.i, 0)
                    ctx.set(ports.copi.i, copi)
                    ctx.set(ports.cipo.i, cipo)
                    await ctx.delay(3e-7)
                    ctx.set(ports.sck.i, 1)
                await ctx.delay(3e-7)
                ctx.set(ports.cs.i, 1)
        return testbench

    def test_sim_frontend(self):
        ports = PortGroup()
        ports.cs   = io.SimulationPort("i", 1, name="cs")
        ports.sck  = io.SimulationPort("i", 1, name="sck")
        ports.copi = io.SimulationPort("i", 1, name="copi")
        ports.cipo = io.SimulationPort("i", 1, name="cipo")

        dut = SPIAnalyzerFrontend(ports)

        async def stream_testbench(ctx):
            words = [
                {"chip": 0, "copi": 0b01100001, "cipo": 0b11110011, "start": 1},
                {"chip": 0, "copi": 0b00000001, "cipo": 0b00000011, "start": 1},
                {"chip": 0, "copi": 0b00000010, "cipo": 0b00000100, "start": 0},
                {"chip": 0, "copi": 0b00010000, "cipo": 0b00010000, "start": 1},
            ]
            for word in words:
                self.assertEqual(word, (await stream_get(ctx, dut.stream)))

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(self.spi_testbench(ports))
        sim.add_testbench(stream_testbench)
        with sim.write_vcd("test_spi_analyzer_frontend.vcd"):
            sim.run()

    def test_sim_interface(self):
        assembly = SimulationAssembly()

        iface = SPIAnalyzerInterface(logger, assembly, cs="A0", sck="A1", copi="A2", cipo="A3")

        ports = PortGroup()
        ports.cs   = assembly.get_pin("A0")
        ports.sck  = assembly.get_pin("A1")
        ports.copi = assembly.get_pin("A2")
        ports.cipo = assembly.get_pin("A3")
        assembly.add_testbench(self.spi_testbench(ports))

        async def iface_testbench(ctx):
            data = [
                (bytes([0b01100001]),             bytes([0b11110011])),
                (bytes([0b00000001, 0b00000010]), bytes([0b00000011, 0b00000100])),
                (bytes([0b00010000]),             bytes([0b00010000])),
            ]
            for copi_expect, cipo_expect in data:
                chip, copi_data, cipo_data = await iface.capture()
                self.assertEqual(chip, 0)
                self.assertEqual(copi_data, copi_expect)
                self.assertEqual(cipo_data, cipo_expect)

        assembly.run(iface_testbench, vcd_file="test_spi_analyzer_interface.vcd")
