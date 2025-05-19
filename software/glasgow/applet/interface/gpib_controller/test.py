import logging
import asyncio
import time

from amaranth import *

from ... import *

from glasgow.simulation.assembly import SimulationAssembly
from glasgow.gateware.ports import PortGroup
from . import GPIBControllerApplet, GPIBControllerInterface

logger = logging.getLogger(__name__)

class GPIBControllerAppletTestCase(GlasgowAppletV2TestCase, applet=GPIBControllerApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()


    # def talk_and_listen(self, iface):
    #     async def testbench(ctx):
    #         print(ctx)
    #         await iface.send_to(10, b'*IDN?')
    #         await iface.read_from(10)
    #     return testbench

    def listen_and_reply(self, iface):
        async def testbench(ctx):
            time.sleep(0.5)
            print(await iface.read_from(10))
            await iface.send_to(10, b'GLASGOW DIGITAL INTERFACE EXPLORER')
        return testbench



    def test_two_can_talk(self):
        assembly  = SimulationAssembly()
        iface0    = GPIBControllerInterface(logger, assembly,
                        dio="A0:7", eoi="A8", dav="A9", nrfd="A10", ndac="A11", srq="A12", ifc="A13", atn="A14", ren="A15")

        iface1    = GPIBControllerInterface(logger, assembly,
                        dio="B0:7", eoi="B8", dav="B9", nrfd="B10", ndac="B11", srq="B12", ifc="B13", atn="B14", ren="B15")

        for pin in range(0,16):
            assembly.connect_pins("A%i" % pin, "B%i" % pin)

        # assembly.add_testbench(self.talk_and_listen(iface0))
        assembly.add_testbench(self.listen_and_reply(iface1))

        async def do_it(ctx):
            await iface0.send_to(10, b'*IDN?')
            await iface0.read_from(10)

        assembly.run(do_it, vcd_file="test.vcd")
