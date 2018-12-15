import logging
import math
from nmigen.compat import *
from nmigen.compat.genlib.cdc import *

from ... import *


class VideoRGBInputSubtarget(Module):
    def __init__(self, rows, columns, vblank, pads, in_fifo, sys_clk_freq):
        rx    = Signal(5)
        gx    = Signal(5)
        bx    = Signal(5)
        dck   = Signal()
        self.specials += [
            MultiReg(pads.r_t.i, rx),
            MultiReg(pads.g_t.i, gx),
            MultiReg(pads.b_t.i, bx),
            MultiReg(pads.dck_t.i, dck)
        ]

        dck_r = Signal()
        stb   = Signal()
        self.sync += [
            dck_r.eq(dck),
            stb.eq(~dck_r & dck)
        ]

        we    = Signal.like(in_fifo.we)
        din   = Signal.like(in_fifo.din)
        ovf   = Signal()
        ovf_c = Signal()
        self.comb += [
            in_fifo.we.eq(we & ~ovf),
            in_fifo.din.eq(din),
        ]
        self.sync += \
            ovf.eq(~ovf_c & (ovf | (we & ~in_fifo.writable)))

        pixel = Signal(15)
        self.sync += \
            If(stb, pixel.eq(Cat(rx, gx, bx)))

        frame = Signal(5)
        f_stb = Signal()
        self.sync += \
            If(f_stb, frame.eq(frame + 1))

        ovf_r = Signal()
        row   = Signal(max=rows)
        col   = Signal(max=columns)
        self.submodules.fsm = ResetInserter()(FSM(reset_state="CAPTURE-ROW"))
        self.fsm.act("CAPTURE-ROW",
            If(stb,
                If(row == 0,
                    ovf_r.eq(ovf),
                    ovf_c.eq(1),
                    f_stb.eq(1),
                    NextState("SKIP-FIRST-PIXEL")
                ).Elif(row == rows,
                    NextValue(row, 0),
                    NextState("REPORT-FRAME")
                ).Else(
                    NextState("REPORT-FRAME")
                )
            )
        )
        self.fsm.act("SKIP-FIRST-PIXEL",
            If(stb,
                NextState("REPORT-FRAME")
            )
        )
        self.fsm.act("REPORT-FRAME",
            din.eq(0x80 | (ovf_r << 7) | (frame << 1) | (row >> 7)),
            we.eq(1),
            NextState("REPORT-ROW")
        )
        self.fsm.act("REPORT-ROW",
            din.eq(row & 0x7f),
            we.eq(1),
            NextState("REPORT-1")
        )
        for (state, offset, nextstate) in (
            ("REPORT-1",  0, "REPORT-2"),
            ("REPORT-2",  5, "REPORT-3"),
            ("REPORT-3", 10, "CAPTURE-PIXEL")
        ):
            self.fsm.act(state,
                din.eq((pixel >> offset) & 0x1f),
                we.eq(1),
                NextState(nextstate)
            )
        self.fsm.act("CAPTURE-PIXEL",
            If(stb,
                If(col == columns - 1,
                    NextValue(col, 0),
                    NextValue(row, row + 1),
                    NextState("CAPTURE-ROW")
                ).Else(
                    NextValue(col, col + 1),
                    NextState("REPORT-1")
                )
            )
        )

        vblank_cyc = math.ceil(vblank * 0.9 * sys_clk_freq) # reset at 90% vblank
        timer      = Signal(max=vblank_cyc)
        self.sync += [
            If(dck,
                If(timer != vblank_cyc,
                    timer.eq(timer + 1)
                )
            ).Else(
                timer.eq(0)
            )
        ]
        self.comb += [
            self.fsm.reset.eq(timer == vblank_cyc),
            # sync.oe.eq(self.fsm.reset),
        ]


class VideoRGBInputApplet(GlasgowApplet, name="video-rgb-input"):
    preview = True
    logger = logging.getLogger(__name__)
    help = "capture video stream from RGB555 LCD bus"
    description = """
    Streams screen contents from a color parallel RGB555 LCD, such as Sharp LQ035Q7DH06.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_build_arguments(parser)
        access.add_pin_set_argument(parser, "r", width=5)
        access.add_pin_set_argument(parser, "g", width=5)
        access.add_pin_set_argument(parser, "b", width=5)
        access.add_pin_argument(parser, "dck")
        parser.add_argument("--rows", type=int,
            help="LCD row count")
        parser.add_argument("--columns", type=int,
            help="LCD column count")
        parser.add_argument("--vblank", type=float,
            help="vertical blanking interval, in us")

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        iface.add_subtarget(VideoRGBInputSubtarget(
            rows=args.rows,
            columns=args.columns,
            vblank=args.vblank,
            pads=iface.get_pads(args, pins=("dck",), pin_sets=("r", "g", "b")),
            in_fifo=iface.get_in_fifo(depth=512 * 30, auto_flush=False),
            sys_clk_freq=target.sys_clk_freq,
        ))

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)

        for _ in range(10):
            sync = 0
            while not (sync & 0x80):
                sync = (await iface.read(1))[0]
            frame = (sync & 0x3e) >> 1
            row   = ((sync & 0x01) << 7) | (await iface.read(1))[0]

            print("frame {} row {}".format(frame, row))

# -------------------------------------------------------------------------------------------------

class VideoRGBInputAppletTestCase(GlasgowAppletTestCase, applet=VideoRGBInputApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--pins-r", "0:4", "--pins-g", "5:9", "--pins-b", "10:14",
                                "--pin-dck", "15", "--columns", "160", "--rows", "144",
                                "--vblank", "960"])
