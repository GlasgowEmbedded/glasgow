import logging
import asyncio
from amaranth import *
from amaranth.lib import io, stream, wiring

from ... import *


class BoilerplateCore(wiring.Component):
    in_stream: In(stream.Signature(8))
    out_stream: Out(stream.Signature(8))
    def __init__(self, ports):
        self.ports = ports
    def elaborate(self, platform):
        m = Module()

        ## Instantiate IO buffers for pins/ports
        m.submodules.data_buffer   = data_buffer   = io.Buffer("i", self.ports.data)
        m.submodules.enable_buffer = enable_buffer = io.Buffer("o", self.ports.enable)

        ## Connect IO buffers to corresponding internal signals
        data   = Signal.like(data_buffer)
        enable = Signal.like(enable_buffer)
        wiring.connect(m, data, data_buffer.i)
        wiring.connect(m, enable, enable_buffer.o)

        return m

class BoilerplateSubtarget(wiring.Component):
    def __init__(self, ports, in_fifo, out_fifo):
        self.ports    = ports
        self.in_fifo  = in_fifo
        self.out_fifo = out_fifo

    def elaborate(self, platform):
        m = Module()

    #    ┌───────┐               ┌─────────────────┐    
    #    │in_fifo◄───in_stream───┤                 │    
    #    └───────┘               │                 │     
    #                            │      Core       │     
    #   ┌────────┐               │                 │    
    #   │out_fifo├───out_stream──►                 │    
    #   └────────┘               └─────▲───────┬───┘    
    #                                  │       │        
    #                                data    enable     
    #                                  │       │        
    #                              ┌───┴───────▼──┐     
    #                              │    Ports     │     
    #                              └──────────────┘     


        m.submodules.core = core = BoilerplateCore(self.ports)

        ## Connect BoilerplateCore.in_stream to BoilerplateSubtarget.out_fifo
        wiring.connect(m, self.out_fifo.stream, core.in_stream)
        ## Connect BoilerplateSubtarget.in_fifo to BoilerplateCore.out_stream
        wiring.connect(m, self.in_fifo.stream, core.out_stream)

        return m


class BoilerplateApplet(GlasgowApplet):
    logger = logging.getLogger(__name__)
    help = "boilerplate applet"
    preview = True
    description = """
    An example of the boilerplate code required to implement a minimal Glasgow applet.

    The only things necessary for an applet are:
        * a subtarget class,
        * an applet class,
        * the `build` and `run` methods of the applet class.

    Everything else can be omitted and would be replaced by a placeholder implementation that does
    nothing. Similarly, there is no requirement to use IN or OUT FIFOs, or any pins at all.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_argument(parser, "enable", default=True)
        access.add_pin_set_argument(parser, "data", width=range(8,16+1), default=True)

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        iface.add_subtarget(BoilerplateSubtarget(
            ports=iface.get_port_group(
                enable = args.pin_enable,
                data = args.pin_set_data
            ),
            in_fifo=iface.get_in_fifo(),
            out_fifo=iface.get_out_fifo(),
        ))

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)

    async def run(self, device, args):
        return await device.demultiplexer.claim_interface(self, self.mux_interface, args)

    @classmethod
    def add_interact_arguments(cls, parser):
        pass

    async def interact(self, device, args, iface):
        pass

# -------------------------------------------------------------------------------------------------

class BoilerplateAppletTestCase(GlasgowAppletTestCase, applet=BoilerplateApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
