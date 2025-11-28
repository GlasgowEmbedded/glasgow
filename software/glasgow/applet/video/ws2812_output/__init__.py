import logging
import asyncio

from amaranth import *
from amaranth.lib import io, wiring, stream
from amaranth.lib.wiring import In

from glasgow.abstract import AbstractAssembly, GlasgowPin, PortGroup
from glasgow.applet import GlasgowAppletV2
from glasgow.support.endpoint import *
from glasgow.gateware.pll import *


class VideoWS2812Output(Elaboratable):
    def __init__(self, ports: PortGroup):
        self.ports = ports
        self.out = Signal(len(ports.out))

    def elaborate(self, platform):
        m = Module()

        m.submodules.out_buffer = out_buffer = io.Buffer("o", self.ports.out)
        m.d.comb += out_buffer.o.eq(self.out)

        return m


class VideoWS2812OutputComponent(wiring.Component):
    i_stream: In(stream.Signature(8))

    def __init__(
        self, ports: PortGroup, count: int, pix_in_size: int, pix_out_size: int, pix_format_func
    ):
        self.ports = ports
        self.count = count
        self.pix_in_size = pix_in_size
        self.pix_out_size = pix_out_size
        self.pix_format_func = pix_format_func

        super().__init__()

    def elaborate(self, platform):
        # Safe timings:
        # bit period needs to be > 1250ns and < 7µs
        # 0 bits should be 100 - 500 ns
        # 1 bits should be > 750ns and < (period - 200ns)
        # reset should be >300µs

        sys_clk_freq = platform.default_clk_frequency
        t_one = int(1 + sys_clk_freq * 750e-9)
        t_period = int(max(1 + sys_clk_freq * 1250e-9, 1 + t_one + sys_clk_freq * 200e-9))
        assert t_period / sys_clk_freq < 7000e-9
        t_zero = int(1 + sys_clk_freq * 100e-9)
        assert t_zero < sys_clk_freq * 500e-9
        t_reset = int(1 + sys_clk_freq * 300e-6)

        m = Module()

        m.submodules.output = output = VideoWS2812Output(self.ports)

        pix_in_size = self.pix_in_size
        pix_out_size = self.pix_out_size
        pix_out_bpp = pix_out_size * 8

        cyc_ctr = Signal(range(t_reset + 1))
        bit_ctr = Signal(range(pix_out_bpp + 1))
        byt_ctr = Signal(range((pix_in_size) + 1))
        pix_ctr = Signal(range(self.count + 1))
        word_ctr = Signal(range(max(2, len(self.ports.out))))

        pix = Array([Signal(8) for i in range((pix_in_size) - 1)])
        word = Signal(pix_out_bpp * len(self.ports.out))

        with m.FSM():
            with m.State("LOAD"):
                m.d.comb += [
                    self.i_stream.ready.eq(1),
                    output.out.eq(0),
                ]
                with m.If(self.i_stream.valid):
                    with m.If(byt_ctr < ((pix_in_size) - 1)):
                        m.d.sync += [
                            pix[byt_ctr].eq(self.i_stream.payload),
                            byt_ctr.eq(byt_ctr + 1),
                        ]
                    with m.Else():
                        p = self.pix_format_func(*pix, self.i_stream.payload)
                        m.d.sync += word.eq(Cat(word[pix_out_bpp:], p))
                        with m.If(word_ctr < (len(self.ports.out) - 1)):
                            m.d.sync += [
                                word_ctr.eq(word_ctr + 1),
                                byt_ctr.eq(0),
                            ]
                        with m.Else():
                            m.next = "SEND-WORD"

            with m.State("SEND-WORD"):
                with m.If(cyc_ctr < t_zero):
                    m.d.comb += output.out.eq((1 << len(self.ports.out)) - 1)
                    m.d.sync += cyc_ctr.eq(cyc_ctr + 1)
                with m.Elif(cyc_ctr < t_one):
                    m.d.comb += (
                        o.eq(word[(pix_out_bpp - 1) + (pix_out_bpp * i)])
                        for i, o in enumerate(output.out)
                    )
                    m.d.sync += cyc_ctr.eq(cyc_ctr + 1)
                with m.Elif(cyc_ctr < t_period):
                    m.d.comb += output.out.eq(0)
                    m.d.sync += cyc_ctr.eq(cyc_ctr + 1)
                with m.Elif(bit_ctr < (pix_out_bpp - 1)):
                    m.d.comb += output.out.eq(0)
                    m.d.sync += [
                        cyc_ctr.eq(0),
                        bit_ctr.eq(bit_ctr + 1),
                        word.eq(Cat(0, word[:-1])),
                    ]
                with m.Elif(pix_ctr < (self.count - 1)):
                    m.d.comb += output.out.eq(0)
                    m.d.sync += [
                        pix_ctr.eq(pix_ctr + 1),
                        cyc_ctr.eq(0),
                        bit_ctr.eq(0),
                        byt_ctr.eq(0),
                        word_ctr.eq(0),
                    ]
                    m.next = "LOAD"
                with m.Else():
                    m.d.comb += output.out.eq(0)
                    m.d.sync += cyc_ctr.eq(0)
                    m.next = "RESET"

            with m.State("RESET"):
                m.d.comb += output.out.eq(0)
                m.d.sync += cyc_ctr.eq(cyc_ctr + 1)
                with m.If(cyc_ctr == t_reset):
                    m.d.sync += [
                        cyc_ctr.eq(0),
                        pix_ctr.eq(0),
                        bit_ctr.eq(0),
                        byt_ctr.eq(0),
                        word_ctr.eq(0),
                    ]
                    m.next = "LOAD"

        return m


