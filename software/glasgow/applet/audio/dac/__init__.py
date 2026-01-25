from typing import Literal
import logging
import asyncio
import argparse

from amaranth import *
from amaranth.lib import wiring, stream, io
from amaranth.lib.wiring import In, Out

from glasgow.support.endpoint import ServerEndpoint
from glasgow.abstract import AbstractAssembly, GlasgowPin, ClockDivisor
from glasgow.applet import GlasgowAppletV2


__all__ = ["AudioDACComponent", "AudioDACInterface"]


class SigmaDeltaDACChannel(wiring.Component):
    def __init__(self, bits, signed):
        self.bits   = bits
        self.signed = signed

        super().__init__({
            "input":  In(bits), # PCM code (signed or unsigned)
            "update": In(1),    # update input, for multi-channel synchronization

            "output": Out(1),   # PDM pulse train
            "strobe": In(1),    # strobe input; adds code to accumulator and updates `output`
        })

    def elaborate(self, platform):
        m = Module()

        # Glasgow has unipolar supply, so signed 0 needs to become Vcc/2.
        level = Signal(self.bits)
        with m.If(self.update):
            if self.signed:
                m.d.sync += level.eq(self.input - (1 << (self.bits - 1)))
            else:
                m.d.sync += level.eq(self.input)

        # Carry out from the accumulator generates the PDM pulse train.
        accum = Signal(self.bits)
        with m.If(self.strobe):
            m.d.sync += Cat(accum, self.output).eq(accum + level)

        return m


class AudioDACComponent(wiring.Component):
    i_stream: In(stream.Signature(8))

    sample_divisor:     In(16)
    modulation_divisor: In(16)

    def __init__(self, ports: io.PortLike, *, width: Literal[1, 2], signed: bool):
        assert width in (1, 2)

        self._ports  = ports
        self._width  = width
        self._signed = signed

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.o_buffer = o_buffer = io.Buffer("o", self._ports)
        m.submodules += (channels := [
            SigmaDeltaDACChannel(bits=self._width * 8, signed=self._signed)
            for _ in range(len(o_buffer.o))
        ])
        m.d.comb += o_buffer.o.eq(Cat(channel.output for channel in channels))

        sample_timer     = Signal.like(self.sample_divisor)
        modulation_timer = Signal.like(self.modulation_divisor)
        modulation_stb   = Signal()

        with m.If(modulation_timer == 0):
            m.d.comb += modulation_stb.eq(1)
            m.d.sync += modulation_timer.eq(self.modulation_divisor)
        with m.Else():
            m.d.sync += modulation_timer.eq(modulation_timer-1)

        for channel in channels:
            m.d.comb += channel.strobe.eq(modulation_stb)

        with m.FSM():
            with m.State("STANDBY"):
                m.d.sync += o_buffer.oe.eq(0)
                with m.If(self.i_stream.valid):
                    m.d.sync += o_buffer.oe.eq(1)
                    m.next = "WAIT"

            with m.State("WAIT"):
                with m.If(sample_timer == 0):
                    m.d.sync += sample_timer.eq(
                        self.sample_divisor - len(channels) * self._width - 1)
                    m.next = "CHANNEL-0-READ-1"
                with m.Else():
                    m.d.sync += sample_timer.eq(sample_timer - 1)

            for index, channel in enumerate(channels):
                if index + 1 < len(channels):
                    next_state = f"CHANNEL-{index+1}-READ-1"
                else:
                    next_state = "LATCH"
                if self._width == 1:
                    with m.State(f"CHANNEL-{index}-READ-1"):
                        m.d.comb += self.i_stream.ready.eq(1)
                        with m.If(self.i_stream.valid):
                            m.d.sync += channel.input[0:8].eq(self.i_stream.payload)
                            m.next = next_state
                        with m.Else():
                            m.next = "STANDBY"
                if self._width == 2:
                    with m.State(f"CHANNEL-{index}-READ-1"):
                        m.d.comb += self.i_stream.ready.eq(1)
                        with m.If(self.i_stream.valid):
                            m.d.sync += channel.input[0:8].eq(self.i_stream.payload)
                            m.next = f"CHANNEL-{index}-READ-2"
                        with m.Else():
                            m.next = "STANDBY"
                    with m.State(f"CHANNEL-{index}-READ-2"):
                        m.d.comb += self.i_stream.ready.eq(1)
                        with m.If(self.i_stream.valid):
                            m.d.sync += channel.input[8:16].eq(self.i_stream.payload)
                            m.next = next_state
                        with m.Else():
                            m.next = "STANDBY"

            with m.State("LATCH"):
                m.d.comb += [ channel.update.eq(1) for channel in channels ]
                m.next = "WAIT"

        return m


