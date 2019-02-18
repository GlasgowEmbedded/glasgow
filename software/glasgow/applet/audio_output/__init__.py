import logging
import argparse
from migen import *

from .. import *
from ...gateware.pads import *


class AudioOutputSubtarget(Module):
    def __init__(self, pads, out_fifo, sample_cyc, width):
        assert width in (1, 2)

        timer = Signal(max=sample_cyc)
        accum = Signal(width * 8)
        level = Signal(width * 8)

        self.sync += Cat(accum, pads.o_t.o).eq(accum + level)

        self.submodules.fsm = FSM()
        self.fsm.act("STANDBY",
            NextValue(pads.o_t.oe, 0),
            If(out_fifo.readable,
                NextValue(pads.o_t.oe, 1),
                NextState("WAIT")
            )
        )
        self.fsm.act("WAIT",
            If(timer == 0,
                NextValue(timer, sample_cyc - width - 1),
                NextState("READ-1")
            ).Else(
                NextValue(timer, timer - 1)
            )
        )
        self.fsm.act("READ-1",
            out_fifo.re.eq(1),
            If(out_fifo.readable,
                NextValue(level[0:8], out_fifo.dout),
                NextState("WAIT" if width == 1 else "READ-2")
            ).Else(
                NextState("STANDBY")
            )
        )
        if width > 1:
            self.fsm.act("READ-2",
                out_fifo.re.eq(1),
                If(out_fifo.readable,
                    NextValue(level[8:16], out_fifo.dout),
                    NextState("WAIT")
                ).Else(
                    NextState("STANDBY")
                )
            )


class AudioOutputApplet(GlasgowApplet, name="audio-output"):
    logger = logging.getLogger(__name__)
    help = "play sound using a ΣΔ-DAC"
    description = """
    Play sound using a 1-bit sigma-delta DAC, i.e. pulse density modulation.

    Currently, the supported sample formats are:
        * mono unsigned 8-bit,
        * mono unsigned 16-bit little endian.

    Other formats may be converted to it using:

        sox <input> -c 1 -r <rate> <output>.<u8|u16>
    """

    __pins = ("o",)

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_argument(parser, "o", default=True)

        parser.add_argument(
            "-r", "--sample-rate", metavar="FREQ", type=int, default=8000,
            help="set sample rate to FREQ Hz (default: %(default)d)")
        parser.add_argument(
            "-w", "--width", metavar="WIDTH", type=int, default=1,
            help="set sample width to WIDTH bytes (default: %(default)d)")

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        subtarget = iface.add_subtarget(AudioOutputSubtarget(
            pads=iface.get_pads(args, pins=self.__pins),
            out_fifo=iface.get_out_fifo(),
            sample_cyc=int(target.sys_clk_freq // args.sample_rate),
            width=args.width,
        ))
        return subtarget

    async def run(self, device, args):
        return await device.demultiplexer.claim_interface(self, self.mux_interface, args)

    @classmethod
    def add_interact_arguments(cls, parser):
        parser.add_argument(
            "file", metavar="FILE", type=argparse.FileType("rb"),
            help="read PCM data from FILE")
        parser.add_argument(
            "-l", "--loop", default=False, action="store_true",
            help="loop the input samples")

    async def interact(self, device, args, pcm_iface):
        pcm_data = args.file.read()
        while True:
            await pcm_iface.write(pcm_data)
            if not args.loop:
                break

# -------------------------------------------------------------------------------------------------

class AudioOutputAppletTestCase(GlasgowAppletTestCase, applet=AudioOutputApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
