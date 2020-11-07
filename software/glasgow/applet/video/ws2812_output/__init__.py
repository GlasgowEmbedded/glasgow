import logging
import asyncio
from nmigen import *

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
    def __init__(self, pads, count, out_fifo):
        self.pads = pads
        self.count = count
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

        cyc_ctr = Signal(range(t_reset+1))
        bit_ctr = Signal(range(24))
        pix_ctr = Signal(range(self.count+1))
        word_ctr = Signal(range(max(2, len(self.pads))))

        r = Signal(8)
        g = Signal(8)
        word = Signal(24 * len(self.pads))

        with m.FSM():
            with m.State("LOAD-R"):
                m.d.comb += [
                    self.out_fifo.r_en.eq(1),
                    output.out.eq(0),
                ]
                with m.If(self.out_fifo.r_rdy):
                    m.d.sync += r.eq(self.out_fifo.r_data)
                    m.next = "LOAD-G"

            with m.State("LOAD-G"):
                m.d.comb += [
                    self.out_fifo.r_en.eq(1),
                    output.out.eq(0),
                ]
                with m.If(self.out_fifo.r_rdy):
                    m.d.sync += g.eq(self.out_fifo.r_data)
                    m.next = "LOAD-B"

            with m.State("LOAD-B"):
                m.d.comb += [
                    self.out_fifo.r_en.eq(1),
                    output.out.eq(0),
                ]
                with m.If(self.out_fifo.r_rdy):
                    m.d.sync += word.eq(Cat(word[24:] if len(self.pads) > 1 else [], self.out_fifo.r_data, r, g))
                    with m.If(word_ctr == (len(self.pads) - 1)):
                        m.next = "SEND-WORD"
                    with m.Else():
                        m.d.sync += word_ctr.eq(word_ctr + 1)
                        m.next = "LOAD-R"

            with m.State("SEND-WORD"):
                with m.If(cyc_ctr < t_zero):
                    m.d.comb += output.out.eq((1 << len(self.pads)) - 1)
                    m.d.sync += cyc_ctr.eq(cyc_ctr + 1)
                with m.Elif(cyc_ctr < t_one):
                    m.d.comb += ( o.eq(word[23 + 24 * i]) for i,o in enumerate(output.out) )
                    m.d.sync += cyc_ctr.eq(cyc_ctr + 1)
                with m.Elif(cyc_ctr < t_period):
                    m.d.comb += output.out.eq(0)
                    m.d.sync += cyc_ctr.eq(cyc_ctr + 1)
                with m.Elif(bit_ctr < 23):
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
                        word_ctr.eq(0),
                    ]
                    m.next = "LOAD-R"
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
                        word_ctr.eq(0),
                    ]
                    m.next = "LOAD-R"

        return m


class VideoWS2812OutputApplet(GlasgowApplet, name="video-ws2812-output"):
    logger = logging.getLogger(__name__)
    help = "display video via WS2812 LEDs"
    description = """
    Output RGB frames from a socket to one or more WS2812(B) LED strings.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_set_argument(parser, "out", width=range(1, 17), required=True)
        parser.add_argument(
            "-c", "--count", metavar="N", type=int, required=True,
            help="set the number of LEDs per string")

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        subtarget = iface.add_subtarget(VideoWS2812OutputSubtarget(
            pads=[iface.get_pin(pin) for pin in args.pin_set_out],
            count=args.count,
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
        buffer_size = len(args.pin_set_out) * args.count * 3 * args.buffer
        return await device.demultiplexer.claim_interface(self, self.mux_interface, args, write_buffer_size=buffer_size)

    @classmethod
    def add_interact_arguments(cls, parser):
        ServerEndpoint.add_argument(parser, "endpoint")

    async def interact(self, device, args, leds):
        frame_size = len(args.pin_set_out) * args.count * 3
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

# -------------------------------------------------------------------------------------------------

class VideoWS2812OutputAppletTestCase(GlasgowAppletTestCase, applet=VideoWS2812OutputApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--pins-out", "0:3", "-c", "1024"])
