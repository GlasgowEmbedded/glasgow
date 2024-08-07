import logging
import asyncio
from amaranth import *
from amaranth.lib import io, stream, wiring

from ... import *


class BoilerplateModule(wiring.Component):
    data: In(8)
    enable: Out(1)

    in_stream: In(stream.Signature(signed(8)))
    out_stream: Out(stream.Signature(signed(8)))
    def elaborate(self, platform):
        m = Module()

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
    #                            │BoilerplateModule│     
    #   ┌────────┐               │                 │    
    #   │out_fifo├───out_stream──►                 │    
    #   └────────┘               └─────▲───────┬───┘    
    #                                  │       │        
    #                                data    enable     
    #                                  │       │        
    #                              ┌───┴───────▼──┐     
    #                              │    Ports     │     
    #                              └──────────────┘     


        m.submodules.boilerplate = boilerplate = BoilerplateModule()

        ## Instantiate IO buffers for pins/ports
        m.submodules.data_buffer = data_buffer = io.Buffer("i", args.port_data)
        m.submodules.enable_buffer = enable_buffer = io.Buffer("o", args.port_enable)

        ## Connect IO buffers to corresponding ports of BoilerplateModule
        wiring.connect(m, boilerplate.data, data_buffer.i)
        wiring.connect(m, boilerplate.enable, enable_buffer.o)

        ## Connect BoilerplateModule.in_stream to BoilerplateSubtarget.out_fifo
        boilerplate.in_stream.payload.eq(self.out_fifo.r_data),
        boilerplate.in_stream.valid.eq(self.out_fifo.r_rdy),
        self.out_fifo.r_en.eq(boilerplate.in_stream.ready),

        ## Connect BoilerplateSubtarget.in_fifo to BoilerplateModule.out_stream
        self.in_fifo.w_data.eq(boilerplate.out_stream.payload),
        self.in_fifo.w_en.eq(boilerplate.out_stream.valid),
        boilerplate.out_stream.ready.eq(self.in_fifo.w_rdy),

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
        access.add_pin_set_argument(parser, "data", width=8, default=True)

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
