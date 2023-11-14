from collections import defaultdict
import logging
import argparse
from vcd import VCDWriter
from amaranth import *
from amaranth.lib.cdc import FFSynchronizer

from ....gateware.pads import *
from ....gateware.analyzer import *
from ... import *
from .signal_compressor import SignalCompressor
from .arbeiter import LAArbeiter

# This LA uses a simple protocol for sending compressed values over the FIFO:
# Each packet starts with a 8 bit size word. The size can be 0, then the word only consists of that
# word. If the size is n != 0, the packet is n*2 bytes long. Each 16bit word is encoded acording
# to the format described in the SignalCompressor value. The packets are round-robin for each pin.

class BetterLASubtarget(Elaboratable):
    def __init__(self, pads, in_fifo):
        self.pads    = pads
        self.in_fifo = in_fifo

        self.la = LAArbeiter(in_fifo)

    def elaborate(self, platform):
        m = Module()
        m.submodules += self.la

        pins_i = Signal.like(self.pads.i_t.i)
        m.submodules += FFSynchronizer(self.pads.i_t.i, pins_i)
        m.d.comb += self.la.input.eq(pins_i)

        return m


class BetterLAApplet(GlasgowApplet):
    logger = logging.getLogger(__name__)
    help = "capture logic waveforms"
    description = """
    A somewhat better logic analyzer applet that allows for the capture of traces as VCD files.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_set_argument(parser, "i", width=range(1, 17), default=1)

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        iface.add_subtarget(BetterLASubtarget(
            pads=iface.get_pads(args, pin_sets=("i",)),
            in_fifo=iface.get_in_fifo(depth=512*16),
        ))

        self._sample_freq = target.sys_clk_freq
        self._pins = getattr(args, "pin_set_i")

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
            pull_high = set(args.pin_set_i)
        if args.pull_downs:
            pull_low = set(args.pin_set_i)
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args,
                                                           pull_low=pull_low, pull_high=pull_high)
        return iface

    @classmethod
    def add_interact_arguments(cls, parser):
        parser.add_argument(
            "file", metavar="VCD-FILE", type=argparse.FileType("w"),
            help="write VCD waveforms to VCD-FILE")

    async def interact(self, device, args, iface):
        pins = defaultdict(list)
        overrun = False

        zero_chunks = 0
        chunks = 0
        try:  # this try catches Ctrl+C for being able to manually interrupt capture
            while not overrun:
                for p in self._pins:
                    pkgs = await LAArbeiter.read_chunk(iface.read)
                    if len(pkgs) == 0:
                        zero_chunks += 1
                    chunks += 1
                    pins[p].extend(pkgs)
                    if len(pkgs) > 255 - len(self._pins):
                        overrun = True
                        print("overrun")
        finally:
            events = []
            cycles = 0
            for p, pkgs in pins.items():
                cycle = 0
                for pkg in pkgs:
                    for value, duration in SignalCompressor.decode_pkg(pkg):
                        timestamp = cycle * 1_000_000_000 // self._sample_freq
                        events.append((timestamp, p, value))
                        cycle += duration
                cycles = max(cycle, cycles)
            events.sort(key=lambda e: e[0])

            total_pkgs = sum(len(pkgs) for pkgs in pins.values())
            total_bytes = chunks + total_pkgs * 2

            print(f"captured {cycles} cycles")
            print(f"chunking overhead: {chunks / total_bytes * 100}%")
            print(f"zero chunks overhead: {zero_chunks / total_bytes * 100}%")
            print(f"compression gain: {100 - (total_bytes * 8 / cycle * 100)}%")
            

            vcd_writer = VCDWriter(args.file, timescale="1 ns", check_values=False)
            vcd_signals = {
                p: vcd_writer.register_var(scope="", name="pin[{}]".format(p), var_type="wire", 
                                           size=1, init=0)
                for p in pins.keys()
            }
            for timestamp, p, value in events:
                signal = vcd_signals[p]
                vcd_writer.change(signal, timestamp, value)
            vcd_writer.close(timestamp)
