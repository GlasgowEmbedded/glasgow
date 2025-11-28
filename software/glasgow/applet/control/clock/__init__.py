import logging

from amaranth import *
from amaranth.lib import wiring, io
from amaranth.lib.wiring import In

from glasgow.abstract import AbstractAssembly, GlasgowPin
from glasgow.applet import GlasgowAppletV2


__all__ = ["ClockDriveInterface"]


class ClockDriveComponent(wiring.Component):
    enabled: In(1)
    divisor: In(16)

    def __init__(self, ports):
        self._ports = ports

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.clk_buffer = clk_buffer = io.FFBuffer("o", self._ports.clk)

        m.d.comb += clk_buffer.oe.eq(self.enabled)

        timer = Signal.like(self.divisor)
        with m.If(timer == 0):
            m.d.sync += timer.eq(self.divisor)
            m.d.sync += clk_buffer.o.eq(~clk_buffer.o)
        with m.Else():
            m.d.sync += timer.eq(timer - 1)

        return m


class ClockDriveInterface:
    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
                 clk: GlasgowPin, name: str = "clk"):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        ports = assembly.add_port_group(clk=clk)
        component = assembly.add_submodule(ClockDriveComponent(ports))
        self._enabled = assembly.add_rw_register(component.enabled)
        self._clock = assembly.add_clock_divisor(component.divisor,
            ref_period=assembly.sys_clk_period * 2, name=name)

    async def enable(self, frequency: int) -> int:
        """Enable and configure clock.

        Sets the clock frequency to :py:`frequency` Hz and configures the clock pin as push-pull.
        If the clock pin is already configured as push-pull, then the change in frequency is done
        as follows: the current half-cycle has the old period, and the next half-cycle has
        the new period.

        Returns the actual frequency used, which may be equal or less than :py:`frequency`.
        """
        await self._clock.set_frequency(frequency)
        await self._enabled.set(True)
        return await self._clock.get_frequency()

    async def disable(self):
        """Disable clock.

        Disables the oscillator and configures the clock pin as Hi-Z.
        """
        await self._enabled.set(False)


class ControlClockApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "clock generator"
    description = """
    Generates a 50% duty cycle square wave with a specified frequency by dividing the FPGA system
    clock. Achievable frequencies are integer fractions of 24 MHz (for revC and later).
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "clk", required=True, default=True)

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.clk_iface = ClockDriveInterface(self.logger, self.assembly, clk=args.clk)

    @classmethod
    def add_setup_arguments(cls, parser):
        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=1000,
            help="set clock frequency to FREQ kHz (default: %(default)s)")

    async def setup(self, args):
        await self.clk_iface.enable(args.frequency * 1000)

    async def run(self, args):
        pass # nothing to do

    @classmethod
    def tests(cls):
        from . import test
        return test.ControlClockAppletTestCase
