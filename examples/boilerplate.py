# The first part of this file must be copied into:
#    .../glasgow/software/glasgow/applet/<group>/<name>/__init__.py
# Afterwards, `pyproject.toml` should be adjusted to make the new applet available via the CLI.

import logging
import asyncio

from amaranth import *
from amaranth.lib import enum, data, wiring, stream, io
from amaranth.lib.wiring import In, Out

from glasgow.applet import GlasgowAppletV2


class BoilerplateComponent(wiring.Component):
    i_stream: In(stream.Signature(8))
    o_stream: Out(stream.Signature(8))

    loopback_en: In(1)

    def __init__(self, ports):
        self.ports = ports

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.clk_buffer  = clk_buffer  = io.Buffer("o",  self.ports.clk)
        m.submodules.data_buffer = data_buffer = io.Buffer("io", self.ports.data)

        # ... FPGA-side implementation goes here, for example:

        with m.If(self.loopback_en):
            wiring.connect(m, wiring.flipped(self.i_stream), wiring.flipped(self.o_stream))

        return m


class BoilerplateInterface:
    def __init__(self, logger, assembly, *, clk, data):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        ports = assembly.add_port_group(clk=clk, data=data)
        component = assembly.add_submodule(BoilerplateComponent(ports))
        self._pipe = assembly.add_inout_pipe(component.o_stream, component.i_stream)
        self._loopback_en = assembly.add_rw_register(component.loopback_en)

    def _log(self, message, *args):
        self._logger.log(self._level, "boilerplate: " + message, *args)

    # ... host-side implementation goes here, for example:

    async def enable_loopback(self):
        self._log("enabling loopback")
        await self._loopback_en.set(1)

    async def do_something(self):
        self._log("doing something")
        await self._pipe.send([0xa9])
        await self._pipe.flush()
        return await self._pipe.recv(1)


class BoilerplateApplet(GlasgowAppletV2):
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
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "clk", default=True)
        access.add_pins_argument(parser, "data", width=4, default=True)

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.boilerplate_iface = BoilerplateInterface(self.logger, self.assembly,
                clk=args.clk, data=args.data)

    @classmethod
    def add_setup_arguments(cls, parser):
        pass

    async def setup(self, args):
        await self.boilerplate_iface.enable_loopback()

    @classmethod
    def add_run_arguments(cls, parser):
        pass

    async def run(self, args):
        result = await self.boilerplate_iface.do_something()
        print(f"did something: {result.hex()}")

    @classmethod
    def tests(cls):
        from . import test
        return test.BoilerplateAppletTestCase

# -------------------------------------------------------------------------------------------------

# The second part of the file must be copied into:
#    .../glasgow/software/glasgow/applet/<group>/<name>/test.py

from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_simulation_test

from . import BoilerplateApplet


class BoilerplateAppletTestCase(GlasgowAppletV2TestCase, applet=BoilerplateApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    @applet_v2_simulation_test()
    async def test_loopback(self, applet, ctx):
        result = await applet.boilerplate_iface.do_something()
        self.assertEqual(result, b"\xa9")
