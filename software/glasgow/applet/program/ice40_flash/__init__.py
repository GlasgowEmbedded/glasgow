import asyncio
import logging

from glasgow.applet.memory._25x import Memory25xApplet
from glasgow.applet.control.gpio import GPIOInterface


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

        access.add_pins_argument(parser, "reset", default="A6", required=True)
        access.add_pins_argument(parser, "done",  default="A7")

    def build(self, args):
        super().build(args)

        self._reset_iface = GPIOInterface(self.logger, self.assembly, pins=(~args.reset,))
        if args.done is not None:
            self._done_iface = GPIOInterface(self.logger, self.assembly, pins=(args.done,))
        else:
            self._done_iface = None

    async def run(self, args):
        await self._reset_iface.output(0, True)
        await super().run(args)
        await self._reset_iface.output(0, False)

        if self._done_iface is not None:
            for _ in range(10):    # Wait up to 100 ms
                await asyncio.sleep(0.010)  # Poll every 10 ms
                if await self._done_iface.get(0):
                    self.logger.info("FPGA configured from flash")
                    break
            else:
                self.logger.warning("FPGA failed to configure after releasing reset")

    @classmethod
    def tests(cls):
        from . import test
        return test.ProgramICE40FlashAppletTestCase