class VideoWS2812OutputInterface:
    def __init__(
        self,
        logger: logging.Logger,
        assembly: AbstractAssembly,
        *,
        out: tuple[GlasgowPin],
        count: int,
        pix_in_size: int,
        pix_out_size: int,
        pix_format_func,
        buffer: int,
    ):
        self._logger = logger
        self._frame_size = len(out) * pix_in_size * count
        ports = assembly.add_port_group(out=out)
        component = assembly.add_submodule(
            VideoWS2812OutputComponent(ports, count, pix_in_size, pix_out_size, pix_format_func)
        )
        self._pipe = assembly.add_out_pipe(
            component.i_stream, buffer_size=len(out) * count * pix_in_size * buffer
        )

    async def write_frame(self, data):
        """Send one or more frame's worth of pixel data to the LED string."""
        assert len(data) % self._frame_size == 0
        await self._pipe.send(data)
        await self._pipe.flush(_wait=False)

    @property
    def frame_size(self) -> int:
        """Size of each frame in bytes."""
        return self._frame_size


class VideoWS2812OutputApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "display video via WS2812 LEDs"
    description = """
    Output RGB(W) frames from a socket to one or more WS2812(B) LED strings.
    """

    pixel_formats = {
        # in-out      in size  out size  format_func
        "RGB-BRG":   (   3,        3,    lambda r,g,b:   Cat(b,r,g)   ),
        "RGB-BGR":   (   3,        3,    lambda r,g,b:   Cat(b,g,r)   ),
        "RGB-xBRG":  (   3,        4,    lambda r,g,b:   Cat(Const(0, unsigned(8)),b,r,g) ),
        "RGBW-WBRG": (   4,        4,    lambda r,g,b,w: Cat(w,b,r,g) ),
    }

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "out", width=range(1, 17), required=True)
        parser.add_argument(
            "-c", "--count", metavar="N", type=int, required=True,
            help="set the number of LEDs per string")
        parser.add_argument(
            "-f", "--pix-fmt", metavar="F", choices=cls.pixel_formats.keys(), default="RGB-BRG",
            help="set the pixel format (one of: %(choices)s, default: %(default)s)")
        parser.add_argument(
            "-b", "--buffer", metavar="N", type=int, default=16,
            help="set the number of frames to buffer internally (buffered twice)")

    def build(self, args):
        self.pix_in_size, pix_out_size, pix_format_func = self.pixel_formats[args.pix_fmt]

        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.ws2812_iface = VideoWS2812OutputInterface(
                self.logger,
                self.assembly,
                out=args.out,
                count=args.count,
                pix_in_size=self.pix_in_size,
                pix_out_size=pix_out_size,
                pix_format_func=pix_format_func,
                buffer=args.buffer,
            )

    @classmethod
    def add_run_arguments(cls, parser):
        ServerEndpoint.add_argument(parser, "endpoint")

    async def run(self, args):
        # This buffer is for the socket only, and is independet from the one
        # configured in VideoWS2812OutputInterface
        frame_size = self.ws2812_iface.frame_size
        buffer_size = frame_size * args.buffer
        endpoint = await ServerEndpoint(
            "socket",
            self.logger,
            args.endpoint,
            queue_size=buffer_size,
        )
        while True:
            try:
                data = await asyncio.shield(endpoint.recv(buffer_size))
                partial = len(data) % frame_size
                while partial:
                    data += await asyncio.shield(endpoint.recv(frame_size - partial))
                    partial = len(data) % frame_size
                await self.ws2812_iface.write_frame(data)
            except EOFError:
                pass

    @classmethod
    def tests(cls):
        from . import test

        return test.VideoWS2812OutputAppletTestCase
