import logging
from amaranth import *
from amaranth.lib import data, io

from ....gateware.pll import *
from ... import *


class VGAOutputSubtarget(Elaboratable):
    def __init__(self, ports, h_front, h_sync, h_back, h_active, v_front, v_sync, v_back, v_active,
                 pix_clk_freq):
        self.ports    = ports

        self.h_front  = h_front
        self.h_sync   = h_sync
        self.h_back   = h_back
        self.h_active = h_active
        self.v_front  = v_front
        self.v_sync   = v_sync
        self.v_back   = v_back
        self.v_active = v_active

        self.pix_clk_freq = pix_clk_freq

    def elaborate(self, platform):
        m = Module()

        m.submodules.hs = hs_buf = io.FFBuffer("o", self.ports.hs)
        m.submodules.vs = vs_buf = io.FFBuffer("o", self.ports.vs)
        m.submodules.r  = r_buf  = io.FFBuffer("o", self.ports.r)
        m.submodules.g  = g_buf  = io.FFBuffer("o", self.ports.g)
        m.submodules.b  = b_buf  = io.FFBuffer("o", self.ports.b)

        m.domains.pix = cd_pix = ClockDomain()
        m.submodules += PLL(f_in=platform.default_clk_frequency, f_out=self.pix_clk_freq, odomain="pix")

        h_ctr = Signal(range(self.h_active + self.h_front + self.h_sync + self.h_back))
        v_ctr = Signal(range(self.v_active + self.v_front + self.v_sync + self.v_back))
        pix = Signal(data.StructLayout({"r": 1, "g": 1, "b": 1}))

        h_en  = Signal()
        v_en  = Signal()

        m.d.pix += h_ctr.eq(h_ctr + 1)
        with m.If(h_ctr == (self.h_active) - 1):
            m.d.pix += h_en.eq(0)
        with m.Elif(h_ctr == (self.h_active + self.h_front) - 1):
            m.d.pix += hs_buf.o.eq(1)
        with m.Elif(h_ctr == (self.h_active + self.h_front + self.h_sync) - 1):
            m.d.pix += hs_buf.o.eq(0)
        with m.Elif(h_ctr == (self.h_active + self.h_front + self.h_sync + self.h_back) - 1):
            m.d.pix += h_en.eq(1)
            m.d.pix += h_ctr.eq(0)

            m.d.pix += v_ctr.eq(v_ctr + 1)
            with m.If(v_ctr == (self.v_active - 1)):
                m.d.pix += v_en.eq(0)
            with m.Elif(v_ctr == (self.v_active + self.v_front - 1)):
                m.d.pix += vs_buf.o.eq(1)
            with m.Elif(v_ctr == (self.v_active + self.v_front + self.v_sync - 1)):
                m.d.pix += vs_buf.o.eq(0)
            with m.Elif(v_ctr == (self.v_active + self.v_front + self.v_sync + self.v_back - 1)):
                m.d.pix += v_en.eq(1)
                m.d.pix += v_ctr.eq(0)

        with m.If(v_en & h_en):
            m.d.pix += [
                r_buf.o.eq(pix.r),
                g_buf.o.eq(pix.g),
                b_buf.o.eq(pix.b),
            ]
        with m.Else():
            m.d.pix += [
                r_buf.o.eq(0),
                g_buf.o.eq(0),
                b_buf.o.eq(0),
            ]

        m.d.comb += \
            Cat(pix.r, pix.g, pix.b) \
                .eq(h_ctr[5:] + v_ctr[5:])

        return m


# video video graphics adapter is dumb, so the applet is just called VGAOutputApplet
class VGAOutputApplet(GlasgowApplet):
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
    """

    __default_refresh_rate = 60.0

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_argument(parser, "hs", default=True)
        access.add_pin_argument(parser, "vs", default=True)
        access.add_pin_argument(parser, "r", default=True)
        access.add_pin_argument(parser, "g", default=True)
        access.add_pin_argument(parser, "b", default=True)

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

    def build(self, target, args, test_pattern=True):
        h_dots  = args.h_active + args.h_front + args.h_sync + args.h_back
        v_lines = args.v_active + args.v_front + args.v_sync + args.v_back
        dots_per_frame = h_dots * v_lines
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

        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        subtarget = iface.add_subtarget(VGAOutputSubtarget(
            ports=iface.get_port_group(
                hs = args.pin_hs,
                vs = args.pin_vs,
                r  = args.pin_r,
                g  = args.pin_g,
                b  = args.pin_b
            ),
            h_front=args.h_front,
            h_sync=args.h_sync,
            h_back=args.h_back,
            h_active=args.h_active,
            v_front=args.v_front,
            v_sync=args.v_sync,
            v_back=args.v_back,
            v_active=args.v_active,
            pix_clk_freq=pix_clk_freq,
        ))
        return subtarget

    async def run(self, device, args):
        return await device.demultiplexer.claim_interface(self, self.mux_interface, args)

    async def interact(self, device, args, vga):
        pass

    @classmethod
    def tests(cls):
        from . import test
        return test.VGAOutputAppletTestCase
