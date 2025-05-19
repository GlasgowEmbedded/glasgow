import asyncio
import logging
from amaranth import *
from amaranth.lib import wiring, io
from amaranth.lib.wiring import In, Out

from ...memory._25x import Memory25xApplet
from ... import *


class ProgramICE40FlashComponent(wiring.Component):
    reset: In(1)
    done:  Out(1)

    def __init__(self, ports):
        self._ports = ports

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        if self._ports.reset is not None:
            m.submodules.reset_buffer = reset = io.Buffer("o", self._ports.reset)
            m.d.comb += reset.oe.eq(self.reset)

        if self._ports.done is not None:
            m.submodules.done_buffer = done = io.Buffer("i", self._ports.done)
            m.d.comb += self.done.eq(done.i)

        return m


class ProgramICE40FlashApplet(Memory25xApplet):
    logger = logging.getLogger(__name__)
    help = "program 25-series Flash memories used with iCE40 FPGAs"
    description = """
    Program the 25-series Flash memories found on many boards with iCE40 FPGAs. This applet is
    based on the `memory-25x` applet; in addition, it asserts the FPGA reset while programming
    the memory, and checks the CDONE pin to determine whether the FPGA has successfully read
    the configuration after the applet finishes.

    See the description of the `memory-25x` applet for details.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pins_argument(parser, "reset")
        access.add_pins_argument(parser, "done")

    def build(self, args):
        super().build(args)

        ports = self.assembly.add_port_group(reset=args.reset, done=args.done)
        component = self.assembly.add_submodule(ProgramICE40FlashComponent(ports))
        self.__reset = self.assembly.add_rw_register(component.reset)
        self.__done = self.assembly.add_ro_register(component.done)

    async def run(self, args):
        await self.__reset.set(True)
        await super().run(args)
        await self.__reset.set(False)

        if args.done is not None:
            for _ in range(200):    # Wait up to 2s
                await asyncio.sleep(0.010)  # Poll every 10 ms
                if await self.__done:
                    self.logger.info("FPGA configured from flash")
                    break
            else:
                self.logger.warning("FPGA failed to configure after releasing reset")

    @classmethod
    def tests(cls):
        from . import test
        return test.ProgramICE40FlashAppletTestCase
