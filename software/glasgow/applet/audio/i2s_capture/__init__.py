import enum
import asyncio
import logging
import argparse
import wave
from functools import reduce
from nmigen import *
from nmigen.lib.cdc import FFSynchronizer

from ....gateware.pads import *
from ... import *


RATE_MEASURE_EVENTS=32
STREAM_TIMEOUT=0.25 # 250ms

class _Command(enum.IntEnum):
    BIT_RATE   = 0x00
    SAMPLE_RATE = 0x01
    CAPTURE   = 0x02


class SyncException(Exception):
    pass


class AudioI2SCaptureSubtarget(Elaboratable):
    def __init__(self, pads, fifos, leds, reg_busy, reg_fault, reg_rate,
                 reg_samp_size, clk_edge="r", mode="i2s", stream_timeout=12000000):
        self.pads = pads
        self.in_fifo, self.out_fifo = fifos

        self.led_ovf        = leds[0]
        self.led_fault      = leds[1]
        self.led_run        = leds[2]

        self.reg_busy       = reg_busy
        self.reg_fault      = reg_fault
        self.reg_rate       = reg_rate
        self.reg_samp_size  = reg_samp_size

        self.clk_edge       = clk_edge
        self.mode           = mode
        self.stream_timeout = stream_timeout

    def elaborate(self, platform):
        m = Module()

        # -- bit clock

        clk_i = Signal.like(self.pads.clk_t.i)
        m.submodules += FFSynchronizer(self.pads.clk_t.i,  clk_i)

        clk_edge = Signal(2)
        clk      = Signal()
        m.d.sync += clk_edge.eq(Cat(clk_i, clk_edge[:-1]))
        if self.clk_edge in ("r", "rising"):
            m.d.comb += clk.eq(clk_edge == 0b01)
        elif self.clk_edge in ("f", "falling"):
            m.d.comb += clk.eq(clk_edge == 0b10)
        else:
            assert False

        # -- frame sync

        fs_i = Signal.like(self.pads.fs_t.i)
        m.submodules += FFSynchronizer(self.pads.fs_t.i,   fs_i),

        frame_edge  = Signal(3)
        frame_start = Signal()
        word_start  = Signal()
        with m.If(clk):
            m.d.sync += frame_edge.eq(Cat(fs_i, frame_edge[:-1]))
        if self.mode == "i2s":
            # For I2S, the data is shifted 1-bit after the frame sync
            m.d.comb += [
                frame_start.eq(frame_edge == 0b100),
                word_start.eq((frame_edge == 0b100) | (frame_edge == 0b011)),
            ]
        elif self.mode == "pcm":
            # For PCM, the data is aligned with the frame sync
            m.d.comb += [
                frame_start.eq(frame_edge == 0b110),
                word_start.eq((frame_edge == 0b110) | (frame_edge == 0b001)),
            ]
        else:
            assert False

        # -- data input

        data_i = Signal.like(self.pads.data_t.i)
        m.submodules += FFSynchronizer(self.pads.data_t.i, data_i)

        # -- leds

        m.d.comb += [
            self.led_ovf.eq(~self.in_fifo.w_rdy),
            self.led_fault.eq(self.reg_fault),
            self.led_run.eq(self.reg_busy),
        ]

        # --

        timeout_cyc = Signal(range(self.stream_timeout))
        timeout_esc = Signal()
        def timeout(reset):
            with m.If(reset):
                m.d.sync += timeout_cyc.eq(self.stream_timeout)
            with m.Elif(~timeout_esc):
                m.d.sync += timeout_cyc.eq(timeout_cyc - 1)
            with m.If(timeout_cyc == 0):
                m.next = "COMMAND"

        # --

        count       = Signal(8)
        data_sr     = Signal(8)

        rate_src    = Signal()
        rate_sig    = Mux(rate_src, clk & frame_start, clk)

        with m.FSM() as fsm:
            m.d.comb += self.reg_busy.eq(~fsm.ongoing("COMMAND"))

            with m.State("COMMAND"):
                with m.If(self.out_fifo.r_rdy):
                    m.d.comb += self.out_fifo.r_en.eq(1)
                    m.d.sync += self.reg_fault.eq(0)
                    with m.Switch(self.out_fifo.r_data):
                        with m.Case(_Command.BIT_RATE):
                            m.d.sync += rate_src.eq(0)
                            m.next = "RATE-WAIT"
                        with m.Case(_Command.SAMPLE_RATE):
                            m.d.sync += rate_src.eq(1)
                            m.next = "RATE-WAIT"
                        with m.Case(_Command.CAPTURE):
                            m.d.sync += [
                                timeout_cyc.eq(self.stream_timeout),
                                timeout_esc.eq(1),
                            ]
                            m.next = "CAPTURE-WORD-WAIT"

            with m.State("FAULT"):
                m.d.sync += self.reg_fault.eq(1)
                m.next = "COMMAND"

            with m.State("RATE-WAIT"):
                with m.If(rate_sig):
                    m.d.sync += [
                        count.eq(RATE_MEASURE_EVENTS),
                        self.reg_rate.eq(0),
                    ]
                    m.next = "RATE-COUNT"
            with m.State("RATE-COUNT"):
                m.d.sync += self.reg_rate.eq(self.reg_rate + 1)
                with m.If(rate_sig):
                    m.d.sync += count.eq(count - 1)
                with m.If(count == 0):
                    m.next = "COMMAND"

            with m.State("CAPTURE-WORD-WAIT"):
                timeout(word_start)
                with m.If(word_start):
                    frame_header = Cat(fs_i, Const(0xC0 >> 1, unsigned(7)))
                    m.d.sync += [
                        timeout_esc.eq(0),
                        data_sr.eq(0),
                        count.eq(self.reg_samp_size - 1),
                        self.in_fifo.w_data.eq(frame_header),
                    ]
                    m.next = "CAPTURE-HEADER"
            with m.State("CAPTURE-HEADER"):
                with m.If(~self.in_fifo.w_rdy):
                    m.next = "FAULT"
                with m.Else():
                    m.d.comb += self.in_fifo.w_en.eq(1),
                    m.next = "CAPTURE-DATA-SAMPLE"
            with m.State("CAPTURE-DATA-SAMPLE"):
                data_next = Cat(data_i, data_sr[:-1])
                m.d.sync += data_sr.eq(data_next)
                with m.If((count % 8) == 0):
                    m.d.sync += self.in_fifo.w_data.eq(data_next)
                    m.next = "CAPTURE-DATA-TX"
                with m.Else():
                    m.next = "CAPTURE-DATA-WAIT"
            with m.State("CAPTURE-DATA-TX"):
                with m.If(~self.in_fifo.w_rdy):
                    m.next = "FAULT"
                with m.Else():
                    m.d.comb += self.in_fifo.w_en.eq(1),
                    with m.If(count != 0):
                        m.next = "CAPTURE-DATA-WAIT"
                    with m.Else():
                        m.next = "CAPTURE-WORD-WAIT"
            with m.State("CAPTURE-DATA-WAIT"):
                timeout(clk)
                with m.If(clk):
                    m.d.sync += count.eq(count - 1)
                    m.next = "CAPTURE-DATA-SAMPLE"

        return m


