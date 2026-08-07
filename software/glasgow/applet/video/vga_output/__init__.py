from dataclasses import dataclass
from typing import assert_never

from amaranth import *
from amaranth.lib import enum, data, wiring, io
from amaranth.lib.wiring import Out

from glasgow.support import logging
from glasgow.gateware import pll
from glasgow.applet import GlasgowAppletError, GlasgowAppletV2


class VGATestPattern(enum.Enum):
    Quilt = "quilt"
    Rect  = "rect"
    Grid  = "grid"
    Flag  = "flag"

    def __str__(self):
        return self.value


@dataclass(frozen=True)
class Modeline:
    h_front_px:     int
    h_sync_px:      int
    h_back_px:      int
    h_active_px:    int
    v_front_lines:  int
    v_sync_lines:   int
    v_back_lines:   int
    v_active_lines: int

    @property
    def h_total_px(self):
        return self.h_active_px + self.h_front_px + self.h_sync_px + self.h_back_px

    @property
    def v_total_lines(self):
        return self.v_active_lines + self.v_front_lines + \
               self.v_sync_lines + self.v_back_lines


class VGAOutputGenerator(wiring.Component):
    hs:  Out(1)
    vs:  Out(1)
    rgb: Out(data.StructLayout({"r": 1, "g": 1, "b": 1}))

    def __init__(self, modeline, test_pattern=VGATestPattern.Quilt):
        self.modeline    = modeline
        self.test_pattern = test_pattern

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        h_ctr = Signal(range(self.modeline.h_total_px))
        v_ctr = Signal(range(self.modeline.v_total_lines))

        m.d.sync += h_ctr.eq(h_ctr + 1)
        with m.If(h_ctr == self.modeline.h_total_px - 1):
            m.d.sync += [
                h_ctr.eq(0),
                v_ctr.eq(Mux(v_ctr == self.modeline.v_total_lines - 1, 0, v_ctr + 1)),
            ]

        pix = Signal(data.StructLayout({"r": 1, "g": 1, "b": 1}))
        match self.test_pattern:
            case VGATestPattern.Quilt:
                m.d.comb += pix.eq(h_ctr[5:] + v_ctr[5:])
            case VGATestPattern.Rect:
                with m.If(
                    (h_ctr == 0) |
                    (v_ctr == 0) |
                    (h_ctr == self.modeline.h_active_px - 1) |
                    (v_ctr == self.modeline.v_active_lines - 1)
                ):
                    m.d.comb += pix.eq(0b111)
            case VGATestPattern.Grid:
                with m.If((h_ctr[:5] == 0) | (v_ctr[:5] == 0)):
                    m.d.comb += pix.eq(0b111)
            case VGATestPattern.Flag:
                phase = Signal(range(5))
                for index in range(1, 5):
                    stripe_start = (index * self.modeline.v_active_lines + 4) // 5
                    with m.If(v_ctr >= stripe_start):
                        m.d.comb += phase.eq(index)
                m.d.comb += pix.eq(Array([0b110, 0b101, 0b111, 0b101, 0b110])[phase])
            case _ as unreachable:
                assert_never(unreachable)

        h_active = h_ctr < self.modeline.h_active_px
        v_active = v_ctr < self.modeline.v_active_lines
        m.d.comb += [
            self.hs.eq(
                (h_ctr >= self.modeline.h_active_px + self.modeline.h_front_px) &
                (h_ctr < self.modeline.h_active_px + self.modeline.h_front_px +
                 self.modeline.h_sync_px)
            ),
            self.vs.eq(
                (v_ctr >= self.modeline.v_active_lines + self.modeline.v_front_lines) &
                (v_ctr < self.modeline.v_active_lines + self.modeline.v_front_lines +
                 self.modeline.v_sync_lines)
            ),
            self.rgb.eq(Mux(h_active & v_active, pix, 0)),
        ]

        return m


class VGAOutputComponent(Elaboratable):
    def __init__(self, ports, modeline, pix_clk_freq, test_pattern=VGATestPattern.Quilt):
        self.ports = ports
        self.modeline = modeline
        self.pix_clk_freq = pix_clk_freq
        self.test_pattern = test_pattern

    def elaborate(self, platform):
        m = Module()

        m.submodules.hs = hs_buf = io.FFBuffer("o", self.ports.hs, o_domain="pix")
        m.submodules.vs = vs_buf = io.FFBuffer("o", self.ports.vs, o_domain="pix")
        m.submodules.r  = r_buf  = io.FFBuffer("o", self.ports.r,  o_domain="pix")
        m.submodules.g  = g_buf  = io.FFBuffer("o", self.ports.g,  o_domain="pix")
        m.submodules.b  = b_buf  = io.FFBuffer("o", self.ports.b,  o_domain="pix")

        plan = pll.ClockPlan(1 / platform.default_clk_frequency)
        m.domains.pix = plan.add_domain(pll.Channel(period=1 / self.pix_clk_freq, tolerance=0.01))
        m.submodules += plan.create(platform)

        m.submodules.generator = generator = DomainRenamer("pix")(VGAOutputGenerator(
            modeline=self.modeline,
            test_pattern=self.test_pattern,
        ))
        m.d.comb += [
            hs_buf.o.eq(generator.hs),
            vs_buf.o.eq(generator.vs),
            Cat(r_buf.o, g_buf.o, b_buf.o).eq(generator.rgb),
        ]

        return m


class VGAOutputApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "display video via VGA"
    description = """
    Output a test pattern on a VGA output.

    To configure this applet for a certain video mode, it is possible to use a full mode line,
    such as:
        * 640x480 @ 60 Hz: -p 25.175 -hf 16 -hs 96 -hb 48 -ha 640 -vf 10 -vs 2 -vb 33 -va 480

    Either the pixel clock or the refresh rate must be specified; the other parameter will be
    calculated using the mode line.

    The VGA interface uses 75 Ohm termination, and the analog signals are referenced to 0.7 V.
    As such, the signals should be connected as follows if port voltage is set to 3.3 V:
        * hs --[ 100R ]-- HSYNC
        * vs --[ 100R ]-- VSYNC
        * r ---[ 350R ]-- RED
        * g ---[ 350R ]-- GREEN
        * b ---[ 350R ]-- BLUE

    Horizontal and vertical sync pulses are active-high. Append ``#`` to either pin name to
    select active-low sync, for example: ``--hs A0# --vs A1#``.
    """

    __default_refresh_rate = 60.0

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)

        access.add_pins_argument(parser, "hs", default=True)
        access.add_pins_argument(parser, "vs", default=True)
        access.add_pins_argument(parser, "r", default=True)
        access.add_pins_argument(parser, "g", default=True)
        access.add_pins_argument(parser, "b", default=True)

        p_refresh = parser.add_mutually_exclusive_group()
        p_refresh.add_argument(
            "-p", "--pix-clk-freq", metavar="FREQ", type=float,
            help="set pixel clock to FREQ MHz")
        p_refresh.add_argument(
            "-r", "--refresh-rate", metavar="FREQ", type=float,
            help=f"set refresh rate to FREQ Hz (default: {cls.__default_refresh_rate:.1f})")

        parser.add_argument(
            "-hf", "--h-front", metavar="N", type=int, default=16,
            help="set horizontal front porch to N pixel clocks (default: %(default)s)")
        parser.add_argument(
            "-hs", "--h-sync", metavar="N", type=int, default=96,
            help="set horizontal sync time to N pixel clocks (default: %(default)s)")
        parser.add_argument(
            "-hb", "--h-back", metavar="N", type=int, default=48,
            help="set horizontal back porch to N pixel clocks (default: %(default)s)")
        parser.add_argument(
            "-ha", "--h-active", metavar="N", type=int, default=640,
            help="set horizontal resolution to N pixel clocks (default: %(default)s)")

        parser.add_argument(
            "-vf", "--v-front", metavar="N", type=int, default=10,
            help="set vertical front porch to N line clocks (default: %(default)s)")
        parser.add_argument(
            "-vs", "--v-sync", metavar="N", type=int, default=2,
            help="set vertical sync time to N line clocks (default: %(default)s)")
        parser.add_argument(
            "-vb", "--v-back", metavar="N", type=int, default=33,
            help="set vertical back porch to N line clocks (default: %(default)s)")
        parser.add_argument(
            "-va", "--v-active", metavar="N", type=int, default=480,
            help="set vertical resolution to N line clocks (default: %(default)s)")

        parser.add_argument(
            "--pattern", metavar="PATTERN", type=VGATestPattern,
            choices=list(VGATestPattern), default=VGATestPattern.Quilt,
            help="use the specific test pattern (choices: %(choices)s, default: %(default)s)")

    def build(self, args):
        for name in ("h_active", "h_sync", "v_active", "v_sync"):
            value = getattr(args, name)
            if value <= 0:
                raise GlasgowAppletError(
                    f"{name.replace('_', ' ')} must be positive, not {value}")
        for name in ("h_front", "h_back", "v_front", "v_back"):
            value = getattr(args, name)
            if value < 0:
                raise GlasgowAppletError(
                    f"{name.replace('_', ' ')} must not be negative, not {value}")
        if args.pix_clk_freq is not None and args.pix_clk_freq <= 0:
            raise GlasgowAppletError(
                f"pixel clock frequency must be positive, not {args.pix_clk_freq}")
        if args.refresh_rate is not None and args.refresh_rate <= 0:
            raise GlasgowAppletError(
                f"refresh rate must be positive, not {args.refresh_rate}")

        modeline = Modeline(
            h_front_px=args.h_front,
            h_sync_px=args.h_sync,
            h_back_px=args.h_back,
            h_active_px=args.h_active,
            v_front_lines=args.v_front,
            v_sync_lines=args.v_sync,
            v_back_lines=args.v_back,
            v_active_lines=args.v_active,
        )
        dots_per_frame = modeline.h_total_px * modeline.v_total_lines
        if args.pix_clk_freq is not None:
            pix_clk_freq = args.pix_clk_freq * 1e6
            refresh_rate = pix_clk_freq / dots_per_frame
        else:
            refresh_rate = args.refresh_rate
            if refresh_rate is None:
                refresh_rate = self.__default_refresh_rate
            pix_clk_freq = refresh_rate * dots_per_frame

        self.logger.info("%dx%d @ %.1f Hz: pixel clock %.3f MHz (ideal)",
            args.h_active, args.v_active, refresh_rate, pix_clk_freq / 1e6)

        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.assembly.add_submodule(VGAOutputComponent(
                ports=self.assembly.add_port_group(
                    hs=args.hs,
                    vs=args.vs,
                    r=args.r,
                    g=args.g,
                    b=args.b,
                ),
                modeline=modeline,
                pix_clk_freq=pix_clk_freq,
                test_pattern=args.pattern,
            ))

    async def run(self, args):
        pass # no host interface; nothing to do

    @classmethod
    def tests(cls):
        from . import test
        return test.VGAOutputAppletTestCase
