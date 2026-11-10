from collections.abc import Buffer, Iterable
from amaranth import *
from amaranth.lib import io, wiring, stream
from amaranth.lib.wiring import In

from glasgow.support import logging
from glasgow.support.endpoint import ServerEndpoint
from glasgow.abstract import AbstractAssembly, GlasgowPin
from glasgow.applet import GlasgowAppletV2, GlasgowAppletError


__all__ = ["WS2812OutputInterface"]


class VideoWS2812Output(Elaboratable):
    def __init__(self, ports):
        self.ports = ports
        self.out = Signal(len(ports.out))

    def elaborate(self, platform):
        m = Module()

        m.submodules.out_buffer = out_buffer = io.Buffer("o", self.ports.out)
        m.d.comb += out_buffer.o.eq(self.out)

        return m


class VideoWS2812OutputComponent(wiring.Component):
    i_stream: In(stream.Signature(8))

    def __init__(self, ports, count, pix_in_size, pix_out_size, pix_format_func):
        self.ports           = ports
        self.count           = count
        self.pix_in_size     = pix_in_size
        self.pix_out_size    = pix_out_size
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

        cyc_ctr = Signal(range(t_reset+1))
        bit_ctr = Signal(range(pix_out_bpp+1))
        byt_ctr = Signal(range((pix_in_size)+1))
        pix_ctr = Signal(range(self.count+1))
        word_ctr = Signal(range(max(2, len(self.ports.out))))

        pix = Array([ Signal(8) for i in range((pix_in_size) - 1) ])
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
                    m.d.comb += (o.eq(word[(pix_out_bpp - 1) + (pix_out_bpp * i)])
                                 for i,o in enumerate(output.out))
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


class WS2812OutputInterface:
    """Output complete frames to parallel WS2812 LED strings.

    Pixels are interleaved by string: pixel 0 of every string, then pixel 1 of every string,
    and so on. Each pixel contains RGB or RGBW bytes as selected by :py:`pixel_format`.
    """

    pixel_formats = {
        "RGB-BRG":   (3, 3, lambda r, g, b: Cat(b, r, g)),
        "RGB-xBRG":  (3, 4, lambda r, g, b: Cat(Const(0, unsigned(8)), b, r, g)),
        "RGBW-WBRG": (4, 4, lambda r, g, b, w: Cat(w, b, r, g)),
    }

    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
                 out: Iterable[GlasgowPin], count: int, pixel_format="RGB-BRG", buffer=16):
        if count <= 0:
            raise ValueError("LED count must be positive")
        if buffer <= 0:
            raise ValueError("Frame buffer count must be positive")
        pix_in_size, pix_out_size, pix_format_func = self.pixel_formats[pixel_format]
        ports = assembly.add_port_group(out=out)
        self.frame_size = len(ports.out) * count * pix_in_size
        self.buffer_size = self.frame_size * buffer
        component = assembly.add_submodule(VideoWS2812OutputComponent(
            ports, count, pix_in_size, pix_out_size, pix_format_func))
        self._pipe = assembly.add_out_pipe(component.i_stream, buffer_size=self.buffer_size)

    async def write(self, data: Buffer):
        """Write one or more complete frames and flush them to the device.

        The byte length must be a multiple of :py:`frame_size`.
        """
        if memoryview(data).nbytes % self.frame_size:
            raise ValueError("Data must contain complete frames")
        await self._pipe.send(data)
        await self._pipe.flush()


class VideoWS2812OutputApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "display video via WS2812 LEDs"
    description = """
    Output RGB(W) frames from a socket to one or more WS2812(B) LED strings.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)

        access.add_pins_argument(parser, "out", width=range(1, 17), required=True)
        parser.add_argument(
            "-c", "--count", metavar="N", type=int, required=True,
            help="set the number of LEDs per string")
        parser.add_argument(
            "-f", "--pix-fmt", metavar="F",
            choices=WS2812OutputInterface.pixel_formats.keys(), default="RGB-BRG",
            help="set the pixel format (one of: RGB-BRG, RGB-xBRG, RGBW-WBRG; "
                 "default: %(default)s)")

        parser.add_argument(
            "-b", "--buffer", metavar="N", type=int, default=16,
            help="set the number of frames to buffer internally (buffered twice)")

    def build(self, args):
        if args.count <= 0:
            raise GlasgowAppletError("LED count must be positive")
        if args.buffer <= 0:
            raise GlasgowAppletError("Frame buffer count must be positive")
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.leds_iface = WS2812OutputInterface(self.logger, self.assembly,
                out=args.out, count=args.count, pixel_format=args.pix_fmt, buffer=args.buffer)

    @classmethod
    def add_run_arguments(cls, parser):
        ServerEndpoint.add_argument(parser, "endpoint")

    async def run(self, args):
        endpoint = await ServerEndpoint("socket", self.logger, args.endpoint,
            queue_size=self.leds_iface.buffer_size)
        while True:
            try:
                data = await endpoint.recv()
                partial = len(data) % self.leds_iface.frame_size
                if partial:
                    data += await endpoint.recv(self.leds_iface.frame_size - partial)
            except EOFError:
                continue
            await self.leds_iface.write(data)

    @classmethod
    def tests(cls):
        from . import test
        return test.VideoWS2812OutputAppletTestCase
