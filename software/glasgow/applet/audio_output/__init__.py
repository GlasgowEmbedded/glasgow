import logging
import argparse
from migen import *

from .. import *
from ...gateware.pads import *


class AudioOutputSubtarget(Module):
    def __init__(self, pads, out_fifo, sample_cyc):
        count = Signal(8)
        limit = Signal(8)

        self.sync += count.eq(count + 1)
        self.comb += pads.o_t.o.eq(count < limit)

        timer = Signal(max=sample_cyc)
        self.sync += [
            out_fifo.re.eq(0),
            If(timer == 0,
                timer.eq(sample_cyc - 1),
                If(out_fifo.readable,
                    out_fifo.re.eq(1),
                    pads.o_t.oe.eq(1),
                    limit.eq(out_fifo.dout)
                ).Else(
                    pads.o_t.oe.eq(0),
                )
            ).Else(
                timer.eq(timer - 1)
            )
        ]


class AudioOutputApplet(GlasgowApplet, name="audio-output"):
    logger = logging.getLogger(__name__)
    help = "play sound using pulse width modulation"
    description = """
    Play sound using pulse width modulation.

    Currently, only one sample format is supported: mono unsigned 8-bit.
    Other formats may be converted to it using:

        sox <input> -c 1 -r <rate> <output>.u8
    """

    __pins = ("o",)

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_argument(parser, "o", default=True)

        parser.add_argument(
            "-r", "--sample-rate", metavar="FREQ", type=int, default=8000,
            help="set sample rate to FREQ Hz (default: %(default)d)")

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        subtarget = iface.add_subtarget(AudioOutputSubtarget(
            pads=iface.get_pads(args, pins=self.__pins),
            out_fifo=iface.get_out_fifo(),
            sample_cyc=int(target.sys_clk_freq // args.sample_rate),
        ))
        return subtarget

    async def run(self, device, args):
        return await device.demultiplexer.claim_interface(self, self.mux_interface, args)

    @classmethod
    def add_interact_arguments(cls, parser):
        parser.add_argument(
            "file", metavar="FILE", type=argparse.FileType("rb"),
            help="read PCM data from FILE")

    async def interact(self, device, args, pcm_iface):
        await pcm_iface.write(args.file.read())

# -------------------------------------------------------------------------------------------------

class AudioOutputAppletTestCase(GlasgowAppletTestCase, applet=AudioOutputApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
