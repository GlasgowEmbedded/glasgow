import logging
import argparse
from migen import *

from .. import *
from ...gateware.pads import *


class AudioOutputChannel(Module):
    def __init__(self, output, bits):
        self.level = Signal(bits)
        self.latch = Signal(bits)
        self.stb   = Signal()

        ###

        self.accum = Signal(bits)
        self.sync += Cat(self.accum, output).eq(self.accum + self.latch)

        self.sync += If(self.stb, self.latch.eq(self.level))


class AudioOutputSubtarget(Module):
    def __init__(self, pads, out_fifo, sample_cyc, width):
        assert width in (1, 2)

        timer = Signal(max=sample_cyc)

        channels = [AudioOutputChannel(output, bits=width * 8) for output in pads.o_t.o]
        self.submodules += channels

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
                NextState("CHANNEL-0-READ-1")
            ).Else(
                NextValue(timer, timer - 1)
            )
        )
        for index, channel in enumerate(channels):
            if index + 1 < len(channels):
                next_state = "CHANNEL-%d-READ-1" % (index + 1)
            else:
                next_state = "LATCH"
            if width == 1:
                self.fsm.act("CHANNEL-%d-READ-1" % index,
                    out_fifo.re.eq(1),
                    If(out_fifo.readable,
                        NextValue(channel.level[0:8], out_fifo.dout),
                        NextState(next_state)
                    ).Else(
                        NextState("STANDBY")
                    )
                )
            if width == 2:
                self.fsm.act("CHANNEL-%d-READ-1" % index,
                    out_fifo.re.eq(1),
                    If(out_fifo.readable,
                        NextValue(channel.level[0:8], out_fifo.dout),
                        NextState("CHANNEL-%d-READ-2" % index)
                    ).Else(
                        NextState("STANDBY")
                    )
                )
                self.fsm.act("CHANNEL-%d-READ-2" % index,
                    out_fifo.re.eq(1),
                    If(out_fifo.readable,
                        NextValue(channel.level[8:16], out_fifo.dout),
                        NextState(next_state)
                    ).Else(
                        NextState("STANDBY")
                    )
                )
        self.fsm.act("LATCH",
            [channel.stb.eq(1) for channel in channels],
            NextState("WAIT")
        )


class AudioOutputApplet(GlasgowApplet, name="audio-output"):
    logger = logging.getLogger(__name__)
    help = "play sound using a ΣΔ-DAC"
    description = """
    Play sound using a 1-bit sigma-delta DAC, i.e. pulse density modulation.

    Currently, the supported sample formats are:
        * 1..16 channel unsigned 8-bit,
        * 1..16 channel unsigned 16-bit little endian.

    Other formats may be converted to it using:

        sox <input> -c <channels> -r <rate> <output>.<u8|u16>

    For example, to play an ogg file:

        sox samples.ogg -c 2 -r 48000 samples.u16
        glasgow run audio-output --pins-o 0,1 -r 48000 -w 2 samples.u16
    """

    __pin_sets = ("o",)

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_set_argument(parser, "o", width=range(1, 17), default=1)

        parser.add_argument(
            "-r", "--sample-rate", metavar="FREQ", type=int, default=8000,
            help="set sample rate to FREQ Hz (default: %(default)d)")
        parser.add_argument(
            "-w", "--width", metavar="WIDTH", type=int, default=1,
            help="set sample width to WIDTH bytes (default: %(default)d)")

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        subtarget = iface.add_subtarget(AudioOutputSubtarget(
            pads=iface.get_pads(args, pin_sets=self.__pin_sets),
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
