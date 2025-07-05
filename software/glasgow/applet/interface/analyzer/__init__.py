import logging
import argparse
from vcd import VCDWriter
from amaranth import *
from amaranth.lib import enum, data, wiring, stream, io
from amaranth.lib.wiring import In, Out
from amaranth.lib.cdc import FFSynchronizer

from glasgow.abstract import AbstractAssembly, GlasgowPin
from glasgow.applet import GlasgowAppletV2

from ....gateware.analyzer import *
from ... import *


class AnalyzerComponent(wiring.Component):
    o_stream: Out(stream.Signature(8))

    def __init__(self, ports):
        self.ports = ports

        self.analyzer = EventAnalyzer(in_fifo)
        self.event_source = self.analyzer.add_event_source("pin", "change", len(self.ports.i))

    def elaborate(self, platform):
        m = Module()
        m.submodules += self.analyzer

        m.submodules.i_buffer = i_buffer = io.Buffer("i", self.ports.i)
        pins_i = Signal.like(i_buffer.i)
        pins_r = Signal.like(i_buffer.i)
        m.submodules += FFSynchronizer(i_buffer.i, pins_i)

        m.d.sync += pins_r.eq(pins_i)
        m.d.comb += [
            self.event_source.data.eq(pins_i),
            self.event_source.trigger.eq(pins_i != pins_r)
        ]

        return m


class AnalyzerInterface:
    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, event_sources):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        ports = [assembly.add_port(event_sources[i], "%d" % i) for i in range(len(event_sources))]
        component = assembly.add_submodule(AnalyzerComponent(ports))
        self._pipe = assembly.add_in_pipe(component.o_stream, flush=C(1))

    def _log(self, message: str, *args):
        self._logger.log(self._level, "boilerplate: " + message, *args)

        self.lower   = interface
        self.decoder = TraceDecoder(event_sources)

    async def read(self):
        self.decoder.process(await self.lower.read())
        return self.decoder.flush()


class AnalyzerApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "capture logic waveforms"
    description = """
    Capture waveforms, similar to a logic analyzer.
    """
    required_revision = "C0" # iCE40UP5K isn't quite fast enough

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "i", width=range(1, 17), default=1)

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.assembly_iface = AnalyzerInterface(self.logger, self.assembly, args.i)

    @classmethod
    def add_setup_arguments(cls, parser):
        g_pulls = parser.add_mutually_exclusive_group()
        g_pulls.add_argument(
            "--pull-ups", default=False, action="store_true",
            help="enable pull-ups on all pins")
        g_pulls.add_argument(
            "--pull-downs", default=False, action="store_true",
            help="enable pull-downs on all pins")

    async def setup(self, device, args):
        pull_low  = set()
        pull_high = set()
        if args.pull_ups:
            pull_high = set(args.i)
        if args.pull_downs:
            pull_low = set(args.i)
        await self.analyzer_iface.run()

    @classmethod
    def add_run_arguments(cls, parser):
        parser.add_argument(
            "--pin-names", metavar="NAMES", dest="names", default=None,
            help="optional comma separated list of pin names")
        parser.add_argument(
            "file", metavar="VCD-FILE", type=argparse.FileType("w"),
            help="write VCD waveforms to VCD-FILE")

    async def run(self, device, args, iface):
        vcd_writer = VCDWriter(args.file, timescale="1 ns", check_values=False)
        signals = []

        names = []
        if args.names:
            names = args.names.split(",")
            assert len(names) == self._event_sources[0].width
        else:
            names = [ f"pin[{index}]" for index in range(self._event_sources[0].width) ]

        for index in range(self._event_sources[0].width):
            signals.append(vcd_writer.register_var(scope="glasgow", name=names[index],
                var_type="wire", size=1, init=0))

        try:
            overrun = False
            timestamp = 0
            while not overrun:
                for cycle, events in await iface.read():
                    timestamp = cycle * 1_000_000_000 // self._sample_freq

                    if events == "overrun":
                        self.logger.error("FIFO overrun, shutting down")
                        for signal in signals:
                            vcd_writer.change(signal, timestamp, "x")
                        overrun = True
                        break

                    if "pin" in events: # could be also "throttle"
                        value = events["pin"]
                        for bit, signal in enumerate(signals):
                            vcd_writer.change(signal, timestamp, (value >> bit) & 1)

        finally:
            vcd_writer.close(timestamp)

    @classmethod
    def tests(cls):
        from . import test
        return test.AnalyzerAppletTestCase
