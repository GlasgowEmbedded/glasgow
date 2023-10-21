import logging
import asyncio
from amaranth import *

from ....support.endpoint import *
from ....gateware.pads import *
from ....gateware.pll import *
from ... import *


class VideoWS2812Output(Elaboratable):
    def __init__(self, pads):
        self.pads = pads
        self.out = Signal(len(pads))

    def elaborate(self, platform):
        m = Module()

        for i, pad in enumerate(self.pads):
            m.d.comb += [
                pad.oe.eq(1),
                pad.o.eq(self.out[i]),
            ]

        return m


class VideoWS2812OutputSubtarget(Elaboratable):
    def __init__(self, pads, count, pix_in_size, pix_out_size, pix_format_func, out_fifo):
        self.pads = pads
        self.count = count
        self.pix_in_size = pix_in_size
        self.pix_out_size = pix_out_size
        self.pix_format_func = pix_format_func
        self.out_fifo = out_fifo

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

        m.submodules.output = output = VideoWS2812Output(self.pads)

        pix_in_size = self.pix_in_size
        pix_out_size = self.pix_out_size
        pix_out_bpp = pix_out_size * 8

        cyc_ctr = Signal(range(t_reset+1))
        bit_ctr = Signal(range(pix_out_bpp+1))
        byt_ctr = Signal(range((pix_in_size)+1))
        pix_ctr = Signal(range(self.count+1))
        word_ctr = Signal(range(max(2, len(self.pads))))

        pix = Array([ Signal(8) for i in range((pix_in_size) - 1) ])
        word = Signal(pix_out_bpp * len(self.pads))

        with m.FSM():
            with m.State("LOAD"):
                m.d.comb += [
                    self.out_fifo.r_en.eq(1),
                    output.out.eq(0),
                ]
                with m.If(self.out_fifo.r_rdy):
                    with m.If(byt_ctr < ((pix_in_size) - 1)):
                        m.d.sync += [
                            pix[byt_ctr].eq(self.out_fifo.r_data),
                            byt_ctr.eq(byt_ctr + 1),
                        ]
                    with m.Else():
                        p = self.pix_format_func(*pix, self.out_fifo.r_data)
                        m.d.sync += word.eq(Cat(word[pix_out_bpp:], p))
                        with m.If(word_ctr < (len(self.pads) - 1)):
                            m.d.sync += [
                                word_ctr.eq(word_ctr + 1),
                                byt_ctr.eq(0),
                            ]
                        with m.Else():
                            m.next = "SEND-WORD"

            with m.State("SEND-WORD"):
                with m.If(cyc_ctr < t_zero):
                    m.d.comb += output.out.eq((1 << len(self.pads)) - 1)
                    m.d.sync += cyc_ctr.eq(cyc_ctr + 1)
                with m.Elif(cyc_ctr < t_one):
                    m.d.comb += ( o.eq(word[(pix_out_bpp - 1) + (pix_out_bpp * i)]) for i,o in enumerate(output.out) )
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


class VideoWS2812OutputApplet(GlasgowApplet):
    logger = logging.getLogger(__name__)
    help = "display video via WS2812 LEDs"
    description = """
    Output RGB(W) frames from a socket to one or more WS2812(B) LED strings.
    """

    pixel_formats = {
        # in-out      in size  out size  format_func
        'RGB-BRG':   (   3,        3,    lambda r,g,b:   Cat(b,r,g)   ),
        'RGB-xBRG':  (   3,        4,    lambda r,g,b:   Cat(Const(0, unsigned(8)),b,r,g) ),
        'RGBW-WBRG': (   4,        4,    lambda r,g,b,w: Cat(w,b,r,g) ),
    }

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_set_argument(parser, "out", width=range(1, 17), required=True)
        parser.add_argument(
            "-c", "--count", metavar="N", type=int, required=True,
            help="set the number of LEDs per string")
        parser.add_argument(
            "-f", "--pix-fmt", metavar="F", choices=cls.pixel_formats.keys(), default="RGB-BRG",
            help="set the pixel format (one of: %(choices)s, default: %(default)s)")

    def build(self, target, args):
        self.pix_in_size, pix_out_size, pix_format_func = self.pixel_formats[args.pix_fmt]

        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        subtarget = iface.add_subtarget(VideoWS2812OutputSubtarget(
            pads=[iface.get_pin(pin) for pin in args.pin_set_out],
            count=args.count,
            pix_in_size=self.pix_in_size,
            pix_out_size=pix_out_size,
            pix_format_func=pix_format_func,
            out_fifo=iface.get_out_fifo(),
        ))

        return subtarget

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)

        parser.add_argument(
            "-b", "--buffer", metavar="N", type=int, default=16,
            help="set the number of frames to buffer internally (buffered twice)")

    async def run(self, device, args):
        buffer_size = len(args.pin_set_out) * args.count * self.pix_in_size * args.buffer
        return await device.demultiplexer.claim_interface(self, self.mux_interface, args, write_buffer_size=buffer_size)

    @classmethod
    def add_interact_arguments(cls, parser):
        ServerEndpoint.add_argument(parser, "endpoint")

    async def interact(self, device, args, leds):
        frame_size = len(args.pin_set_out) * args.count * self.pix_in_size
        buffer_size = frame_size * args.buffer
        endpoint = await ServerEndpoint("socket", self.logger, args.endpoint, queue_size=buffer_size)
        while True:
            try:
                data = await asyncio.shield(endpoint.recv(buffer_size))
                partial = len(data) % frame_size
                while partial:
                    data += await asyncio.shield(endpoint.recv(frame_size - partial))
                    partial = len(data) % frame_size
                await leds.write(data)
                await leds.flush(wait=False)
            except asyncio.CancelledError:
                pass

    @classmethod
    def tests(cls):
        from . import test
        return test.VideoWS2812OutputAppletTestCase
