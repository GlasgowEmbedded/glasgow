import argparse
import logging
from amaranth import *
from amaranth.lib import io

from ... import *


class VideoHub75Output(Elaboratable):
    def __init__(self, ports):
        self.ports = ports

        self.rgb1 = Signal(len(self.ports.rgb1))
        self.rgb2 = Signal(len(self.ports.rgb2))
        self.addr = Signal(len(self.ports.addr))
        self.clk  = Signal()
        self.lat  = Signal()
        self.oe   = Signal()

    def elaborate(self, platform):
        m = Module()

        m.submodules.rgb1_buffer = rgb1_buffer = io.Buffer("o", self.ports.rgb1)
        m.submodules.rgb2_buffer = rgb2_buffer = io.Buffer("o", self.ports.rgb2)
        m.submodules.addr_buffer = addr_buffer = io.Buffer("o", self.ports.addr)
        m.submodules.clk_buffer  = clk_buffer  = io.Buffer("o", self.ports.clk)
        m.submodules.lat_buffer  = lat_buffer  = io.Buffer("o", self.ports.lat)
        m.submodules.oe_buffer   = oe_buffer   = io.Buffer("o", self.ports.oe)

        m.d.comb += [
            rgb1_buffer.o.eq(self.rgb1),
            rgb2_buffer.o.eq(self.rgb2),
            addr_buffer.o.eq(self.addr),
            clk_buffer.o.eq(self.clk),
            lat_buffer.o.eq(self.lat),
            oe_buffer.o.eq(~self.oe),
        ]

        return m


class VideoHub75OutputSubtarget(Elaboratable):
    def __init__(self, ports, px_width, px_height, expose_delay, pattern_rate):
        self.ports = ports

        self.px_width = px_width
        self.px_height = px_height
        self.expose_delay = expose_delay
        self.pattern_rate = pattern_rate

    def pix_gen(self, x, y):
        return Cat(x[self.pattern_rate:] + y[self.pattern_rate:])

    def elaborate(self, platform):
        px_height_half = self.px_height // 2

        m = Module()

        m.submodules.output = output = VideoHub75Output(self.ports)

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

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pins_argument(parser, "rgb1", width=3,          default="A0:2")
        access.add_pins_argument(parser, "rgb2", width=3,          default="A3:5")
        access.add_pins_argument(parser, "addr", width=range(1,6), default="B0:4")
        access.add_pins_argument(parser, "clk",                    default="B5")
        access.add_pins_argument(parser, "lat",                    default="B6")
        access.add_pins_argument(parser, "oe",                     default="B7")

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
        num_addr_bits = len(args.addr)
        max_px_height = pow(2, num_addr_bits) * 2
        if args.px_height > max_px_height:
            raise GlasgowAppletError("Cannot have a vertical panel resolution of {} with only {} address bits..."
                                     .format(args.px_height, num_addr_bits))

        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        subtarget = iface.add_subtarget(VideoHub75OutputSubtarget(
            ports=iface.get_port_group(
                rgb1 = args.rgb1,
                rgb2 = args.rgb2,
                addr = args.addr,
                clk  = args.clk,
                lat  = args.lat,
                oe   = args.oe
            ),
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
