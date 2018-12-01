import logging
from migen import *

from .. import *
from ...gateware.pads import *
from ...gateware.pll import *


class VGAOutput(Module):
    def __init__(self, pads):
        self.hs = Signal()
        self.vs = Signal()
        self.r  = Signal()
        self.g  = Signal()
        self.b  = Signal()

        ###

        self.comb += [
            pads.hs_t.oe.eq(1),
            pads.hs_t.o.eq(self.hs),
            pads.vs_t.oe.eq(1),
            pads.vs_t.o.eq(self.vs),
            pads.r_t.oe.eq(1),
            pads.r_t.o.eq(self.r),
            pads.g_t.oe.eq(1),
            pads.g_t.o.eq(self.g),
            pads.b_t.oe.eq(1),
            pads.b_t.o.eq(self.b),
        ]


class VGAOutputSubtarget(Module):
    def __init__(self, pads, v_front, v_sync, v_back, v_active, h_front, h_sync, h_back, h_active,
                 sys_clk_freq, pix_clk_freq):
        self.submodules.output = output = VGAOutput(pads)

        self.clock_domains.cd_pix = ClockDomain(reset_less=True)
        self.specials += PLL(f_in=sys_clk_freq, f_out=pix_clk_freq, odomain="pix")

        h_total = h_front + h_sync + h_back + h_active
        v_total = v_front + v_sync + v_back + v_active

        self.h_ctr = h_ctr = Signal(max=h_total)
        self.v_ctr = v_ctr = Signal(max=v_total)
        self.pix   = pix   = Record([
            ("r", 1),
            ("g", 1),
            ("b", 1),
        ])

        h_en = Signal()
        v_en = Signal()
        self.sync.pix += [
            If(h_ctr == h_total - 1,
                If(v_ctr == v_total - 1,
                    v_ctr.eq(0)
                ).Else(
                    v_ctr.eq(v_ctr + 1)
                ),
                h_ctr.eq(0),
            ).Else(
                h_ctr.eq(h_ctr + 1)
            ),
            If(h_ctr == 0,
                h_en.eq(1),
            ).Elif(h_ctr == h_active,
                h_en.eq(0),
            ).Elif(h_ctr == h_active + h_front,
                output.hs.eq(1)
            ).Elif(h_ctr == h_active + h_front + h_sync,
                output.hs.eq(0)
            ),
            If(v_ctr == 0,
                v_en.eq(1),
            ).Elif(v_ctr == v_active,
                v_en.eq(0),
            ).Elif(v_ctr == v_active + v_front,
                output.vs.eq(1)
            ).Elif(v_ctr == v_active + v_front + v_sync,
                output.vs.eq(0)
            ),
            If(v_en & h_en,
                output.r.eq(pix.r),
                output.g.eq(pix.g),
                output.b.eq(pix.b),
            ).Else(
                output.r.eq(0),
                output.g.eq(0),
                output.b.eq(0),
            )
        ]


class VGAOutputApplet(GlasgowApplet, name="vga-output"):
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

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        subtarget = iface.add_subtarget(VGAOutputSubtarget(
            pads=iface.get_pads(args, pins=self.__pins),
            v_front=args.v_front,
            v_sync=args.v_sync,
            v_back=args.v_back,
            v_active=args.v_active,
            h_front=args.h_front,
            h_sync=args.h_sync,
            h_back=args.h_back,
            h_active=args.h_active,
            sys_clk_freq=target.sys_clk_freq,
            pix_clk_freq=args.pix_clk_freq * 1e6,
        ))
        target.platform.add_period_constraint(subtarget.cd_pix.clk, 1e3 / args.pix_clk_freq)

        subtarget.comb += \
            Cat(subtarget.pix.r, subtarget.pix.g, subtarget.pix.b) \
                .eq(subtarget.h_ctr[5:] + subtarget.v_ctr[5:])

    async def run(self, device, args):
        return await device.demultiplexer.claim_interface(self, self.mux_interface, args)

# -------------------------------------------------------------------------------------------------

class VGAOutputAppletTestCase(GlasgowAppletTestCase, applet=VGAOutputApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--port", "B"])
