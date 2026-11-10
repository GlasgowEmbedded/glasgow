import math
from dataclasses import dataclass

from amaranth import *
from amaranth.lib import io, wiring, stream
from amaranth.lib.wiring import Out
from amaranth.lib.cdc import FFSynchronizer

from glasgow.support import logging
from glasgow.abstract import AbstractAssembly, GlasgowPin
from glasgow.applet import GlasgowAppletV2, GlasgowAppletError


class VideoRGBInputComponent(wiring.Component):
    o_stream: Out(stream.Signature(8))

    def __init__(self, rows, columns, vblank, ports, sys_clk_freq):
        self.rows = rows
        self.columns = columns
        self.vblank = vblank
        self.ports = ports
        self.sys_clk_freq = sys_clk_freq
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        rx    = Signal(5)
        gx    = Signal(5)
        bx    = Signal(5)
        dck   = Signal()

        m.submodules.r_buffer   = r_buffer   = io.Buffer("i", self.ports.r)
        m.submodules.g_buffer   = g_buffer   = io.Buffer("i", self.ports.g)
        m.submodules.b_buffer   = b_buffer   = io.Buffer("i", self.ports.b)
        m.submodules.dck_buffer = dck_buffer = io.Buffer("i", self.ports.dck)

        m.submodules += [
            FFSynchronizer(r_buffer.i, rx),
            FFSynchronizer(g_buffer.i, gx),
            FFSynchronizer(b_buffer.i, bx),
            FFSynchronizer(dck_buffer.i, dck)
        ]

        dck_r = Signal()
        stb   = Signal()
        m.d.sync += [
            dck_r.eq(dck),
            stb.eq(~dck_r & dck)
        ]

        w_en    = Signal()
        w_data  = Signal(8)
        ovf   = Signal()
        ovf_c = Signal()
        m.d.comb += [
            self.o_stream.valid.eq(w_en & ~ovf),
            self.o_stream.payload.eq(w_data),
        ]
        with m.If(ovf_c):
            m.d.sync += ovf.eq(0)
        with m.Elif(w_en & ~self.o_stream.ready):
            m.d.sync += ovf.eq(1)

        pixel = Signal(15)
        with m.If(stb):
            m.d.sync += pixel.eq(Cat(rx, gx, bx))

        frame = Signal(5)

        ovf_r = Signal()
        row   = Signal(range(self.rows + 1))
        col   = Signal(range(self.columns))
        # Reset only row/column tracking and the FSM during vertical blanking.
        capture = Module()
        blank = Signal()
        m.submodules.capture = ResetInserter(blank)(capture)
        with m.If(ovf_c):
            m.d.sync += [ovf_r.eq(ovf), frame.eq(frame + 1)]
        with capture.FSM():
            with capture.State("CAPTURE-ROW"):
                with capture.If(stb):
                    with capture.If(row == 0):
                        capture.d.comb += [
                            ovf_c.eq(1),
                        ]
                        capture.next = "SKIP-FIRST-PIXEL"
                    with capture.Elif(row == self.rows):
                        capture.d.sync += row.eq(0)
                        capture.next = "REPORT-FRAME"
                    with capture.Else():
                        capture.next = "REPORT-FRAME"
            with capture.State("SKIP-FIRST-PIXEL"):
                with capture.If(stb):
                    capture.next = "REPORT-FRAME"
            with capture.State("REPORT-FRAME"):
                capture.d.comb += [
                    w_data.eq(0x80 | (ovf_r << 6) | (frame << 1) | (row >> 7)),
                    w_en.eq(1),
                ]
                capture.next = "REPORT-ROW"
            with capture.State("REPORT-ROW"):
                capture.d.comb += [
                    w_data.eq(row & 0x7f),
                    w_en.eq(1),
                ]
                capture.next = "REPORT-1"
            for (state, offset, nextstate) in (
                ("REPORT-1",  0, "REPORT-2"),
                ("REPORT-2",  5, "REPORT-3"),
                ("REPORT-3", 10, "CAPTURE-PIXEL")
            ):
                with capture.State(state):
                    capture.d.comb += [
                        w_data.eq((pixel >> offset) & 0x1f),
                        w_en.eq(1),
                    ]
                    capture.next = nextstate
            with capture.State("CAPTURE-PIXEL"):
                with capture.If(stb):
                    with capture.If(col == self.columns - 1):
                        capture.d.sync += [
                            col.eq(0),
                            row.eq(row + 1),
                        ]
                        capture.next = "CAPTURE-ROW"
                    with capture.Else():
                        capture.d.sync += col.eq(col + 1)
                        capture.next = "REPORT-1"

        vblank_cyc = math.ceil(self.vblank * 0.9 * self.sys_clk_freq) # reset at 90% vblank
        timer      = Signal(range(vblank_cyc + 1))
        with m.If(dck):
            with m.If(timer != vblank_cyc):
                m.d.sync += timer.eq(timer + 1)
        with m.Else():
            m.d.sync += timer.eq(0)

        m.d.comb += blank.eq(timer == vblank_cyc)

        return m


