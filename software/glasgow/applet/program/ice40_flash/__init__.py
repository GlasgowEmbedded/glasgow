import asyncio

from amaranth.lib.io import PortLike

from glasgow.support import logging
from glasgow.abstract import GlasgowPin, glasgow_ports
from glasgow.applet.memory._25q import Memory25QPorts, Memory25QApplet
from glasgow.applet.control.gpio import GPIOInterface


__all__ = ["ProgramICE40FlashApplet"]


@glasgow_ports
class ProgramICE40FlashPorts(Memory25QPorts):
    # A field without a default is not left as an attribute of the class, so the supply of
    # the base class has to be looked up in its fields.
    reset: PortLike = GlasgowPin.field(default="A6", invert=True,
        power=Memory25QPorts.__dataclass_fields__["supply"])
    """FPGA reset (active low)"""
    done: PortLike | None = GlasgowPin.field(default="A7",
        power=Memory25QPorts.__dataclass_fields__["supply"])
    """FPGA configuration done"""


class ProgramICE40FlashApplet(Memory25QApplet):
    logger = logging.getLogger(__name__)
    help = "program 25-series SPI NOR Flash memories used with iCE40 FPGAs"
    description = """
    Program the 25-series SPI NOR Flash memories found on many boards with iCE40 FPGAs. This applet
    is based on the `memory-25q` applet; in addition, it asserts the FPGA reset while programming
    the memory, and checks the CDONE pin to determine whether the FPGA has successfully read
    the configuration after the applet finishes.

    See the description of the `memory-25q` applet for details.
    """

    ports_cls = ProgramICE40FlashPorts

    def build(self, args):
        super().build(args)

        with self.assembly.add_applet(self):
            self._reset_iface = GPIOInterface(self.logger, self.assembly, self.ports.reset)
            if self.ports.done is not None:
                self._done_iface = GPIOInterface(self.logger, self.assembly, self.ports.done)
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
