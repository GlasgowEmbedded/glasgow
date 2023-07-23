import logging
import math
from amaranth import *
from amaranth.lib.cdc import FFSynchronizer

from ... import *


class VideoRGBInputSubtarget(Elaboratable):
    def __init__(self, rows, columns, vblank, pads, in_fifo, sys_clk_freq):
        self.rows = rows
        self.columns = columns
        self.vblank = vblank
        self.pads = pads
        self.in_fifo = in_fifo
        self.sys_clk_freq = sys_clk_freq

    def elaborate(self, platform):
        m = Module()

        rx    = Signal(5)
        gx    = Signal(5)
        bx    = Signal(5)
        dck   = Signal()
        m.submodules += [
            FFSynchronizer(self.pads.r_t.i, rx),
            FFSynchronizer(self.pads.g_t.i, gx),
            FFSynchronizer(self.pads.b_t.i, bx),
            FFSynchronizer(self.pads.dck_t.i, dck)
        ]

        dck_r = Signal()
        stb   = Signal()
        m.d.sync += [
            dck_r.eq(dck),
            stb.eq(~dck_r & dck)
        ]

        w_en    = Signal()
        w_data  = Signal.like(self.in_fifo.w_data)
        ovf   = Signal()
        ovf_c = Signal()
        m.d.comb += [
            self.in_fifo.w_en.eq(w_en & ~ovf),
            self.in_fifo.w_data.eq(w_data),
        ]
        with m.If(ovf_c):
            m.d.sync += ovf.eq(0)
        with m.Elif(w_en & ~self.in_fifo.w_rdy):
            m.d.sync += ovf.eq(1)

        pixel = Signal(15)
        with m.If(stb):
            m.d.sync += pixel.eq(Cat(rx, gx, bx))

        frame = Signal(5)

        ovf_r = Signal()
        row   = Signal(range(self.rows + 1))
        col   = Signal(range(self.columns))
        m.domains.fsm = ClockDomain()
        with m.FSM(domain="fsm"):
            with m.State("CAPTURE-ROW"):
                with m.If(stb):
                    with m.If(row == 0):
                        m.d.sync += [
                            ovf_r.eq(ovf),
                            frame.eq(frame + 1)
                        ]
                        m.d.comb += [
                            ovf_c.eq(1),
                        ]
                        m.next = "SKIP-FIRST-PIXEL"
                    with m.Elif(row == self.rows):
                        m.d.fsm += row.eq(0)
                        m.next = "REPORT-FRAME"
                    with m.Else():
                        m.next = "REPORT-FRAME"
            with m.State("SKIP-FIRST-PIXEL"):
                with m.If(stb):
                    m.next = "REPORT-FRAME"
            with m.State("REPORT-FRAME"):
                m.d.comb += [
                    w_data.eq(0x80 | (ovf_r << 6) | (frame << 1) | (row >> 7)),
                    w_en.eq(1),
                ]
                m.next = "REPORT-ROW"
            with m.State("REPORT-ROW"):
                m.d.comb += [
                    w_data.eq(row & 0x7f),
                    w_en.eq(1),
                ]
                m.next = "REPORT-1"
            for (state, offset, nextstate) in (
                ("REPORT-1",  0, "REPORT-2"),
                ("REPORT-2",  5, "REPORT-3"),
                ("REPORT-3", 10, "CAPTURE-PIXEL")
            ):
                with m.State(state):
                    m.d.comb += [
                        w_data.eq((pixel >> offset) & 0x1f),
                        w_en.eq(1),
                    ]
                    m.next = nextstate
            with m.State("CAPTURE-PIXEL"):
                with m.If(stb):
                    with m.If(col == self.columns - 1):
                        m.d.fsm += [
                            col.eq(0),
                            row.eq(row + 1),
                        ]
                        m.next = "CAPTURE-ROW"
                    with m.Else():
                        m.d.fsm += col.eq(col + 1),
                        m.next = "REPORT-1"

        vblank_cyc = math.ceil(self.vblank * 0.9 * self.sys_clk_freq) # reset at 90% vblank
        timer      = Signal(range(vblank_cyc))
        with m.If(dck):
            with m.If(timer != vblank_cyc):
                m.d.sync += timer.eq(timer + 1)
        with m.Else():
            m.d.sync += timer.eq(0)

        m.d.comb += [
            ResetSignal("fsm").eq((timer == vblank_cyc) | ResetSignal("sync")),
            ClockSignal("fsm").eq(ResetSignal("sync")),
        ]

        return m


class VideoRGBInputApplet(GlasgowApplet):
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
                                "--vblank", "960e-6"])