@dataclass(frozen=True)
class VideoRGBInputRow:
    """Row header from the capture stream.

    ``frame`` is a wrapping 5-bit counter, ``row`` is an 8-bit row number, and ``overflow``
    reports lost data in the previous frame. Pixel data is not included.
    """

    frame: int
    row: int
    overflow: bool


class VideoRGBInputInterface:
    """Capture row headers from a parallel RGB555 LCD bus.

    ``vblank`` is the vertical blanking interval in seconds. The bus must hold DCK high
    during vertical blanking. Each color pin group is ordered from least to most significant bit.
    """

    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
                 r: tuple[GlasgowPin, ...], g: tuple[GlasgowPin, ...],
                 b: tuple[GlasgowPin, ...], dck: GlasgowPin,
                 rows: int, columns: int, vblank: float):
        if not 1 <= rows <= 256:
            raise GlasgowAppletError("row count must be between 1 and 256")
        if columns < 1:
            raise GlasgowAppletError("column count must be positive")
        if not math.isfinite(vblank) or vblank <= 0:
            raise GlasgowAppletError("vertical blanking interval must be finite and positive")

        component = assembly.add_submodule(VideoRGBInputComponent(
            rows=rows, columns=columns, vblank=vblank,
            ports=assembly.add_port_group(r=r, g=g, b=b, dck=dck),
            sys_clk_freq=1 / assembly.sys_clk_period,
        ))
        self._pipe = assembly.add_in_pipe(component.o_stream, fifo_depth=512 * 30)

    async def read_row(self) -> VideoRGBInputRow:
        """Wait for the next row header, discarding intervening pixel bytes.

        This preview interface reports headers only; it does not reconstruct images.
        """
        sync = 0
        while not (sync & 0x80):
            sync = (await self._pipe.recv(1))[0]
        row = ((sync & 0x01) << 7) | (await self._pipe.recv(1))[0]
        return VideoRGBInputRow(frame=(sync & 0x3e) >> 1, row=row,
                                overflow=bool(sync & 0x40))


class VideoRGBInputApplet(GlasgowAppletV2):
    preview = True
    logger = logging.getLogger(__name__)
    help = "capture video stream from RGB555 LCD bus"
    description = """
    Streams screen contents from a color parallel RGB555 LCD, such as Sharp LQ035Q7DH06.

    This preview reports ten frame/row headers; it does not save or display captured images.
    The vertical blanking interval is specified in seconds.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "r", width=5, required=True)
        access.add_pins_argument(parser, "g", width=5, required=True)
        access.add_pins_argument(parser, "b", width=5, required=True)
        access.add_pins_argument(parser, "dck", required=True)
        parser.add_argument("--rows", type=int, required=True,
            help="LCD row count")
        parser.add_argument("--columns", type=int, required=True,
            help="LCD column count")
        parser.add_argument("--vblank", type=float, required=True,
            help="vertical blanking interval, in seconds")

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.video_rgb_iface = VideoRGBInputInterface(self.logger, self.assembly,
                r=args.r, g=args.g, b=args.b, dck=args.dck,
                rows=args.rows, columns=args.columns, vblank=args.vblank)

    async def run(self, args):
        for _ in range(10):
            header = await self.video_rgb_iface.read_row()
            print(f"frame {header.frame} row {header.row}")

    @classmethod
    def tests(cls):
        from . import test
        return test.VideoRGBInputAppletTestCase
