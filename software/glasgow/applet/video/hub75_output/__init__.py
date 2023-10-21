import argparse
import logging
from amaranth import *

from ... import *


class VideoHub75Output(Elaboratable):
    def __init__(self, pads):
        self.pads = pads

        self.rgb1 = Signal(pads.rgb1_t.o.shape())
        self.rgb2 = Signal(pads.rgb2_t.o.shape())
        self.addr = Signal(pads.addr_t.o.shape())
        self.clk  = Signal()
        self.lat  = Signal()
        self.oe   = Signal()

    def elaborate(self, platform):
        m = Module()

        m.d.comb += [
            self.pads.rgb1_t.oe.eq(1),
            self.pads.rgb1_t.o.eq(self.rgb1),

            self.pads.rgb2_t.oe.eq(1),
            self.pads.rgb2_t.o.eq(self.rgb2),

            self.pads.addr_t.oe.eq(1),
            self.pads.addr_t.o.eq(self.addr),

            self.pads.clk_t.oe.eq(1),
            self.pads.clk_t.o.eq(self.clk),

            self.pads.lat_t.oe.eq(1),
            self.pads.lat_t.o.eq(self.lat),

            self.pads.oe_t.oe.eq(1),
            self.pads.oe_t.o.eq(~self.oe),
        ]

        return m


class VideoHub75OutputSubtarget(Elaboratable):
    def __init__(self, pads, px_width, px_height, expose_delay, pattern_rate):
        self.pads = pads

        self.px_width = px_width
        self.px_height = px_height
        self.expose_delay = expose_delay
        self.pattern_rate = pattern_rate

    def pix_gen(self, x, y):
        return Cat(x[self.pattern_rate:] + y[self.pattern_rate:])

    def elaborate(self, platform):
        px_height_half = self.px_height // 2

        m = Module()

        m.submodules.output = output = VideoHub75Output(self.pads)

        row      = Signal(output.addr.shape())
        row_disp = Signal(output.addr.shape())
        m.d.comb += output.addr.eq(row_disp)

        cnt = Signal(32)
        col = Signal(cnt.shape())
        m.d.comb += col.eq(cnt[1:])

        with m.FSM() as fsm:
            with m.State("ROW-SHIFT"):
                with m.If(cnt < self.px_width * 2):
                    m.d.comb += [
                        output.clk.eq(cnt[0]),
                        output.rgb1.eq(self.pix_gen(col, row)),
                        output.rgb2.eq(self.pix_gen(col, row + px_height_half)),
                    ]
                    m.d.sync += cnt.eq(cnt + 1)
                with m.Else():
                    m.d.sync += cnt.eq(0)
                    m.next = "EXPOSE"

            with m.State("EXPOSE"):
                m.d.comb += output.oe.eq(1)

                with m.If(cnt < self.expose_delay):
                    m.d.sync += cnt.eq(cnt + 1)
                with m.Else():
                    m.next = "LATCH"

            with m.State("LATCH"):
                m.d.comb += output.lat.eq(1),
                m.d.sync += [
                    row_disp.eq(row),
                    row.eq(Mux(row < (px_height_half - 1), row + 1, 0)),
                    cnt.eq(0),
                ]
                m.next = "ROW-SHIFT"

        return m


class VideoHub75OutputApplet(GlasgowApplet):
    logger = logging.getLogger(__name__)
    help = "display a test pattern on HUB75 panel"
    description = """
    Output a test pattern on a HUB75 compatible LED matrix.

    This applet expects two RGB interfaces (each driving half of a display), that share common
    Clock, Latch and #OE signals.

    Using a horizontal resolution that does not match your display will cause artifacts on one side.
    Using a vertical resolution that does not match your display will cause the image to split.
    """

    __pin_sets = ("rgb1", "rgb2", "addr")
    __pins = ("clk", "lat", "oe")

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_set_argument(parser, "rgb1", width=3,          default=(0,1,2))
        access.add_pin_set_argument(parser, "rgb2", width=3,          default=(3,4,5))
        access.add_pin_set_argument(parser, "addr", width=range(1,6), default=(8,9,10,11,12))
        access.add_pin_argument(parser,     "clk",                    default=13)
        access.add_pin_argument(parser,     "lat",                    default=14)
        access.add_pin_argument(parser,     "oe",                     default=15)

        parser.add_argument(
            "--px-width", metavar="PX-WIDTH", type=int, default=64,
            help="the width of the LED matrix, in pixels (default: %(default)s)")
        parser.add_argument(
            "--px-height", metavar="PX-HEIGHT", type=int, default=64,
            help="the height of the LED matrix, in pixels (default: %(default)s)")
        parser.add_argument(
            "--pattern-rate", metavar="PATTERN-RATE", type=int, default=2,
            help="the pattern's rate-of-change (default: %(default)s)")
        parser.add_argument(
            "--expose-delay", metavar="EXPOSE-DELAY", type=int, default=1000,
            help="the exposure delay, directly impacts brightness and refresh rate (default: %(default)s)")

    def build(self, target, args):
        num_addr_bits = len(args.pin_set_addr)
        max_px_height = pow(2, num_addr_bits) * 2
        if args.px_height > max_px_height:
            raise GlasgowAppletError("Cannot have a vertical panel resolution of {} with only {} address bits..."
                                     .format(args.px_height, num_addr_bits))

        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        subtarget = iface.add_subtarget(VideoHub75OutputSubtarget(
            pads=iface.get_pads(args, pins=self.__pins, pin_sets=self.__pin_sets),
            px_width=args.px_width,
            px_height=args.px_height,
            expose_delay=args.expose_delay,
            pattern_rate=args.pattern_rate,
        ))

        return subtarget

    async def run(self, device, args):
        return await device.demultiplexer.claim_interface(self, self.mux_interface, args)

    @classmethod
    def tests(cls):
        from . import test
        return test.VideoHub75OutputAppletTestCase
