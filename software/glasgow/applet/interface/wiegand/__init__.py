import logging
import asyncio
from amaranth import *

import time

from ... import *


class WiegandSubtarget(Elaboratable):
    def __init__(self, pads, in_fifo, out_fifo, pulse_width, pulse_gap):
        self.pads     = pads
        self.in_fifo  = in_fifo
        self.out_fifo = out_fifo

        self.pulse_width = pulse_width
        self.pulse_gap = pulse_gap

        self.limit = pulse_gap + pulse_width

        self.done = Signal()
        self.bits = Signal(range(26 + 1), reset=26)
        self.preamble = Signal(range(100 + 1), reset=100)
        self.preamble_done = Signal()

        self.ovf = Signal()
        self.gap = Signal()

        self.count = Signal(range(self.limit + 1))

    def elaborate(self, platform):
        m = Module()

        m.d.comb += self.ovf.eq(self.count == self.limit)
        m.d.comb += self.gap.eq(self.count > self.pulse_width)

        m.d.comb += self.done.eq(self.bits == 0)
        m.d.comb += self.preamble_done.eq(self.preamble == 0)

        m.d.comb += self.pads.d0_t.oe.eq(1)
        m.d.comb += self.pads.d1_t.oe.eq(1)

        m.d.comb += self.pads.d1_t.o.eq(1)

        with m.If(self.done):
            m.d.sync += self.pads.d0_t.o.eq(1)
        with m.Else():
            with m.If(~self.preamble_done):
                m.d.sync += self.pads.d0_t.o.eq(1)
                with m.If(self.ovf):
                    m.d.sync += self.preamble.eq(self.preamble - 1)
                    m.d.sync += self.count.eq(0)
                with m.Else():
                    m.d.sync += self.count.eq(self.count + 1)
            with m.Else():
                with m.If(self.ovf):
                    m.d.sync += self.bits.eq(self.bits - 1)
                    m.d.sync += self.count.eq(0)
                with m.Else():
                    m.d.sync += self.count.eq(self.count + 1)

                with m.If(self.gap):
                    m.d.sync += self.pads.d0_t.o.eq(1)

                with m.Else():
                    m.d.sync += self.pads.d0_t.o.eq(0)


        # self.pads.d0_t.eq(0)
        return m


class WiegandApplet(GlasgowApplet):
    logger = logging.getLogger(__name__)
    help = "boilerplate applet"
    description = """
    An example of the boilerplate code required to implement a minimal Glasgow applet.

    The only things necessary for an applet are:
        * a subtarget class,
        * an applet class,
        * the `build` and `run` methods of the applet class.

    Everything else can be omitted and would be replaced by a placeholder implementation that does
    nothing. Similarly, there is no requirement to use IN or OUT FIFOs, or any pins at all.
    """

    __pins = ("d0", "d1")

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        for pin in cls.__pins:
            access.add_pin_argument(parser, pin, default=True)

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)

        pulse_width = self.derive_clock(
                input_hz=target.sys_clk_freq, output_hz=11904)

        pulse_gap = self.derive_clock(
                input_hz=target.sys_clk_freq, output_hz=3875)

        iface.add_subtarget(WiegandSubtarget(
            pads=iface.get_pads(args, pins=self.__pins),
            in_fifo=iface.get_in_fifo(),
            out_fifo=iface.get_out_fifo(),
            pulse_width=pulse_width,
            pulse_gap=pulse_gap
        ))

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)

    async def run(self, device, args):
        return await device.demultiplexer.claim_interface(self, self.mux_interface, args)

    @classmethod
    def add_interact_arguments(cls, parser):
        pass

    async def interact(self, device, args, iface):
        time.sleep(1)
        # for i in range(1, 10000000):
            # pass

# -------------------------------------------------------------------------------------------------

class WiegandAppletTestCase(GlasgowAppletTestCase, applet=WiegandApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
