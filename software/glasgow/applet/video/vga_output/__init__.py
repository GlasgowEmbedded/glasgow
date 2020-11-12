import logging
from nmigen import *
from nmigen.hdl.cd import ClockDomain
from nmigen.hdl.rec import Record

from ....gateware.pads import *
from ....gateware.pll import *
from ... import *


class VGAOutput(Elaboratable):
    def __init__(self, pads):
        self.pads = pads

        self.hs = Signal()
        self.vs = Signal()
        self.r  = Signal()
        self.g  = Signal()
        self.b  = Signal()

    def elaborate(self, platform):
        m = Module()

        m.d.comb += [
            self.pads.hs_t.oe.eq(1),
            self.pads.hs_t.o.eq(self.hs),
            self.pads.vs_t.oe.eq(1),
            self.pads.vs_t.o.eq(self.vs),
            self.pads.r_t.oe.eq(1),
            self.pads.r_t.o.eq(self.r),
            self.pads.g_t.oe.eq(1),
            self.pads.g_t.o.eq(self.g),
            self.pads.b_t.oe.eq(1),
            self.pads.b_t.o.eq(self.b),
        ]

        return m


class VGAOutputSubtarget(Elaboratable):
    def __init__(self, pads, h_front, h_sync, h_back, h_active, v_front, v_sync, v_back, v_active, pix_clk_freq):
        self.pads = pads
        self.h_front = h_front
        self.h_sync = h_sync
        self.h_back = h_back
        self.h_active = h_active
        self.v_front = v_front
        self.v_sync = v_sync
        self.v_back = v_back
        self.v_active, = v_active,
        self.pix_clk_freq = pix_clk_freq

    def elaborate(self, platform):
        m = Module()

        m.submodules.output = output = VGAOutput(self.pads)

        m.domains.pix = cd_pix = ClockDomain(reset_less=True)
        m.submodules += PLL(f_in=platform.default_clk_frequency, f_out=self.pix_clk_freq, odomain="pix")
        platform.add_clock_constraint(cd_pix.clk, self.pix_clk_freq)

        h_total = self.h_front + self.h_sync + self.h_back + self.h_active
        v_total = self.v_front + self.v_sync + self.v_back + self.v_active

        h_ctr = Signal(range(h_total))
        v_ctr = Signal(range(v_total))
        pix = Record([
            ("r", 1),
            ("g", 1),
            ("b", 1),
        ])

        h_en  = Signal()
        v_en  = Signal()
        h_stb = Signal()
        v_stb = Signal()

        m.d.comb += [
            h_stb.eq(h_ctr == self.h_active),
            v_stb.eq(h_stb & (v_ctr == self.v_active)),
        ]

        with m.If(h_ctr == h_total - 1):
            with m.If(v_ctr == v_total - 1):
                m.d.pix += v_ctr.eq(0)
            with m.Else():
                m.d.pix += v_ctr.eq(v_ctr + 1)
            m.d.pix += h_ctr.eq(0)
        with m.Else():
            m.d.pix += h_ctr.eq(h_ctr + 1)

        with m.If(h_ctr == 0):
            m.d.pix += h_en.eq(1)
        with m.Elif(h_ctr == self.h_active):
            m.d.pix += h_en.eq(0)
        with m.Elif(h_ctr == self.h_active + self.h_front):
            m.d.pix += output.hs.eq(1)
        with m.Elif(h_ctr == self.h_active + self.h_front + self.h_sync):
            m.d.pix += output.hs.eq(0)

        with m.If(v_ctr == 0):
            m.d.pix += v_en.eq(1)
        with m.Elif(v_ctr == self.v_active):
            m.d.pix += v_en.eq(0)
        with m.Elif(v_ctr == self.v_active + self.v_front):
            m.d.pix += output.vs.eq(1)
        with m.Elif(v_ctr == self.v_active + self.v_front + self.v_sync):
            m.d.pix += output.vs.eq(0)

        with m.If(v_en & h_en):
            m.d.pix += [
                output.r.eq(pix.r),
                output.g.eq(pix.g),
                output.b.eq(pix.b),
            ]
        with m.Else():
            m.d.pix += [
                output.r.eq(0),
                output.g.eq(0),
                output.b.eq(0),
            ]

        m.d.comb += \
            Cat(pix.r, pix.g, pix.b) \
                .eq(h_ctr[5:] + v_ctr[5:])

        return m


# video video graphics adapter is dumb, so the applet is just called VGAOutputApplet
class VGAOutputApplet(GlasgowApplet, name="video-vga-output"):
    logger = logging.getLogger(__name__)
    help = "display video via VGA"
    description = """
    Output a test pattern on a VGA output.

    To configure this applet for a certain video mode, it is necessary to use a mode line, such as:
        * 640x480 60 Hz: -p 25.175 -hf 16 -hs 96 -hb 48 -ha 640 -vf 10 -vs 2 -vb 33 -va 480

    The VGA interface uses 75 Ohm termination, and the analog signals are referenced to 0.7 V.
    As such, the signals should be connected as follows if port voltage is set to 3.3 V:
        * hs --[ 100R ]-- HSYNC
        * vs --[ 100R ]-- VSYNC
        * r ---[ 350R ]-- RED
        * g ---[ 350R ]-- GREEN
        * b ---[ 350R ]-- BLUE
    """

    __pins = ("hs", "vs", "r", "g", "b")

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        for pin in cls.__pins:
            access.add_pin_argument(parser, pin, default=True)

        parser.add_argument(
            "-p", "--pix-clk-freq", metavar="FREQ", type=float, default=25.175,
            help="set pixel clock to FREQ MHz (default: %(default).3f)")

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
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        subtarget = iface.add_subtarget(VGAOutputSubtarget(
            pads=iface.get_pads(args, pins=self.__pins),
            h_front=args.h_front,
            h_sync=args.h_sync,
            h_back=args.h_back,
            h_active=args.h_active,
            v_front=args.v_front,
            v_sync=args.v_sync,
            v_back=args.v_back,
            v_active=args.v_active,
            pix_clk_freq=args.pix_clk_freq * 1e6,
        ))
        return subtarget

    async def run(self, device, args):
        return await device.demultiplexer.claim_interface(self, self.mux_interface, args)

# -------------------------------------------------------------------------------------------------

class VGAOutputAppletTestCase(GlasgowAppletTestCase, applet=VGAOutputApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--port", "B"])
