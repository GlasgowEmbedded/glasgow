import argparse
import logging
from amaranth import *
from amaranth.lib.cdc import FFSynchronizer

from ... import *


class LevelTimeoutSubtarget(Elaboratable):
    def __init__(self, pads, input_inverted, input_timeout, output_inverted, output_width):
        self.pads = pads

        self.input_inverted = input_inverted
        self.input_timeout = input_timeout

        self.output_inverted = output_inverted
        self.output_width = output_width

    def elaborate(self, platform):
        sys_clk_freq = platform.default_clk_frequency
        t_timeout = int(1 + sys_clk_freq * self.input_timeout)
        t_outpulse = int(1 + sys_clk_freq * self.output_width)

        m = Module()

        in_r = Signal()
        m.d.comb += self.pads.in_t.oe.eq(0)
        if self.input_inverted:
            m.submodules += FFSynchronizer(~self.pads.in_t.i, in_r, reset=1)
        else:
            m.submodules += FFSynchronizer(self.pads.in_t.i, in_r, reset=1)

        out_r = Signal()
        m.d.comb += self.pads.out_t.oe.eq(1)
        if self.output_inverted:
            m.d.comb += self.pads.out_t.o.eq(~out_r)
        else:
            m.d.comb += self.pads.out_t.o.eq(out_r)

        ctr_timeout = Signal(range(t_timeout + 1))
        ctr_outpulse = Signal(range(t_outpulse + 1))

        with m.FSM():
            with m.State("reset"):
                m.d.sync += ctr_timeout.eq(t_timeout)
                with m.If(~in_r):
                    m.next = "ready"

            with m.State("ready"):
                with m.If(in_r):
                    m.next = "wait-timeout"

            with m.State("wait-timeout"):
                with m.If(~in_r):
                    m.next = "reset"
                with m.Elif(ctr_timeout > 0):
                    m.d.sync += ctr_timeout.eq(ctr_timeout - 1)
                with m.Else():
                    m.d.sync += ctr_outpulse.eq(t_outpulse)
                    m.next = "reset"

        m.d.comb += out_r.eq(ctr_outpulse > 0)
        with m.If(ctr_outpulse > 0):
            m.d.sync += ctr_outpulse.eq(ctr_outpulse - 1)

        return m


class LevelTimeoutApplet(GlasgowApplet):
    logger = logging.getLogger(__name__)
    help = "level timeout trigger"
    description = """
    Generate a trigger pulse when a signal remains in a given state for too long.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_argument(parser, "in", default=True)
        access.add_pin_argument(parser, "out", default=True)

        parser.add_argument("--input-inverted", action="store_true", default=False,
                            help="start timeout from a falling edge")
        parser.add_argument("--input-timeout", metavar="TIMEOUT", type=int, default=1500,
                            help="timeout duration, in microseconds (default: %(default)dus)")

        parser.add_argument("--output-inverted", action="store_true", default=False,
                            help="produce a low pulse")
        parser.add_argument("--output-width", metavar="WIDTH", type=int, default=5,
                            help="output pulse width, in microseconds (default: %(default)dus)")

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        iface.add_subtarget(LevelTimeoutSubtarget(
            pads=iface.get_pads(args, pins=("in","out")),
            input_inverted=args.input_inverted,
            input_timeout=args.input_timeout / 1_000_000,
            output_inverted=args.output_inverted,
            output_width=args.output_width / 1_000_000,
        ))

    async def run(self, device, args):
        return await device.demultiplexer.claim_interface(self, self.mux_interface, args)

    async def interact(self, device, args, trigger):
        pass

    @classmethod
    def tests(cls):
        from . import test
        return test.LevelTimeoutAppletTestCase
