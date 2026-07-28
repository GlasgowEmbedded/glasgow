from amaranth import *
from amaranth.lib import io

from glasgow.support import logging
from glasgow.applet import GlasgowAppletV2, GlasgowAppletError


class VideoHub75OutputGenerator(Elaboratable):
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

        m.submodules.rgb1_buffer = rgb1_buffer = io.Buffer("o", self.ports.rgb1)
        m.submodules.rgb2_buffer = rgb2_buffer = io.Buffer("o", self.ports.rgb2)
        m.submodules.addr_buffer = addr_buffer = io.Buffer("o", self.ports.addr)
        m.submodules.clk_buffer  = clk_buffer  = io.Buffer("o", self.ports.clk)
        m.submodules.lat_buffer  = lat_buffer  = io.Buffer("o", self.ports.lat)
        # The physical #OE line is active-low.
        m.submodules.oe_buffer   = oe_buffer   = io.Buffer("o", ~self.ports.oe)

        row      = Signal(addr_buffer.o.shape())
        row_disp = Signal(addr_buffer.o.shape())
        m.d.comb += addr_buffer.o.eq(row_disp)

        cnt = Signal(32)
        col = Signal(cnt.shape())
        m.d.comb += col.eq(cnt[1:])

        with m.FSM():
            with m.State("ROW-SHIFT"):
                with m.If(cnt < self.px_width * 2):
                    m.d.comb += [
                        clk_buffer.o.eq(cnt[0]),
                        rgb1_buffer.o.eq(self.pix_gen(col, row)),
                        rgb2_buffer.o.eq(self.pix_gen(col, row + px_height_half)),
                    ]
                    m.d.sync += cnt.eq(cnt + 1)
                with m.Else():
                    m.d.sync += cnt.eq(0)
                    m.next = "EXPOSE"

            with m.State("EXPOSE"):
                m.d.comb += oe_buffer.o.eq(1)

                with m.If(cnt < self.expose_delay):
                    m.d.sync += cnt.eq(cnt + 1)
                with m.Else():
                    m.next = "LATCH"

            with m.State("LATCH"):
                m.d.comb += lat_buffer.o.eq(1)
                m.d.sync += [
                    row_disp.eq(row),
                    row.eq(Mux(row < (px_height_half - 1), row + 1, 0)),
                    cnt.eq(0),
                ]
                m.next = "ROW-SHIFT"

        return m


class VideoHub75OutputApplet(GlasgowAppletV2):
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
        access.add_voltage_argument(parser)

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
            help="the exposure delay, directly impacts brightness and refresh rate "
                 "(default: %(default)s)")

    def build(self, args):
        if args.px_width <= 0:
            raise GlasgowAppletError(
                f"Panel width must be positive, not {args.px_width}")
        if args.px_height <= 0:
            raise GlasgowAppletError(
                f"Panel height must be positive, not {args.px_height}")
        if args.px_height % 2 != 0:
            raise GlasgowAppletError(
                f"Panel height must be even; the panel is scanned as two "
                f"halves, not {args.px_height}")
        if args.expose_delay < 0:
            raise GlasgowAppletError(
                f"Exposure delay must not be negative, not {args.expose_delay}")
        if args.pattern_rate < 0:
            raise GlasgowAppletError(
                f"Pattern rate must not be negative, not {args.pattern_rate}")

        num_addr_bits = len(args.addr)
        max_px_height = pow(2, num_addr_bits) * 2
        if args.px_height > max_px_height:
            raise GlasgowAppletError(
                f"Cannot have a vertical panel resolution of {args.px_height} "
                f"with only {num_addr_bits} address bits")

        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            ports = self.assembly.add_port_group(
                rgb1 = args.rgb1,
                rgb2 = args.rgb2,
                addr = args.addr,
                clk  = args.clk,
                lat  = args.lat,
                oe   = args.oe
            )
            self.assembly.add_submodule(VideoHub75OutputGenerator(
                ports=ports,
                px_width=args.px_width,
                px_height=args.px_height,
                expose_delay=args.expose_delay,
                pattern_rate=args.pattern_rate,
            ))

    async def run(self, args):
        pass # no host interface; the pattern generator runs standalone on the FPGA

    @classmethod
    def tests(cls):
        from . import test
        return test.VideoHub75OutputAppletTestCase
