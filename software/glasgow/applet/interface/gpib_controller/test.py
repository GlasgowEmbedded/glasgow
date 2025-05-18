import logging

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


    def test_two_can_talk(self):
        assembly  = SimulationAssembly()
        iface0    = GPIBControllerInterface(logger, assembly,
                        dio="A0:7", eoi="B0", dav="B1", nrfd="B2", ndac="B3", srq="B4", ifc="B5", atn="B6", ren="B7")

        iface1    = GPIBControllerInterface(logger, assembly,
                        dio="A0:7", eoi="B0", dav="B1", nrfd="B2", ndac="B3", srq="B4", ifc="B5", atn="B6", ren="B7")

       async def do_it(ctx):
            x = iface1.read_from(10)
            await iface0.send_to(10, b'*IDN?')
            print(await x)

        assembly.run(do_it, vcd_file="test.vcd")
