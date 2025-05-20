import logging

from amaranth import *

from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_simulation_test, applet_v2_hardware_test
from glasgow.simulation.assembly import SimulationAssembly
from . import UARTApplet, UARTInterface


logger = logging.getLogger(__name__)


class UARTAppletTestCase(GlasgowAppletV2TestCase, applet=UARTApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    def prepare_loopback(self, assembly):
        assembly.connect_pins("A0", "A1")

    @applet_v2_simulation_test(prepare=prepare_loopback, args="--baud 9600")
    async def test_loopback(self, applet, ctx):
        await applet.uart_iface.write(bytes([0xAA, 0x55]))
        self.assertEqual(await applet.uart_iface.read(2), bytes([0xAA, 0x55]))

    # This test is here mainly to test the test machinery.
    @applet_v2_hardware_test(args="-V 3.3 --baud 9600", mock="uart_iface")
    async def test_loopback_hw(self, applet):
        await applet.uart_iface.write(bytes([0xAA, 0x55]))
        self.assertEqual(await applet.uart_iface.read(2), bytes([0xAA, 0x55]))

    def test_multiple_interfaces(self):
        assembly  = SimulationAssembly()
        iface0    = UARTInterface(logger, assembly, rx="A0", tx="A1", parity="none")
        iface1    = UARTInterface(logger, assembly, rx="B0", tx="B1", parity="none")

        assembly.connect_pins("A0", "B1")
        assembly.connect_pins("B0", "A1")

        async def write_testbench(ctx):
            await iface0.set_baud(9600)
            await iface1.set_baud(9600)
            await iface0.write(b'Hello')

        async def read_testbench(ctx):
            self.assertEqual(await iface1.read(5), b'Hello')

        assembly.add_testbench(write_testbench)
        assembly.run(read_testbench, vcd_file="uart_multi.vcd")