class AudioI2SCaptureApplet(GlasgowApplet, name='audio-i2s-capture'):
    logger = logging.getLogger(__name__)
    preview = True
    help = "capture I2S audio to a WAV file"
    description = """
    Capture stereo audio that is transmitted via I2S.
    """
    required_revision = "C0"

    __pins = ("clk", "fs", "data")

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        for pin in cls.__pins:
            access.add_pin_argument(parser, pin, default=True)

        parser.add_argument(
            "--clk-edge", metavar="EDGE", type=str, choices=["r", "rising", "f", "falling"],
            default="rising",
            help="latch data at clock edge EDGE (default: %(default)s)")
        parser.add_argument(
            "-m", "--mode", metavar="MODE", type=str, choices=["i2s", "pcm"], default="i2s",
            help="I2S mode has data shifted 1 bit after FS. "
                 "PCM mode has data in line with FS. "
                 "(default: %(default)s)")
        parser.add_argument(
            "-t", "--timeout", metavar="SEC", type=float, default=0.25,
            help="the timeout after the stream stops (default: %(default)s)")

    def build(self, target, args):
        self.sys_clk_freq = target.sys_clk_freq
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)

        reg_busy,      self.__reg_busy      = target.registers.add_ro(1)
        reg_fault,     self.__reg_fault     = target.registers.add_ro(1)
        reg_rate,      self.__reg_rate      = target.registers.add_ro(32)
        reg_samp_size, self.__reg_samp_size = target.registers.add_rw(32)

        stream_timeout = int(target.sys_clk_freq * STREAM_TIMEOUT)

        iface.add_subtarget(AudioI2SCaptureSubtarget(
            pads=iface.get_pads(args, pins=self.__pins),
            fifos=(
                iface.get_in_fifo(auto_flush=False),
                iface.get_out_fifo(),
            ),
            leds=[ target.platform.request("led", _) for _ in range(5) ],
            reg_busy=reg_busy,
            reg_fault=reg_fault,
            reg_rate=reg_rate,
            reg_samp_size=reg_samp_size,
            clk_edge=args.clk_edge,
            mode=args.mode,
            stream_timeout=stream_timeout,
        ))

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)

        parser.add_argument(
            "-r", "--sample-rate", metavar="HZ", type=float, default=None,
            help="the sample rate. (default: auto detect)")
        parser.add_argument(
            "-s", "--sample-size", metavar="SIZE", type=int, default=16,
            help="the size (in bits) of each sample value (default: %(default)s)")
        parser.add_argument(
            "filename", metavar="FILENAME", type=argparse.FileType("wb"),
            help="the output filename")

    def _decode_frame_buf(self, frame_buf):
        if len(frame_buf) < 2:
            raise SyncException('invalid buffer length ({})'.format(len(frame_buf)))

        header = frame_buf[0]
        payload = frame_buf[1:]

        if (header & 0xFE) != 0xC0:
            raise SyncException('invalid header ({:02x})'.format(header))

        channel = header & 0x01 # 0 = left, 1 = right
        sample = bytes(payload[::-1])

        return channel, sample

    async def _gen_samples(self, args, iface, sample_size):
        frame_buf_len = 1 + (sample_size // 8)
        if sample_size % 8:
            frame_buf_len += 1

        i = 0
        pos = 0
        buf = []
        timeout = None
        while True:
            if pos > 0:
                buf = buf[pos:]

            buf.extend(await asyncio.wait_for(iface.read(), timeout=timeout))
            timeout = STREAM_TIMEOUT * 2

            pos = 0
            while (pos + frame_buf_len) < len(buf):
                try:
                    channel, sample = self._decode_frame_buf(buf[pos:pos+frame_buf_len])
                    yield i, channel, sample
                    i += 1
                    pos += frame_buf_len
                except SyncException as e:
                    print(e)
                    pos += 1

    async def _is_fault(self, device):
        return await device.read_register(self.__reg_fault, width=1)

    async def _is_busy(self, device):
        return await device.read_register(self.__reg_busy, width=1)

    async def _wait_idle(self, device):
        while await self._is_busy(device):
            await asyncio.sleep(0.1)

    async def _get_rate(self, iface, device, command):
        await iface.write([ command ])
        await iface.flush()
        await self._wait_idle(device)
        reg_val = await device.read_register(self.__reg_rate, width=4)
        rate = self.sys_clk_freq / ( reg_val / RATE_MEASURE_EVENTS )
        return rate

    async def get_bit_rate(self, iface, device):
        return await self._get_rate(iface, device, _Command.BIT_RATE)

    async def get_sample_rate(self, iface, device):
        return await self._get_rate(iface, device, _Command.SAMPLE_RATE)

    async def autodetect_rates(self, iface, device):
        bit_rate = await self.get_bit_rate(iface, device)
        sample_rate = await self.get_sample_rate(iface, device)
        sample_size = bit_rate / sample_rate / 2

        common_sample_rates = [   8000,  11025,  16000,  22050,  32000,
                                 44100,  48000,  96000, 176400, 192000, ]
        closest_sample_rate = min(common_sample_rates, key=lambda n: abs(n - sample_rate))
        sample_rate_error = abs(1 - (closest_sample_rate / sample_rate))
        if sample_rate_error > 0.02:
            self.logger.warning("The measured sample rate vs. closest common sample rate error "
                                "is greater than 2%")

        common_sample_sizes = [ 8, 16, 24, 32, ]
        closest_sample_size = min(common_sample_sizes, key=lambda n: abs(n - sample_size))
        sample_size_error = abs(1 - (closest_sample_size / sample_size))
        if sample_size_error > 0.02:
            self.logger.warning("The measured sample size vs. closest common sample size error "
                                "is greater than 2%")

        self.logger.info("Measured bit rate:    %10.2f Hz", bit_rate)
        self.logger.info("Measured sample rate: %10.2f Hz      Using sample rate: %8d Hz",
                         sample_rate, closest_sample_rate)
        self.logger.info("Measured sample size: %9.1f  bits    Using sample size: %7d  bits",
                         sample_size, closest_sample_size)

        return closest_sample_rate, closest_sample_size

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)

        if sum(_ is None for _ in ( args.sample_size, args.sample_rate )) == 1:
            self.logger.warning("When giving only one of --sample-size and --sample-rate, "
                                "both will be auto-detected...")

        if args.sample_rate is None or args.sample_size is None:
            self.logger.info("Measuring stream attributes...")
            sample_rate, sample_size = await self.autodetect_rates(iface, device)
        else:
            sample_rate = args.sample_rate
            sample_size = args.sample_size

        await device.write_register(self.__reg_samp_size, sample_size, width=4)

        self.logger.info("Capturing stream...")
        await iface.write([ _Command.CAPTURE ])
        await iface.flush()

        with wave.openfp(args.filename) as f:
            f.setnchannels(2)
            f.setsampwidth(sample_size // 8)
            f.setframerate(sample_rate)

            try:
                async for i, channel, sample in self._gen_samples(args, iface, sample_size):
                    f.writeframes(sample)
            except asyncio.TimeoutError:
                pass

        self.logger.info("Stream ended...")

        if await self._is_fault(device):
            self.logger.error("A fault ocurred while capturing (too high bitrate?)")
