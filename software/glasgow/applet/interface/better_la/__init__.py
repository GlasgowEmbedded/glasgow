from collections import defaultdict
import io
import logging
import argparse
from vcd import VCDWriter
from amaranth import *
from amaranth.lib.cdc import FFSynchronizer

from ....gateware.pads import *
from ....gateware.analyzer import *
from ... import *
from .signal_compressor import SignalCompressor
from .arbiter import LAArbiter

# This LA uses a simple protocol for sending compressed values over the FIFO which is explained
# in the arbiter.py (high level chunks) and signal_compressor.py (low level packets) files.
# The basic architecture is as follows:
#          +------------------+       +--------+
# Pin0 --->| SignalCompressor |------>|  FIFO  |-----+
#          +------------------+       +--------+     |
#                                                    |
#          +------------------+       +--------+     |
# Pin1 --->| SignalCompressor |------>|  FIFO  |-----+     +-----------+      +----------+
#          +------------------+       +--------+     |     |           |      |          |
#                                                    +---->| LAArbiter |----->| USB-FIFO |
#          +------------------+       +--------+     |     |           |      |          |
# Pin2 --->| SignalCompressor |------>|  FIFO  |-----+     +-----------+      +----------+
#          +------------------+       +--------+     |
#                                                    |
#          +------------------+       +--------+     |
# PinN --->|       ...        |------>|   ...  |-----+
#          +------------------+       +--------+

class BetterLASubtarget(Elaboratable):
    def __init__(self, pads, in_fifo, counter_target=False):
        self.pads    = pads
        self.in_fifo = in_fifo
        self.counter_target = counter_target

        self.la = LAArbiter(in_fifo)

    def elaborate(self, platform):
        m = Module()
        m.submodules += self.la

        if self.counter_target:
            print("building bitstream with simulated counter target")
            counter = Signal(len(self.pads.i_t.i)+2)
            m.d.sync += counter.eq(counter + 1)
            m.d.comb += self.la.input.eq(counter[2:])
        else:
            print("building bitstream connected to real target")
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
        parser.add_argument(
            "--counter-target", default=False, action="store_true",
            help="simulate a target with a counter signal",
        )

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        iface.add_subtarget(BetterLASubtarget(
            pads=iface.get_pads(args, pin_sets=("i",)),
            in_fifo=iface.get_in_fifo(depth=512*16, auto_flush=False),
            counter_target=args.counter_target
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
        parser.add_argument("--buffer-size", type=int, default=10,
                            help="how much data to capture in MB")

    async def interact(self, device, args, iface):
        # Step 1: record a buffer
        # we do this before to get the full USB performance and not have any lag-spikes in between
        try:
            print(f"starting capture of {args.buffer_size} MB")
            buffer = await iface.read(1024*1024 * args.buffer_size)
        except KeyboardInterrupt:
            pass
        finally:
            print("captured buffer, converting...")
        

        # Step 2: parse the packets from the captured buffer and sort them into channels
        ptr = 0
        async def read(size, ) -> bytes:
            nonlocal ptr
            to_return = buffer[ptr:ptr+size]
            ptr += size
            if ptr >= len(buffer):
                return None
            return to_return
        channels = defaultdict(list)
        chunks = 0
        while True:
            read_result = await LAArbiter.read_chunk(read)
            if read_result is None:
                break
            channel, chunk = read_result
            if len(chunk) == 255:
                print(f"channel {channel} overrun")
                break
            channels[self._pins[channel]].extend(chunk)
            chunks += 1

        # Step 3: convert each channels packets into events, attach timestamps and sort them by
        # timestamp
        events = []
        cycles = None
        for p, pkgs in channels.items():
            cycle = 0
            for pkg in pkgs:
                for value, duration in SignalCompressor.decode_pkg(pkg):
                    events.append((cycle, p, value))
                    cycle += duration
            cycles = cycle if cycles is None else cycle if cycle < cycles else cycles
        events.sort(key=lambda e: e[0])

        # Step 3.5: report statistics
        total_pkgs = sum(len(pkgs) for pkgs in channels.values())
        total_bytes = chunks + total_pkgs * 2
        print(f"captured {cycles} samples ({cycles / self._sample_freq * 1000}ms)")
        print(f"chunking overhead: {chunks / total_bytes * 100}%")
        print(f"compression gain: {100 - (total_bytes * 8 / (cycle * len(self._pins)) * 100)}%")
        

        # Step 4: write out VCD file
        vcd_writer = VCDWriter(args.file, timescale="1 ns", check_values=False)
        vcd_signals = {
            p: vcd_writer.register_var(scope="", name="pin[{}]".format(p), var_type="wire", 
                                        size=1, init=0)
            for p in self._pins
        }
        for cycle, p, value in events:
            if cycle > cycles:
                # we dont write any timestamps for which we dont have data on all channels
                break
            signal = vcd_signals[p]
            timestamp = cycle * 1_000_000_000 // self._sample_freq
            vcd_writer.change(signal, timestamp, value)
        vcd_writer.close(timestamp)
