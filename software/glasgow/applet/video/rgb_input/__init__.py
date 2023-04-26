import logging
import math
from amaranth import *
from amaranth.lib.cdc import FFSynchronizer
from amaranth.hdl.rec import Record

from ... import *

_bus_layout = [
    ("r", 5),
    ("g", 5),
    ("b", 5),
    ("dck", 1),
]

class VideoRGBCaptureMachine(Elaboratable):
    def __init__(self, bus, in_fifo, rows, columns):
        """
        Core of the capture machinery. Takes color data from ``bus`` and
        delivers it to ``in_fifo``.

        Expects the signals arriving on ``bus`` to be synchronized to the
        ``sync`` domain already.
        """
        self.bus = bus
        self.in_fifo = in_fifo
        self.rows = rows
        self.columns = columns

    def elaborate(self, platform):
        m = Module()

        # Strobe based on the external data clock
        dck_r = Signal()
        stb   = Signal()
        m.d.sync += [
            dck_r.eq(self.bus.dck),
            stb.eq(~dck_r & self.bus.dck)
        ]

        # bind to the input fifo, tracking overflow
        we    = Signal.like(self.in_fifo.we)
        din   = Signal.like(self.in_fifo.din)
        ovf   = Signal()
        ovf_c = Signal()
        m.d.comb += [
            self.in_fifo.we.eq(we & ~ovf),
            self.in_fifo.din.eq(din),
        ]
        m.d.sync += \
            ovf.eq(~ovf_c & (ovf | (we & ~self.in_fifo.writable)))

        # frame counter and corresponding strobe
        frame = Signal(5)
        f_stb = Signal()
        with m.If(f_stb):
            m.d.sync += frame.eq(frame + 1)

        # state machine registers
        # previous frame overflow indicator and row/column counters
        ovf_r = Signal()
        row   = Signal(range(self.rows))
        col   = Signal(range(self.columns))

        # when our internal strobe goes high, latch a pixel
        pixel = Signal(15)
        with m.If(stb):
            m.d.sync += pixel.eq(Cat(self.bus.r, self.bus.g, self.bus.b))

        with m.FSM(reset="CAPTURE-ROW") as fsm:
            # initial state: begin capture of a row, clearing the overflow flag
            # and skipping the first pixel of the first row because we latch
            # pixels 1 clock behind the data line.
            with m.State("CAPTURE-ROW"):
                with m.If(stb):
                    with m.If(row == 0):
                        m.d.comb += [
                            ovf_r.eq(ovf),
                            ovf_c.eq(1),
                            f_stb.eq(1),
                        ]
                        m.next = "SKIP-FIRST-PIXEL"
                    with m.Elif(row == self.rows):
                        m.d.sync += row.eq(0)
                        m.next = "REPORT-FRAME"
                    with m.Else():
                        m.next= "REPORT-FRAME"
            # single-dclk delay for alignment
            with m.State("SKIP-FIRST-PIXEL"):
                with m.If(stb):
                    m.next = "REPORT-FRAME"
            # send frame marker including frame counter, row counter, and
            # indicator that the previous frame overflowed
            with m.State("REPORT-FRAME"):
                m.d.comb += [
                    din.eq(0x80 | (ovf_r << 7) | (frame << 1) | (row >> 7)),
                    we.eq(1),
                ]
                m.next = "REPORT-ROW"
            # send row start marker
            with m.State("REPORT-ROW"):
                m.d.comb += [
                    din.eq(row & 0x7f),
                    we.eq(1),
                ]
                m.next = ("REPORT-1")
            # use the next 3 clocks to send the 3 color channels
            for (state, offset, nextstate) in (
                ("REPORT-1",  0, "REPORT-2"),
                ("REPORT-2",  5, "REPORT-3"),
                ("REPORT-3", 10, "CAPTURE-PIXEL")
            ):
                with m.State(state):
                    m.d.comb += [
                        din.eq((pixel >> offset) & 0x1f),
                        we.eq(1)
                    ]
                    m.next = nextstate
            # advance row/column counters
            with m.State("CAPTURE-PIXEL"):
                with m.If(stb):
                    with m.If(col == self.columns - 1):
                        m.d.sync += [
                            col.eq(0),
                            row.eq(row + 1),
                        ]
                        m.next = "CAPTURE-ROW"
                    with m.Else():
                        m.d.sync += col.eq(col + 1)
                        m.next = "REPORT-1"


        return m

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

        # Bring the parallel bus in to our internal clock domain and pack it in
        # to a Record
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
        pixel_bus = Record(_bus_layout)
        m.d.comb += [
            pixel_bus.r.eq(rx),
            pixel_bus.g.eq(gx),
            pixel_bus.b.eq(bx),
            pixel_bus.dck.eq(dck),
        ]

        # watchdog that resets the capture machine when we don't see a
        # transition on the dck line for >90% of a vblank
        vblank_cyc = math.ceil(self.vblank * 0.9 * self.sys_clk_freq)
        wdt        = Signal(range(vblank_cyc))
        wdt_s      = Signal()

        with m.If(dck):
            with m.If(wdt != vblank_cyc):
                m.d.sync += wdt.eq(wdt + 1)
        with m.Else():
            m.d.sync += wdt.eq(0)
        m.d.comb += wdt_s.eq(wdt == vblank_cyc)

        # Create and bind the actual capture machine
        m.submodules.capture_machine = ResetInserter(wdt_s)(
            VideoRGBCaptureMachine(pixel_bus, self.in_fifo, self.rows, self.columns)
        )

        return m


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