class AudioDACInterface:
    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
                 pins: tuple[GlasgowPin], width: Literal[1, 2], signed: bool):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        component = assembly.add_submodule(AudioDACComponent(assembly.add_port(pins, name="dac"),
                                                             width=width, signed=signed))
        # The buffer size should be limited to prevent the buffer size growing unboundedly
        # 1e6 was ~arbitrarily chosen
        self._pipe = assembly.add_out_pipe(component.i_stream, buffer_size=1e6)
        self._sample_clock = assembly.add_clock_divisor(
            component.sample_divisor,
            ref_period=assembly.sys_clk_period,
            # Drift of sampling clock is extremely bad, so ensure it only happens insofar as
            # the oscillator on the board is imprecise, and with no additional error.
            tolerance=0,
            round_mode="nearest",
            name="sampling"
        )
        self._modulation_clock = assembly.add_clock_divisor(
            component.modulation_divisor,
            ref_period=assembly.sys_clk_period,
            name="modulation"
        )

    @property
    def sample_clock(self) -> ClockDivisor:
        """Sampling clock divisor."""
        return self._sample_clock

    @property
    def modulation_clock(self) -> ClockDivisor:
        """Modulation clock divisor."""
        return self._modulation_clock

    async def write(self, pcm_data: bytes | bytearray | memoryview):
        """Send samples to the DAC to be played in round robin order."""
        await self._pipe.send(pcm_data)

    async def flush(self):
        """Ensure any past writes have reached the device FIFO."""
        await self._pipe.flush()


class AudioDACApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "play sound using a ΣΔ-DAC"
    description = """
    Play sound using a 1-bit sigma-delta DAC, i.e. pulse density modulation.

    Currently, the supported sample formats are:
        * 1..16 channel signed/unsigned 8-bit,
        * 1..16 channel signed/unsigned 16-bit little endian.

    Other formats may be converted to it using:

    ::

        $ sox <input> -c <channels> -r <rate> <output>.<u8|u16>

    For example, to play an ogg file:

    ::

        $ sox samples.ogg -c 2 -r 48000 samples.u16
        $ glasgow run audio-dac -V 3.3 --o A0,A1 -r 48000 -w 2 -u play samples.u16

    To use the DAC as a PulseAudio sink, add the following line to default.pa:

    ::

        load-module module-simple-protocol-tcp source=0 record=true rate=48000 channels=2 \
format=s16le port=12345

    Then run:

    ::

        $ glasgow run audio-dac -V 3.3 --o A0,A1 -r 48000 -w 2 -s connect tcp::12345
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "o", width=range(1, 17), default=1)

        parser.add_argument(
            "-w", "--width", metavar="WIDTH", type=int, default=1, choices=(1, 2),
            help="set sample width to WIDTH bytes (default: %(default)d)")
        g_signed = parser.add_mutually_exclusive_group(required=True)
        g_signed.add_argument(
            "-s", "--signed", dest="signed", default=False, action="store_true",
            help="interpret samples as signed")
        g_signed.add_argument(
            "-u", "--unsigned", dest="signed", action="store_false",
            help="interpret samples as unsigned")

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.pcm_iface = AudioDACInterface(self.logger, self.assembly, pins=args.o,
                                               width=args.width, signed=args.signed)

    @classmethod
    def add_setup_arguments(cls, parser):
        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int,
            help="set modulation frequency to FREQ MHz (default: maximum)")
        parser.add_argument(
            "-r", "--sample-rate", metavar="RATE", type=int, default=8000,
            help="set sample rate to RATE Hz (default: %(default)d)")

    async def setup(self, args):
        if args.frequency is None:
            await self.pcm_iface.modulation_clock.set_frequency(1/self.assembly.sys_clk_period)
        else:
            await self.pcm_iface.modulation_clock.set_frequency(args.frequency)
        await self.pcm_iface.sample_clock.set_frequency(args.sample_rate)

    @classmethod
    def add_run_arguments(cls, parser):
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

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

    async def run(self, args):
        if args.operation == "play":
            pcm_data = args.file.read()
            while True:
                await self.pcm_iface.write(pcm_data)
                if not args.loop:
                    await self.pcm_iface.flush()
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
                await self.pcm_iface.write(data)

    @classmethod
    def tests(cls):
        from . import test
        return test.AudioDACAppletTestCase
