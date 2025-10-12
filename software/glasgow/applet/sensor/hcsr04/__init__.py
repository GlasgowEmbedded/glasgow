# Ref: Sparkfun HCSR04 (https://cdn.sparkfun.com/datasheets/Sensors/Proximity/HCSR04.pdf)
# Accession: G00107

import logging
import asyncio

from amaranth import *
from amaranth.lib import wiring, io, cdc
from amaranth.lib.wiring import In, Out

from glasgow.abstract import AbstractAssembly, GlasgowPin
from glasgow.applet import GlasgowAppletV2, GlasgowAppletError
from glasgow.support.data_logger import DataLogger


__all__ = ["SensorHCSR04Error", "SensorHCSR04Component", "SensorHCSR04Interface"]


class SensorHCSR04Error(GlasgowAppletError):
    pass


class SensorHCSR04Component(wiring.Component):
    start:        In(1)
    supersample:  In(3)
    done:         Out(1)
    distance:     Out(32)

    def __init__(self, ports, us_cycles):
        self._ports     = ports
        self._us_cycles = us_cycles

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        trig = Signal()
        echo = Signal()

        m.submodules.trig_buffer = trig_buffer = io.Buffer("o", self._ports.trig)
        m.d.sync += trig_buffer.o.eq(trig)

        m.submodules.echo_buffer = echo_buffer = io.Buffer("i", self._ports.echo)
        m.submodules += cdc.FFSynchronizer(echo_buffer.i, echo)

        pulse_cycles = 10 * self._us_cycles
        pulse_delay = Signal(range(pulse_cycles + 1), init=pulse_cycles)

        dist_accum  = Signal(24 + len(1 << self.supersample))
        sample_count = Signal(1 << len(self.supersample))

        with m.FSM():
            with m.State("Idle"):
                m.d.sync += dist_accum.eq(0)
                m.d.sync += sample_count.eq(0)
                with m.If(self.start):
                    m.next = "Pulse"

            with m.State("Pulse"):
                m.d.comb += trig.eq(1)
                with m.If(pulse_delay == 0):
                    m.d.sync += pulse_delay.eq(pulse_delay.init)
                    m.next = "Wait-Echo"
                with m.Else():
                    m.d.sync += pulse_delay.eq(pulse_delay - 1)

            with m.State("Wait-Echo"):
                with m.If(echo):
                    m.next = "Measure-Echo"
                with m.If(~self.start):
                    m.next = "Idle"

            with m.State("Measure-Echo"):
                m.d.sync += dist_accum.eq(dist_accum + 1)
                with m.If(~echo):
                    m.d.sync += sample_count.eq(sample_count + 1)
                    with m.If(sample_count + 1 == (1 << self.supersample)):
                        m.next = "Normalize"
                    with m.Else():
                        m.next = "Pulse"

            with m.State("Normalize"):
                with m.If(sample_count != 1):
                    m.d.sync += dist_accum.eq(dist_accum >> 1)
                    m.d.sync += sample_count.eq(sample_count >> 1)
                with m.Else():
                    m.next = "Done"

            with m.State("Done"):
                m.d.comb += self.done.eq(1)
                with m.If(~self.start):
                    m.next = "Idle"

        m.d.comb += self.distance.eq(dist_accum)

        return m


class SensorHCSR04Interface:
    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
                 trig: GlasgowPin, echo: GlasgowPin):
        self._logger   = logger
        self._level    = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._assembly = assembly

        ports = assembly.add_port_group(trig=trig, echo=echo)
        component = assembly.add_submodule(SensorHCSR04Component(ports,
            us_cycles=round(1e-6 / assembly.sys_clk_period)))

        self._start = assembly.add_rw_register(component.start)
        self._supersample = assembly.add_rw_register(component.supersample)
        self._done = assembly.add_ro_register(component.done)
        self._distance = assembly.add_ro_register(component.distance)

    def _log(self, message: str, *args):
        self._logger.log(self._level, "HC-SR04: " + message, *args)

    async def measure_time(self, supersample: int) -> float:
        """Measures the time it takes for sound to travel to the object, in seconds.

        :py:`supersample` represents the number of samples to take for supersampling,
        as 2^samples. For example, if you want to take 8 samples, set this parameter to 3.
        A value of 0 means no supersampling. Maximum value is 7.
        """
        assert 0 <= supersample <= 7, "supersample has to be a positive integer between 0 and 7"

        await self._start.set(0)
        await self._supersample.set(supersample)
        await self._start.set(1)
        while not await self._done:
            await asyncio.sleep(0.010)
        interval = await self._distance * self._assembly.sys_clk_period
        self._log(f"Measured interval: {interval:1.9f} s")
        return interval

    async def measure_distance(self, supersample: int, speed_of_sound: float) -> float:
        """Measures the distance to the object by using the speed of sound.

        :py:`supersample` represents the number of samples to take for supersampling,
        as 2^samples. For example, if you want to take 8 samples, set this parameter to 3.
        A value of 0 means no supersampling. Maximum value is 7.

        :py:`speed_of_sound` is the speed of sound in the current environment.
        """
        interval = await self.measure_time(supersample)
        distance = interval * speed_of_sound / 2
        self._log(f"Measured distance: {distance:2.4f}")
        return distance


class SensorHCSR04Applet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "measure distance using HC-SR04 compatible ultrasound sensors"
    description = """
    Measure distance using HC-SR04 compatible ultrasound sensors.
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
            "-S", "--supersample", type=int, default=4,
            help="""number of samples to take for supersampling (to the power of two).
                    set to 0 to disable supersampling""")
        parser.add_argument(
            "--speed-of-sound", type=float, default=343.2,
            help="speed of sound in the current environment")
        parser.add_argument(
            "-t", "--timeout", type=float, default=0.1,
            help="timeout for each measurement, in seconds")

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

        p_measure = p_operation.add_parser("measure", help="display measured values")
        p_log = p_operation.add_parser("log", help="log measured values")
        p_log.add_argument(
            "-i", "--interval", type=float, default=0.1,
            help="interval between measurements, in seconds")
        DataLogger.add_subparsers(p_log)

    async def run(self, args):
        async def retrieve_distance():
            return await self.hcsr04_iface.measure_distance(args.supersample,
                                                            args.speed_of_sound)

        if args.operation == "measure":
            try:
                distance = await asyncio.wait_for(retrieve_distance(), timeout=args.timeout)
                print(f"distance: {distance:2.4f}")
            except TimeoutError:
                raise SensorHCSR04Error("measurement timed out")

        elif args.operation == "log":
            field_names = dict(dist="distance")
            data_logger = await DataLogger(self.logger, args, field_names=field_names)
            while True:
                try:
                    distance = await asyncio.wait_for(retrieve_distance(), timeout=args.timeout)
                    fields = dict(dist=distance)
                    await data_logger.report_data(fields=fields)
                    await asyncio.sleep(args.interval)
                except TimeoutError as error:
                    await data_logger.report_error("timeout", exception=error)

    @classmethod
    def tests(cls):
        from . import test
        return test.SensorHCSR04AppletTestCase
