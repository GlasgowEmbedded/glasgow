import logging
import asyncio

from amaranth import *

from ... import *

from glasgow.simulation.assembly import SimulationAssembly
from glasgow.gateware.ports import PortGroup
from . import GPIBControllerApplet, GPIBControllerInterface, GPIBStatus, GPIBMessage


logger = logging.getLogger(__name__)

class GPIBControllerAppletTestCase(GlasgowAppletV2TestCase, applet=GPIBControllerApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    def send_a_message(self, iface):
        async def testbench(ctx):
            print("hello from testbench")
            # await iface.send_to(10, b'I')
            await iface.write(GPIBMessage.Data, b'I')
            # await iface.write(GPIBMessage.Data, b'O')
            print("message sent")
        return testbench

    def test_two_can_talk(self):
        assembly  = SimulationAssembly()
        iface0    = GPIBControllerInterface(logger, assembly,
                                            dio="A0:7", eoi="A8", dav="A9", nrfd="A10", ndac="A11", srq="A12", ifc="A13", atn="A14", ren="A15")
        iface1    = GPIBControllerInterface(logger, assembly,
                                            dio="B0:7", eoi="B8", dav="B9", nrfd="B10", ndac="B11", srq="B12", ifc="B13", atn="B14", ren="B15")

        # We skip IFC, ATN and REN, since they're always under the
        # control of the controller, and we're pretending one of the
        # controller isn't a controller....
        for pin in range(0,13):
            assembly.connect_pins("A%i" % pin, "B%i" % pin)

        assembly.add_testbench(self.send_a_message(iface0))

        async def do_it(ctx):
            import time
            time.sleep(0.1)
            while True:
                response = b''
                async for data in iface1.read(to_eoi=True):
                    response += data
                    # print(data)
                    # print("Talker:", GPIBStatus(await iface0._status.get()))
                    # print("Listener:", GPIBStatus(await iface1._status.get()))


        assembly.run(do_it, vcd_file="test.vcd")
