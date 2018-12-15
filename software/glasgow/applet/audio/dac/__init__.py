import logging
import asyncio
import argparse
from nmigen.compat import *

from ....support.endpoint import *
from ....gateware.clockgen import *
from ... import *


class SigmaDeltaDACChannel(Module):
    def __init__(self, output, bits, signed):
        self.stb    = Signal()

        self.level  = Signal(bits)
        self.update = Signal()

        ###

        level_u = Signal(bits)
        if signed:
            self.comb += level_u.eq(self.level - (1 << (bits - 1)))
        else:
            self.comb += level_u.eq(self.level)

        accum   = Signal(bits)
        level_r = Signal(bits)
        self.sync += [
            If(self.stb,
                Cat(accum, output).eq(accum + level_r)
            ),
            If(self.update,
                level_r.eq(level_u)
            )
        ]


class AudioDACSubtarget(Module):
    def __init__(self, pads, out_fifo, pulse_cyc, sample_cyc, width, signed):
        assert width in (1, 2)

        channels = [SigmaDeltaDACChannel(output, bits=width * 8, signed=signed)
                    for output in pads.o_t.o]
        self.submodules += channels

        self.submodules.clkgen = ClockGen(pulse_cyc)
        for channel in channels:
            self.comb += channel.stb.eq(self.clkgen.stb_r)

        timer = Signal(max=sample_cyc)

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
                NextValue(timer, sample_cyc - len(channels) * width - 1),
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
            [channel.update.eq(1) for channel in channels],
            NextState("WAIT")
        )


class AudioDACApplet(GlasgowApplet, name="audio-dac"):
    logger = logging.getLogger(__name__)
    help = "play sound using a ΣΔ-DAC"
    description = """
    Play sound using a 1-bit sigma-delta DAC, i.e. pulse density modulation.

    Currently, the supported sample formats are:
        * 1..16 channel signed/unsigned 8-bit,
        * 1..16 channel signed/unsigned 16-bit little endian.

    Other formats may be converted to it using:

        $ sox <input> -c <channels> -r <rate> <output>.<u8|u16>

    For example, to play an ogg file:

        $ sox samples.ogg -c 2 -r 48000 samples.u16
        $ glasgow run audio-dac --pins-o 0,1 -r 48000 -w 2 -u play samples.u16

    To use the DAC as a PulseAudio sink, add the following line to default.pa:

        load-module module-simple-protocol-tcp source=0 record=true rate=48000 channels=2 \
            format=s16le port=12345

    Then run:

        $ glasgow run audio-dac --pins-o 0,1 -r 48000 -w 2 -s connect tcp::12345
    """

    __pin_sets = ("o",)

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_set_argument(parser, "o", width=range(1, 17), default=1)

        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int,
            help="set modulation frequency to FREQ MHz (default: maximum)")
        parser.add_argument(
            "-r", "--sample-rate", metavar="RATE", type=int, default=8000,
            help="set sample rate to RATE Hz (default: %(default)d)")
        parser.add_argument(
            "-w", "--width", metavar="WIDTH", type=int, default=1,
            help="set sample width to WIDTH bytes (default: %(default)d)")
        g_signed = parser.add_mutually_exclusive_group(required=True)
        g_signed.add_argument(
            "-s", "--signed", dest="signed", default=False, action="store_true",
            help="interpret samples as signed")
        g_signed.add_argument(
            "-u", "--unsigned", dest="signed", action="store_false",
            help="interpret samples as unsigned")

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        if args.frequency is None:
            pulse_cyc = 0
        else:
            pulse_cyc = self.derive_clock(clock_name="modulation",
                input_hz=target.sys_clk_freq, output_hz=args.frequency * 1e6)
        sample_cyc = self.derive_clock(clock_name="sampling",
            input_hz=target.sys_clk_freq, output_hz=args.sample_rate,
            # Drift of sampling clock is extremely bad, so ensure it only happens insofar as
            # the oscillator on the board is imprecise, and with no additional error.
            max_deviation_ppm=0)
        subtarget = iface.add_subtarget(AudioDACSubtarget(
            pads=iface.get_pads(args, pin_sets=self.__pin_sets),
            out_fifo=iface.get_out_fifo(),
            pulse_cyc=pulse_cyc,
            sample_cyc=sample_cyc,
            width=args.width,
            signed=args.signed,
        ))
        return subtarget

    async def run(self, device, args):
        return await device.demultiplexer.claim_interface(self, self.mux_interface, args,
            write_buffer_size=2048)

    @classmethod
    def add_interact_arguments(cls, parser):
        # TODO(py3.7): add required=True
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION")

        p_play = p_operation.add_parser(
            "play", help="play PCM file")
        p_play.add_argument(
            "file", metavar="FILE", type=argparse.FileType("rb"),
            help="read PCM data from FILE")
        p_play.add_argument(
            "-l", "--loop", default=False, action="store_true",
            help="loop the input samples")

        p_connect = p_operation.add_parser(
            "connect", help="connect to a PCM source")
        ServerEndpoint.add_argument(p_connect, "pcm_endpoint")

    async def interact(self, device, args, pcm_iface):
        if args.operation == "play":
            pcm_data = args.file.read()
            while True:
                await pcm_iface.write(pcm_data)
                if not args.loop:
                    break

        if args.operation == "connect":
            proto, *proto_args = args.pcm_endpoint
            if proto == "tcp":
                reader, _ = await asyncio.open_connection(*proto_args)
            elif proto == "unix":
                reader, _ = await asyncio.open_unix_connection(*proto_args)
            else:
                assert False
            while True:
                data = await reader.read(512)
                await pcm_iface.write(data)
                await pcm_iface.flush(wait=False)

# -------------------------------------------------------------------------------------------------

class AudioDACAppletTestCase(GlasgowAppletTestCase, applet=AudioDACApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
