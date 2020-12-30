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
            width=32,
        )
        m.d.comb += self.edge_count.eq(m.submodules.ripple.count)

        return m

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

        reg_clk_count,  self.__reg_clk_count  = target.registers.add_rw(32)
        reg_edge_count, self.__reg_edge_count = target.registers.add_ro(32)
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

    async def measure(self, device, args, clk_count):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)

        await device.write_register(self.__reg_clk_count, clk_count, width=4)

        await iface.write([ _Command.GO ])
        await iface.flush()

        while await device.read_register(self.__reg_running, width=1):
            await asyncio.sleep(0.1)

        edge_count = await device.read_register(self.__reg_edge_count, width=4)

        sample_duration = clk_count / self.sys_clk_freq
        signal_freq = edge_count / sample_duration

        return signal_freq

    async def run(self, device, args):
        signal_freq = await self.measure(device, args, int(self.sys_clk_freq * args.duration))
        print('signal frequency: {:>7.3f} {:1}Hz'.format( *num_to_si(signal_freq) ))
