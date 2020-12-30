#
# notes:
#    - does not play nicely with slow edges or analog signals (e.g: sine wave)
#      will produce very inaccurate and inconsistent results
#

import enum
import asyncio
import logging
from nmigen import *

from ....gateware.pads import *
from ....gateware.ripple import *
from ....support.si_prefix import num_to_si
from ... import *


class _Command(enum.IntEnum):
    GO = 0x00


class FrequencyCounterSubtarget(Elaboratable):
    def __init__(self, pads, clk_count, edge_count, running, out_fifo):
        self.pads = pads
        self.clk_count = clk_count
        self.edge_count = edge_count
        self.running = running
        self.out_fifo = out_fifo

    def elaborate(self, platform):
        m = Module()

        trigger = Signal()
        m.d.comb += [
            self.out_fifo.r_en.eq(self.out_fifo.r_rdy),
            trigger.eq(self.out_fifo.r_en & (self.out_fifo.r_data == _Command.GO)),
        ]

        clk_count = Signal.like(self.clk_count)
        with m.If(trigger):
            m.d.sync += clk_count.eq(self.clk_count)
        with m.Elif(clk_count > 0):
            m.d.sync += clk_count.eq(clk_count - 1)
            m.d.comb += self.running.eq(1)

        m.submodules.ripple = RippleCounter(
            rst=trigger,
            clk=self.pads.i_t.i,
            clk_en=self.running,
            width=64,
        )
        m.d.comb += self.edge_count.eq(m.submodules.ripple.count)

        return m

class FrequencyCounterInterface:
    def __init__(self, applet, device, interface):
        self.applet = applet
        self.device = device
        self.lower = interface

    async def configure(self, duration=2.0):
        ctr = int(self.applet.sys_clk_freq * duration)

        # this is broken (see comment below)
        #await self.device.write_register(self.applet.__reg_clk_count, ctr, width=8)

        await self.applet.set_clk_count(ctr)

    async def start(self):
        await self.lower.write([ _Command.GO ])
        await self.lower.flush()

    async def is_running(self):
        return await self.applet.get_running()

    async def wait(self):
        while await self.is_running():
            await asyncio.sleep(0.1)

    async def get_result(self):
        clk_count = await self.applet.get_clk_count()
        edge_count = await self.applet.get_edge_count()

        sample_duration = clk_count / self.applet.sys_clk_freq
        signal_freq = edge_count / sample_duration

        precision = self.applet.sys_clk_freq / clk_count

        return signal_freq, precision

    async def measure(self, duration=2.0):
        await self.configure(duration)
        await self.start()
        await self.wait()
        return await self.get_result()

class FrequencyCounterApplet(GlasgowApplet, name="freq-counter"):
    logger = logging.getLogger(__name__)
    help = "frequency counter"
    description = """
    Simple frequency counter, based on a ripple counter.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_argument(parser, "i", default=True)

        parser.add_argument(
            "--duration", metavar="DURATION", type=float, default=2.0,
            help="how long to run for, longer gives higher resolution (default: %(default)s)")

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)

        reg_clk_count,  self.__reg_clk_count  = target.registers.add_rw(64)
        reg_edge_count, self.__reg_edge_count = target.registers.add_ro(64)
        reg_running,    self.__reg_running    = target.registers.add_ro(1)

        subtarget = iface.add_subtarget(FrequencyCounterSubtarget(
            pads=iface.get_pads(args, pins=("i",)),
            clk_count=reg_clk_count,
            edge_count=reg_edge_count,
            running=reg_running,
            out_fifo=iface.get_out_fifo(),
        ))

        self.sys_clk_freq = target.sys_clk_freq

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)

    async def run(self, device, args):
        self.device = device

        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args, pull_low={args.pin_i})
        freq_ctr = FrequencyCounterInterface(self, device, iface)

        return freq_ctr

    async def interact(self, device, args, freq_ctr):
        signal_freq, precision = await freq_ctr.measure(args.duration)
        print('signal frequency: {:>7.3f} {:1}Hz'.format( *num_to_si(signal_freq) ))
        print('precision:   +/-  {:>7.3f} {:1}Hz'.format( *num_to_si(precision) ))

    # TODO: for some reason, accessing the registers from the FrequencyCounterInterface
    #       class will raise an odd / malformed AttributeException... as below. This exception
    #       isn't raised by GlasgowHardwareDevice.write_register(), but appears to occur on the
    #       return - wrapping below with a try / except / pass effectively resolves the issue,
    #       but A) that's disgusting, and B) it still breaks assignment / register_read() calls.
    #
    #       for the moment, I've put proxy functions here, but I'd like to remove them...?
    #
    #   $ glasgow run freq-counter -V 3.3
    #   I: g.device.hardware: device already has bitstream ID 171709aadf51812cc9d1e3e54e881a43
    #   I: g.cli: running handler for applet 'freq-counter'
    #   I: g.applet.interface.freq_counter: port(s) A, B voltage set to 3.3 V
    #   Traceback (most recent call last):
    #     File "/home/attie/proj_local/glasgow/venv/bin/glasgow", line 11, in <module>
    #       load_entry_point('glasgow', 'console_scripts', 'glasgow')()
    #     File "/home/attie/proj_local/glasgow/glasgow/software/glasgow/cli.py", line 857, in main
    #       exit(loop.run_until_complete(_main()))
    #     File "/home/attie/.bin/python3.8.2/lib/python3.8/asyncio/base_events.py", line 616, in run_until_complete
    #       return future.result()
    #     File "/home/attie/proj_local/glasgow/glasgow/software/glasgow/cli.py", line 650, in _main
    #       task.result()
    #     File "/home/attie/proj_local/glasgow/glasgow/software/glasgow/cli.py", line 600, in run_applet
    #       iface = await applet.run(device, args)
    #     File "/home/attie/proj_local/glasgow/glasgow/software/glasgow/applet/interface/freq_counter/__init__.py", line 136, in run
    #       signal_freq = await freq_ctr.measure(args.duration)
    #     File "/home/attie/proj_local/glasgow/glasgow/software/glasgow/applet/interface/freq_counter/__init__.py", line 85, in measure
    #       await self.configure(duration)
    #     File "/home/attie/proj_local/glasgow/glasgow/software/glasgow/applet/interface/freq_counter/__init__.py", line 60, in configure
    #       await self.device.write_register(self.applet.__reg_clk_count, ctr, width=8)
    #   AttributeError: 'FrequencyCounterApplet' object has no attribute '_FrequencyCounterInterface__reg_clk_count'

    async def get_clk_count(self):
        return await self.device.read_register(self.__reg_clk_count, width=8)
    async def set_clk_count(self, value):
        await self.device.write_register(self.__reg_clk_count, value, width=8)

    async def get_edge_count(self):
        return await self.device.read_register(self.__reg_edge_count, width=8)

    async def get_running(self):
        return bool(await self.device.read_register(self.__reg_running, width=1))
