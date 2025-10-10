import logging
import asyncio

from amaranth import *
from amaranth.lib import wiring, io, enum, stream, cdc
from amaranth.lib.wiring import In, Out

from glasgow.abstract import AbstractAssembly, GlasgowPin
from glasgow.applet import GlasgowAppletV2


__all__ = ["SensorHCSR04Component", "SensorHCSR04Interface"]
        

class SensorHCSR04Component(wiring.Component):
    start:   In(1)
    done:     Out(1)
    distance: Out(24)
    
    def __init__(self, ports):
        self._ports = ports

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        trig = Signal()
        echo = Signal()

        m.submodules.trig_buffer = trig_buffer = io.Buffer("o", self._ports.trig)
        m.d.sync += trig_buffer.o.eq(trig)

        m.submodules.echo_buffer = echo_buffer = io.Buffer("i", self._ports.echo)
        m.submodules += cdc.FFSynchronizer(echo_buffer.i, echo)

        pulse_count = Signal(range(480 + 1))
        dist_count  = Signal(24)

        with m.FSM():
            with m.State("Idle"):
                m.d.sync += self.done.eq(0)
                m.d.sync += pulse_count.eq(0)
                m.d.sync += dist_count.eq(0)
                with m.If(self.start):
                    m.next = "Pulse"

            with m.State("Pulse"):
                m.d.comb += trig.eq(1)
                m.d.sync += pulse_count.eq(pulse_count + 1)
                with m.If(pulse_count == 480):
                    m.next = "Wait-Echo"

            with m.State("Wait-Echo"):
                with m.If(echo):
                    m.d.sync += self.done.eq(1)
                    m.next = "Measure-Echo"
            
            with m.State("Measure-Echo"):
                m.d.sync += dist_count.eq(dist_count + 1)
                with m.If(~echo):
                    m.next = "Done"

            with m.State("Done"):
                with m.If(~self.start):
                    m.next = "Idle"
        
        m.d.comb += self.distance.eq(dist_count)

        return m


class SensorHCSR04Interface:
    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
                 trig: GlasgowPin, echo: GlasgowPin):
        self._logger   = logger
        self._level    = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._assembly = assembly

        ports = assembly.add_port_group(trig=trig, echo=echo)
        component = assembly.add_submodule(SensorHCSR04Component(ports))

        self._start = assembly.add_rw_register(component.start)
        self._done = assembly.add_ro_register(component.done)
        self._distance = assembly.add_ro_register(component.distance)

    def _log(self, message: str, *args):
        self._logger.log(self._level, "HC-SR04: " + message, *args)

    async def measure(self) -> float:
        """Measures the time to receiving echo, in microseconds."""
        await self._start.set(1)
        while not await self._done:
            await asyncio.sleep(0.005)
        interval = await self._distance / self._assembly._platform.default_clk_frequency
        await self._start.set(0)
        return interval


class SensorHCSR04Applet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "measure distances with HC-SR04 generic ultrasound sensors"
    description = """
    Measure distances using HC-SR04 generic ultrasound sensors.

    Returns a value in centimeters by default.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "trig", required=True, default=True)
        access.add_pins_argument(parser, "echo", required=True, default=True)

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.hcsr04_iface = SensorHCSR04Interface(self.logger, self.assembly,
                                             trig=args.trig, echo=args.echo)

    @classmethod
    def add_run_arguments(cls, parser):
        parser.add_argument(
            "-I", "--inches", type=bool, default=False,
            help="return inches instead of centimeters")

    async def run(self, args):
        self.hcsr04_iface._log("Applet started")
        while True:
            distance = 0
            for i in range(16): # Supersample
                distance += await self.hcsr04_iface.measure()
            distance /= 16
            distance *= 1_000_000 / 58
            self.hcsr04_iface._log(f"Distance: {distance}")
            await asyncio.sleep(0.1)

    @classmethod
    def tests(cls):
        from . import test
        return test.SensorHCSR04AppletTestCase
