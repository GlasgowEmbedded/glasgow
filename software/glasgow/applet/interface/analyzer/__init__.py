import logging
import argparse
from vcd import VCDWriter
from nmigen import *
from nmigen.lib.cdc import FFSynchronizer

from ....gateware.pads import *
from ....gateware.analyzer import *
from ... import *


class AnalyzerSubtarget(Elaboratable):
    def __init__(self, pads, in_fifo):
        self.pads    = pads
        self.in_fifo = in_fifo

        self.analyzer = EventAnalyzer(in_fifo)
        self.event_source = self.analyzer.add_event_source("pin", "change", len(pads.i_t.i))

    def elaborate(self, platform):
        m = Module()
        m.submodules += self.analyzer

        pins_i = Signal.like(self.pads.i_t.i)
        pins_r = Signal.like(self.pads.i_t.i)
        m.submodules += FFSynchronizer(self.pads.i_t.i, pins_i)

        m.d.sync += pins_r.eq(pins_i)
        m.d.comb += [
            self.event_source.data.eq(pins_i),
            self.event_source.trigger.eq(pins_i != pins_r)
        ]

        return m


class AnalyzerInterface:
    def __init__(self, interface, event_sources):
        self.lower   = interface
        self.decoder = TraceDecoder(event_sources)

    async def read(self):
        self.decoder.process(await self.lower.read())
        return self.decoder.flush()


class AnalyzerApplet(GlasgowApplet, name="analyzer"):
    logger = logging.getLogger(__name__)
    help = "capture logic waveforms"
    description = """
    Capture waveforms, similar to a logic analyzer.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_set_argument(parser, "i", width=range(1, 17), default=1)

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        subtarget = iface.add_subtarget(AnalyzerSubtarget(
            pads=iface.get_pads(args, pin_sets=("i",)),
            in_fifo=iface.get_in_fifo(),
        ))

        self._sample_freq = target.sys_clk_freq
        self._event_sources = subtarget.analyzer.event_sources

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)

        g_pulls = parser.add_mutually_exclusive_group()
        g_pulls.add_argument(
            "--pull-ups", default=False, action="store_true",
            help="enable pull-ups on all pins")
        g_pulls.add_argument(
            "--pull-downs", default=False, action="store_true",
            help="enable pull-downs on all pins")

    async def run(self, device, args):
        pull_low  = set()
        pull_high = set()
        if args.pull_ups:
            pull_low = set(args.pin_set_i)
        if args.pull_downs:
            pull_high = set(args.pin_set_i)
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args,
                                                           pull_low=pull_low, pull_high=pull_high)
        return AnalyzerInterface(iface, self._event_sources)

    @classmethod
    def add_interact_arguments(cls, parser):
        parser.add_argument(
            "file", metavar="VCD-FILE", type=argparse.FileType("w"),
            help="write VCD waveforms to VCD-FILE")

    async def interact(self, device, args, iface):
        vcd_writer = VCDWriter(args.file, timescale="1 ns", check_values=False)
        signals = []
        for index in range(self._event_sources[0].width):
            signals.append(vcd_writer.register_var(scope="", name="pin[{}]".format(index),
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

# -------------------------------------------------------------------------------------------------

class AnalyzerAppletTestCase(GlasgowAppletTestCase, applet=AnalyzerApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
