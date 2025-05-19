import logging

from amaranth import *
from amaranth.lib import wiring, io
from amaranth.sim import Simulator

from glasgow.simulation.assembly import SimulationAssembly
from glasgow.gateware.ports import PortGroup
from glasgow.gateware.stream import StreamFIFO, stream_get, stream_put
from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_simulation_test
from . import QSPIAnalyzerFrontend, QSPIAnalyzerComponent, QSPIAnalyzerInterface, QSPIAnalyzerApplet


logger = logging.getLogger(__name__)


class QSPIAnalyzerAppletTestCase(GlasgowAppletV2TestCase, applet=QSPIAnalyzerApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    def qspi_testbench(self, ports):
        async def testbench(ctx):
            transactions = [
                [0b1010, 0b0101],
                [0b0001, 0b0010, 0b0011, 0b1110],
                [0b1001, 0b1111],
            ]
            for seq in transactions:
                await ctx.delay(3e-7)
                ctx.set(ports.cs.i, 0)
                for io in seq:
                    await ctx.delay(3e-7)
                    ctx.set(ports.sck.i, 0)
                    ctx.set(ports.io.i, io)
                    await ctx.delay(3e-7)
                    ctx.set(ports.sck.i, 1)
                await ctx.delay(3e-7)
                ctx.set(ports.cs.i, 1)
        return testbench

    def test_sim_frontend_quad(self):
        ports = PortGroup()
        ports.cs  = io.SimulationPort("i", 1, name="cs")
        ports.sck = io.SimulationPort("i", 1, name="sck")
        ports.io  = io.SimulationPort("i", 4, name="io")

        dut = QSPIAnalyzerFrontend(ports)

        async def stream_testbench(ctx):
            words = [
                {"data": 0b10100101, "epoch": 0},
                {"data": 0b00010010, "epoch": 1},
                {"data": 0b00111110, "epoch": 1},
                {"data": 0b10011111, "epoch": 0},
            ]
            for word in words:
                self.assertEqual(word, (await stream_get(ctx, dut.stream)))

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(self.qspi_testbench(ports))
        sim.add_testbench(stream_testbench)
        with sim.write_vcd("test_qspi_analyzer_frontend.vcd"):
            sim.run()

    def test_sim_frontend_dual(self):
        ports = PortGroup()
        ports.cs  = io.SimulationPort("i", 1, name="cs")
        ports.sck = io.SimulationPort("i", 1, name="sck")
        ports.io  = io.SimulationPort("i", 2, name="io")

        dut = QSPIAnalyzerFrontend(ports)

        async def stream_testbench(ctx):
            words = [
                {"data": 0b00100001, "epoch": 0},
                {"data": 0b00010010, "epoch": 1},
                {"data": 0b00110010, "epoch": 1},
                {"data": 0b00010011, "epoch": 0},
            ]
            for word in words:
                self.assertEqual(word, (await stream_get(ctx, dut.stream)))

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(self.qspi_testbench(ports))
        sim.add_testbench(stream_testbench)
        with sim.write_vcd("test_qspi_analyzer_frontend.vcd"):
            sim.run()

    def test_sim_interface(self):
        assembly = SimulationAssembly()

        iface = QSPIAnalyzerInterface(logger, assembly, cs="A0", sck="A1", io="A2:5")

        ports = PortGroup()
        ports.cs  = assembly.get_pin("A0")
        ports.sck = assembly.get_pin("A1")
        ports.io  = (
            assembly.get_pin("A2") + assembly.get_pin("A3") +
            assembly.get_pin("A4") + assembly.get_pin("A5")
        )
        assembly.add_testbench(self.qspi_testbench(ports))

        async def iface_testbench(ctx):
            data = [
                bytes([0b10100101]),
                bytes([0b00010010, 0b00111110]),
                bytes([0b10011111]),
            ]
            for expect in data:
                data = await iface.capture()
                self.assertEqual(data, expect)

        assembly.run(iface_testbench, vcd_file="test_qspi_analyzer_interface.vcd")
