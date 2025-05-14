# This file can be copied into `.../glasgow/software/glasgow/applet/<group>/<name.py>`.
# Afterwards, `pyproject.toml` should be adjusted to make the new applet available via the CLI.

import logging
import asyncio
from amaranth import *
from amaranth.lib import enum, data, wiring, io
from amaranth.lib.wiring import In, Out

from .. import *


class BoilerplateSubtarget(Elaboratable):
    def __init__(self, ports, in_fifo, out_fifo):
        self.ports    = ports

        self.in_fifo  = in_fifo
        self.out_fifo = out_fifo

    def elaborate(self, platform):
        m = Module()

        m.submodules.clk_buffer  = clk_buffer  = io.Buffer("o",  self.ports.clk)
        m.submodules.data_buffer = data_buffer = io.Buffer("io", self.ports.data)

        # ... FPGA-side implementation goes here, for example:

        m.d.comb += [
            self.in_fifo.w_data.eq(~self.out_fifo.r_data),
            self.in_fifo.w_en.eq(self.out_fifo.r_rdy),
            self.out_fifo.r_en.eq(self.in_fifo.w_rdy),
        ]

        return m


class BoilerplateInterface:
    def __init__(self, interface, logger):
        self._lower  = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

    def _log(self, message, *args):
        self._logger.log(self._level, "boilerplate: " + message, *args)

    # ... host-side implementation goes here, for example:

    async def do_something(self):
        self._log("doing something")
        await self._lower.write([0xa9])
        return await self._lower.read(1)


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

    __pins = ()

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pins_argument(parser, "clk", default=True)
        access.add_pins_argument(parser, "data", width=4, default=True)

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        iface.add_subtarget(BoilerplateSubtarget(
            ports=iface.get_port_group(
                clk  = args.clk,
                data = args.data,
            ),
            in_fifo=iface.get_in_fifo(),
            out_fifo=iface.get_out_fifo(),
        ))

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        return BoilerplateInterface(iface, self.logger)

    @classmethod
    def add_interact_arguments(cls, parser):
        pass

    async def interact(self, device, args, iface):
        result = await iface.do_something()
        print(f"did something: {result.hex()}")


# -------------------------------------------------------------------------------------------------

class BoilerplateAppletTestCase(GlasgowAppletTestCase, applet=BoilerplateApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
