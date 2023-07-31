import asyncio
import logging
from amaranth import *

from ...memory._25x import Memory25xInterface, Memory25xApplet
from ... import *


class ProgramICE40FlashSubtarget(Elaboratable):
    def __init__(self, lower, reset_t, dut_reset, done_t, dut_done):
        self.lower = lower
        self.reset_t = reset_t
        self.dut_reset = dut_reset
        self.done_t = done_t
        self.dut_done = dut_done

    def elaborate(self, platform):
        m = Module()

        m.submodules.lower = self.lower

        if self.reset_t is not None:
            m.d.comb += [
                self.reset_t.o.eq(0),
                self.reset_t.oe.eq(self.dut_reset),
            ]

        if self.done_t is not None:
            m.d.comb += self.dut_done.eq(self.done_t.i)

        return m


class ProgramICE40FlashInterface:
    def __init__(self, interface, logger, device, addr_dut_reset, addr_dut_done):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._device = device
        self._addr_dut_reset = addr_dut_reset
        self._addr_dut_done  = addr_dut_done

    async def set_reset(self, reset):
        if self._addr_dut_reset is not None:
            await self._device.write_register(self._addr_dut_reset, int(reset))

    async def get_done(self):
        if self._addr_dut_reset is not None:
            return await self._device.read_register(self._addr_dut_done)


class ProgramICE40FlashApplet(Memory25xApplet):
    logger = logging.getLogger(__name__)
    help = "program 25-series Flash memories used with iCE40 FPGAs"
    description = """
    Program the 25-series Flash memories found on many boards with iCE40 FPGAs. This applet is
    based on the memory-25x applet; in addition, it asserts the FPGA reset while programming
    the memory, and checks the CDONE pin to determine whether the FPGA has successfully read
    the configuration after the applet finishes.

    See the description of the memory-25x applet for details.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_argument(parser, "reset")
        access.add_pin_argument(parser, "done")

    def build_subtarget(self, target, args):
        subtarget = super().build_subtarget(target, args)

        if args.pin_reset is not None:
            reset_t = self.mux_interface.get_pin(args.pin_reset)
            dut_reset, self.__addr_dut_reset = target.registers.add_rw(1)
        else:
            reset_t = None
            dut_reset = None
            self.__addr_dut_reset = None

        if args.pin_done is not None:
            done_t = self.mux_interface.get_pin(args.pin_done)
            dut_done, self.__addr_dut_done = target.registers.add_ro(1)
        else:
            done_t = None
            dut_done = None
            self.__addr_dut_done = None

        return ProgramICE40FlashSubtarget(subtarget, reset_t, dut_reset, done_t, dut_done)

    async def run(self, device, args):
        m25x_iface = await super().run(device, args)
        return ProgramICE40FlashInterface(m25x_iface, self.logger, device,
                                          self.__addr_dut_reset, self.__addr_dut_done)

    async def interact(self, device, args, ice40_iface):
        await ice40_iface.set_reset(True)
        await super().interact(device, args, ice40_iface.lower)
        await ice40_iface.set_reset(False)

        if args.pin_done is not None:
            for _ in range(200):    # Wait up to 2s
                await asyncio.sleep(0.010)  # Poll every 10 ms
                done = await ice40_iface.get_done()
                if done:
                    break
            if done:
                self.logger.info("FPGA configured from flash")
            else:
                self.logger.warning("FPGA failed to configure after releasing reset")

# -------------------------------------------------------------------------------------------------

class ProgramICE40FlashAppletTestCase(GlasgowAppletTestCase, applet=ProgramICE40FlashApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
