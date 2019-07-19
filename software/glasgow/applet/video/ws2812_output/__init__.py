import logging
import asyncio
from migen import *

from ....support.endpoint import *
from ....gateware.pads import *
from ....gateware.pll import *
from ... import *


class VideoWS2812Output(Module):
    def __init__(self, pads):
        self.out = Signal(len(pads))

        for i, pad in enumerate(pads):
            self.comb += [
                pad.oe.eq(1),
                pad.o.eq(self.out[i]),
            ]


class VideoWS2812OutputSubtarget(Module):
    def __init__(self, pads, sys_clk_freq, count, out_fifo):

        # Safe timings:
        # bit period needs to be > 1250ns and < 7µs
        # 0 bits should be 100 - 500 ns
        # 1 bits should be > 750ns and < (period - 200ns)
        # reset should be >300µs

        t_one = int(1 + sys_clk_freq * 750e-9)
        t_period = int(max(1 + sys_clk_freq * 1250e-9, 1 + t_one + sys_clk_freq * 200e-9))
        assert t_period / sys_clk_freq < 7000e-9
        t_zero = int(1 + sys_clk_freq * 100e-9)
        assert t_zero < sys_clk_freq * 500e-9
        t_reset = int(1 + sys_clk_freq * 300e-6)

        self.submodules.output = output = VideoWS2812Output(pads)

        self.cyc_ctr = Signal(max=t_reset+1)
        self.bit_ctr = Signal(max=24)
        self.pix_ctr = Signal(max=count+1)
        self.word_ctr = Signal(max=max(2, len(pads)))
        self.r = Signal(8)
        self.g = Signal(8)
        self.word = Signal(24 * len(pads))

        self.submodules.fsm = ResetInserter()(FSM(reset_state="LOAD-R"))
        self.fsm.act("LOAD-R",
            output.out.eq(0),
            out_fifo.re.eq(1),
            If(out_fifo.readable,
                NextValue(self.r, out_fifo.dout),
                NextState("LOAD-G")
            )
        )
        self.fsm.act("LOAD-G",
            output.out.eq(0),
            out_fifo.re.eq(1),
            If(out_fifo.readable,
                NextValue(self.g, out_fifo.dout),
                NextState("LOAD-B"),
            )
        )
        self.fsm.act("LOAD-B",
            output.out.eq(0),
            out_fifo.re.eq(1),
            If(out_fifo.readable,
                NextValue(self.word, Cat(self.word[24:] if len(pads) > 1 else [], out_fifo.dout, self.r, self.g)),
                If(self.word_ctr == (len(pads) - 1),
                    NextState("SEND-WORD"),
                ).Else(
                    NextState("LOAD-R"),
                    NextValue(self.word_ctr, self.word_ctr + 1),
                )
            )
        )
        self.fsm.act("SEND-WORD",
            out_fifo.re.eq(0),
            If(self.cyc_ctr < t_zero,
                output.out.eq((1 << len(pads)) - 1),
                NextValue(self.cyc_ctr, self.cyc_ctr + 1),
            ).Elif(self.cyc_ctr < t_one,
                [o.eq(self.word[23 + 24 * i]) for i, o in enumerate(output.out)],
                NextValue(self.cyc_ctr, self.cyc_ctr + 1),
            ).Elif(self.cyc_ctr < t_period,
                output.out.eq(0),
                NextValue(self.cyc_ctr, self.cyc_ctr + 1),
            ).Elif(self.bit_ctr < 23,
                output.out.eq(0),
                NextValue(self.cyc_ctr, 0),
                NextValue(self.bit_ctr, self.bit_ctr + 1),
                NextValue(self.word, Cat(0, self.word[:-1])),
            ).Elif(self.pix_ctr < (count - 1),
                output.out.eq(0),
                NextValue(self.pix_ctr, self.pix_ctr + 1),
                NextValue(self.cyc_ctr, 0),
                NextValue(self.bit_ctr, 0),
                NextValue(self.word_ctr, 0),
                NextState("LOAD-R")
            ).Else(
                output.out.eq(0),
                NextValue(self.cyc_ctr, 0),
                NextState("RESET")
            )
        )
        self.fsm.act("RESET",
            out_fifo.re.eq(0),
            output.out.eq(0),
            NextValue(self.cyc_ctr, self.cyc_ctr + 1),
            If(self.cyc_ctr == t_reset,
                NextValue(self.cyc_ctr, 0),
                NextValue(self.pix_ctr, 0),
                NextValue(self.bit_ctr, 0),
                NextValue(self.word_ctr, 0),
                NextState("LOAD-R")
            )
        )


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
        ServerEndpoint.add_argument(parser, "endpoint")

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        subtarget = iface.add_subtarget(VideoWS2812OutputSubtarget(
            pads=[iface.get_pin(pin) for pin in args.pin_set_out],
            sys_clk_freq=target.sys_clk_freq,
            count=args.count,
            out_fifo=iface.get_out_fifo(),
        ))

        return subtarget

    async def run(self, device, args):
        return await device.demultiplexer.claim_interface(self, self.mux_interface, args)

    async def interact(self, device, args, leds):
        endpoint = await ServerEndpoint("socket", self.logger, args.endpoint)
        while True:
            try:
                data = await asyncio.shield(endpoint.recv())
                await leds.write(data)
                await leds.flush(wait=False)
            except asyncio.CancelledError:
                pass

# -------------------------------------------------------------------------------------------------

class VideoWS2812OutputAppletTestCase(GlasgowAppletTestCase, applet=VideoWS2812OutputApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--port", "A"])
