import os
import asyncio
import logging
import argparse
from nmigen.compat import *

from ... import *
from ..vga_output import VGAOutputApplet
from .cpu import *


class VGATerminalSubtarget(Module):
    def __init__(self, vga, h_active, v_active, font_data, font_width, font_height, blink_cyc,
                 out_fifo, char_mem_init=[], attr_mem_init=[]):
        char_width  = (h_active // font_width)
        char_height = (v_active // font_height)

        char_mem = Memory(width=8, depth=char_width * char_height, init=char_mem_init)
        attr_mem = Memory(width=5, depth=char_width * char_height, init=attr_mem_init)
        self.specials += [char_mem, attr_mem]

        char_port = char_mem.get_port(has_re=True, clock_domain="pix")
        attr_port = attr_mem.get_port(has_re=True, clock_domain="pix")
        self.specials += [char_port, attr_port]

        char_ctr   = Signal(max=char_mem.depth)
        char_l_ctr = Signal.like(char_ctr)
        char_data  = Signal.like(char_port.dat_r)
        attr_data  = Signal.like(attr_port.dat_r)
        self.comb += [
            char_port.re.eq(1),
            char_port.adr.eq(char_ctr),
            char_data.eq(char_port.dat_r),
            attr_port.re.eq(1),
            attr_port.adr.eq(char_ctr),
            attr_data.eq(attr_port.dat_r),
        ]

        font_mem = Memory(width=font_width, depth=font_height * 256, init=font_data)
        self.specials += font_mem

        font_rdport = font_mem.get_port(has_re=True, clock_domain="pix")
        self.specials += font_rdport

        font_h_ctr = Signal(max=font_width)
        font_v_ctr = Signal(max=font_height)
        font_line  = Signal(font_width)
        font_shreg = Signal.like(font_line)
        attr_reg   = Signal.like(attr_data)
        undrl_reg  = Signal()
        self.comb += [
            font_rdport.re.eq(1),
            font_rdport.adr.eq(char_data * font_height + font_v_ctr),
            font_line.eq(Cat(reversed([font_rdport.dat_r[n] for n in range(font_width)])))
        ]
        self.sync.pix += [
            If(vga.v_stb,
                char_ctr.eq(0),
                char_l_ctr.eq(0),
                font_v_ctr.eq(0),
                font_h_ctr.eq(0),
            ).Elif(vga.h_stb & vga.v_en,
                If(font_v_ctr == font_height - 1,
                    char_l_ctr.eq(char_ctr),
                    font_v_ctr.eq(0),
                ).Else(
                    char_ctr.eq(char_l_ctr),
                    font_v_ctr.eq(font_v_ctr + 1),
                ),
                font_h_ctr.eq(0),
            ).Elif(vga.v_en & vga.h_en,
                If(font_h_ctr == 0,
                    char_ctr.eq(char_ctr + 1)
                ),
                If(font_h_ctr == font_width - 1,
                    font_h_ctr.eq(0),
                ).Else(
                    font_h_ctr.eq(font_h_ctr + 1),
                )
            ),
            If(~vga.h_en | (font_h_ctr == font_width - 1),
                font_shreg.eq(font_line),
                attr_reg.eq(attr_data),
                undrl_reg.eq(font_v_ctr == font_height - 1),
            ).Else(
                font_shreg.eq(font_shreg[1:])
            )
        ]

        blink_ctr = Signal(max=blink_cyc)
        blink_reg = Signal()
        self.sync.pix += [
            If(blink_ctr == blink_cyc - 1,
                blink_ctr.eq(0),
                blink_reg.eq(~blink_reg),
            ).Else(
                blink_ctr.eq(blink_ctr + 1),
            )
        ]

        pix_fg = Signal()
        self.comb += [
            pix_fg.eq((font_shreg[0] | (undrl_reg & attr_reg[3])) & (~attr_reg[4] | blink_reg)),
            vga.pix.r.eq(pix_fg & attr_reg[0]),
            vga.pix.g.eq(pix_fg & attr_reg[1]),
            vga.pix.b.eq(pix_fg & attr_reg[2]),
        ]

        self.submodules.cpu = ClockDomainsRenamer("pix")(BonelessCPU(
            char_mem=char_mem,
            attr_mem=attr_mem,
            out_fifo=out_fifo,
            code_init=[
                L("clear"),
                    LDIW(-char_width * char_height),
                    STB(),
                L("clear-loop"),
                    LDI(0),
                    STMC(),
                    ADJ(1),
                    LDP(),
                    ADDB(),
                    JN("clear-loop"),
                    LDI(0),
                    STP(),
                L("recv"),
                    LDF(),
                    JE(0x0a, "lf"),
                    JE(0x0d, "cr"),
                L("echo"),
                    LDIH(0b111),
                    STMC(),
                    STMA(),
                    ADJ(1),
                    J("scroll-chk"),
                L("lf"),
                    ADJ(char_width),
                    J("scroll-chk"),
                L("cr"),
                    LDP(),
                L("cr-find-col"),
                    JL(char_width, "cr-sub-col"),
                    ADDI(-char_width),
                    J("cr-find-col"),
                L("cr-sub-col"),
                    NEG(),
                    STB(),
                    LDP(),
                    ADDB(),
                    STP(),
                    J("recv"),
                L("scroll-chk"),
                    LDIW(-char_width * char_height),
                    STB(),
                    LDP(),
                    ADDB(),
                    JN("recv"),
                L("scroll"),
                    ADJ(-char_width),
                    LDP(),
                    STC(),
                    LDIW(-char_width * (char_height - 1)),
                    STB(),
                    LDI(0),
                    STP(),
                L("scroll-loop"),
                    ADJ(char_width),
                    LDMC(),
                    LDMA(),
                    ADJ(-char_width),
                    STMC(),
                    STMA(),
                    ADJ(1),
                    LDP(),
                    ADDB(),
                    JN("scroll-loop"),
                    LDC(),
                L("scroll-find-col"),
                    JL(char_width, "scroll-sub-col"),
                    ADDI(-char_width),
                    J("scroll-find-col"),
                L("scroll-sub-col"),
                    NEG(),
                    STB(),
                    LDC(),
                    ADDB(),
                    STP(),
                    LDIW(-char_width * char_height),
                    STB(),
                L("scroll-blank-row"),
                    LDI(0),
                    STMC(),
                    ADJ(1),
                    LDP(),
                    ADDB(),
                    JN("scroll-blank-row"),
                    LDC(),
                    STP(),
                    J("recv"),
            ]
        ))


# video video graphics adapter is dumb, so the applet is just called VGATerminalApplet
class VGATerminalApplet(VGAOutputApplet, name="video-vga-terminal"):
    preview = True
    logger = logging.getLogger(__name__)
    help = "emulate a teleprinter using a VGA monitor"
    description = """
    TBD
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        g_font = parser.add_mutually_exclusive_group()
        g_font.add_argument(
            "-fb", "--font-builtin", metavar="FILE", type=str, default="ibmvga8x16",
            choices=["ibmvga8x16", "ibmvga8x14", "ibmvga8x8", "ibmvga8x8hi"],
            help="load builtin font NAME (default: %(default)s, one of: %(choices)s)")
        g_font.add_argument(
            "-fd", "--font-data", metavar="FILE", type=argparse.FileType("rb"),
            help="load font ROM from FILE")
        parser.add_argument(
            "-fw", "--font-width", metavar="PX", type=int, default=8,
            help="set font width to PX pixels (default: %(default)s)")
        parser.add_argument(
            "-fh", "--font-height", metavar="PX", type=int, default=16,
            help="set font height to PX pixels (default: %(default)s)")

    def build(self, target, args):
        vga = super().build(target, args, test_pattern=False)
        iface = self.mux_interface

        if args.font_data:
            font_data = args.font_data.read()
        else:
            font_path = os.path.join(os.path.dirname(__file__), args.font_builtin + ".bin")
            with open(font_path, "rb") as f:
                font_data = f.read()

        subtarget = iface.add_subtarget(VGATerminalSubtarget(
            vga=vga,
            h_active=args.h_active,
            v_active=args.v_active,
            font_data=font_data,
            font_width=args.font_width,
            font_height=args.font_height,
            blink_cyc=int(args.pix_clk_freq * 1e6 / 2),
            out_fifo=iface.get_out_fifo(clock_domain=vga.cd_pix),
        ))

    async def interact(self, device, args, term_iface):
        import pty

        master, slave = pty.openpty()
        self.logger.info("PTY: opened %s", os.ttyname(slave))

        while True:
            data = await asyncio.get_event_loop().run_in_executor(None,
                lambda: os.read(master, 1024))
            await term_iface.write(data)
            await term_iface.flush()

# -------------------------------------------------------------------------------------------------

class VGATerminalAppletTestCase(GlasgowAppletTestCase, applet=VGATerminalApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--port", "B"])
