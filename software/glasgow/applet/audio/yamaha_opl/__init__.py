# Ref: CATALOG No. LSI-2130143 (YM3014B)
# Accession: G00001
# Ref: CATALOG No. LSI-2138123 (YM3812)
# Accession: G00002
# Ref: CATALOG No. LSI-2438124 (YM3812 Application Manual)
# Accession: G00003

# Glaring omissions
# -----------------
#
# The documentation (which often serves more to confuse than to document), has plenty of typos
# and omits critical parts. A brief list of datasheet issues, most of which are common for
# the entire OPL series:
#  * Pin 1 is VCC, not VSS as on the diagram.
#  * ~RD and ~WR are active low, unlike what the truth table implies.
#  * The timing diagrams are incomplete. They imply reads and writes are asynchronous. This is
#    only partially true. There is a latency in terms of master clock cycles after each write,
#    which differs from series to series and from address to data.
#     - OPLL/OPL(?)/OPL2(?): address 12 cycles, data 84 cycles. (only documented for OPLL)
#     - OPL3: address 32 cycles, data 32 cycles. (documented)
#  * The timing diagrams are sometimes absurd. YMF278 datasheet figure 1-5 implies that the data
#    bus is stable for precisely tRDS (which is, incidentally, not defined anywhere) before
#    the ~RD rising edge, which would imply time travel. YM3812 datasheet figure A-3 is actually
#    physically possible.
#
# Bitstream format
# ----------------
#
# The Yamaha DAC bitstream fromat is somewhat underdocumented and confusing. The DAC bitstream
# has 16 bit dynamic range and uses 13 bit samples in a bespoke floating point format. These 13 bit
# samples are padded to 16 bits and transmitted over a serial protocol similar to I²S.
#
# The sample format is as follows, transmitted on wire LSB first:
#  (LSB)                                                                       (MSB)
#  +----+----+----+----+----+----+----+----+----+----+----+----+----+----+----+----+
#  | 0  | 0  | 0  | M0 | M1 | M2 | M3 | M4 | M5 | M6 | M7 | M8 | S  | E0 | E1 | E2 |
#  +----+----+----+----+----+----+----+----+----+----+----+----+----+----+----+----+
#
# Each sample defines a 9-bit M(antissa), 1-bit S(ign) and 3-bit E(exponent). The legal values
# for the exponent are 1..7. The sample format does not appear to follow any intrinsic structure
# and seems to have been chosen for the simplicity of DAC implementation alone. Therefore, no
# attempt is made here to describe the sample format in abstract terms.
#
# The DAC transfer function, which converts DAC bitstream to unsigned 16-bit voltage levels,
# is as follows, in a Verilog-like syntax:
#     assign V = {S, {{7{~S}}, M, 7'b0000000}[E+:15]};
#
# Compatibility modes
# -------------------
#
# Yamaha chips that have compatibility features implement them in a somewhat broken way. When
# the compatibility feature is disabled (e.g. bit 5 of 0x01 TEST for YM3812), its registers are
# masked off. However, the actual feature is still (partially) enabled and it will result in
# broken playback if this is not accounted for. Therefore, for example, the reset sequence has to
# enable all available advanced features, zero out the registers, and then disable them back for
# compatibility with OPL clients that expect the compatibility mode to be on.
#
# Bus cycles
# ----------
#
# The CPU bus interface is asynchronous to master or DAC clock, but is heavily registered (see
# the next section). Writes are referenced to the ~WR rising edge, and require chip-specific
# wait states. Reads are referenced to ~RD falling edge, and always read exactly one register,
# although there might be undocumented registers elsewhere.
#
# Register latency
# ----------------
#
# Many Yamaha chips physically implement the register file as a kind of bucket brigade device, or
# a giant multibit shift register, as opposed to a multiport RAM. This goes hand in hand with
# there being only one physical operator on the chip. On YM3812, the shift register makes one
# revolution per one sample clock, and therefore any write has to be latched from the bus into
# an intermediate area, and wait until the right register travels to the physical write port.
# On YM3812, the latch latency is 12 cycles and the sample takes 72 clocks, therefore each
# address/data write cycle takes 12+12+72 clocks.
#
# On some chips (e.g OPL4) the register that can be read has a busy bit, which seems to be always
# the LSB. On many others (e.g. OPL3) there is no busy bit. Whether the busy bit is available
# on any given silicon seems pretty arbitrary.
#
# VGM timeline
# ------------
#
# The VGM file format assumes that writes happen instantaneously. They do not. On YM3812, a write
# takes slightly more than one YM3812 sample clock (which is slightly less than one VGM sample
# clock). This means that two YM3812 writes followed by a 1 sample delay in VGM "invalidate"
# the delay, by borrowing time from it.
#
# Overclocking
# ------------
#
# It's useful to overclock the synthesizer to get results faster than realtime. Since it's fully
# synchronous digital logic, that doesn't generally affect the output until it breaks.
#
#   * YM3812 stops working between 15 MHz (good) and 30 MHz (bad).

from abc import ABCMeta, abstractmethod
import os.path
import logging
import argparse
import struct
import array
import asyncio
import aiohttp.web as web
import hashlib
import base64
import gzip
import io
from migen import *
from migen.genlib.cdc import MultiReg

from ....gateware.pads import *
from ....gateware.clockgen import *
from ....protocol.vgm import *
from ... import *


class YamahaCPUBus(Module):
    def __init__(self, pads, master_cyc):
        self.stb_m = Signal()

        self.a  = Signal(2)

        self.oe = Signal(reset=1)
        self.di = Signal(8)
        self.do = Signal(8)

        self.cs = Signal()
        self.rd = Signal()
        self.wr = Signal()

        ###

        self.submodules.clkgen = ClockGen(master_cyc)
        self.comb += self.stb_m.eq(self.clkgen.stb_r)

        self.comb += [
            pads.clk_m_t.oe.eq(1),
            pads.clk_m_t.o.eq(self.clkgen.clk),
            pads.a_t.oe.eq(1),
            pads.a_t.o.eq(self.a),
            pads.d_t.oe.eq(self.oe),
            pads.d_t.o.eq(Cat((self.do))),
            self.di.eq(Cat((pads.d_t.i))),
            # handle (self.rd & (self.wr | self.oe)) == 1 safely
            pads.rd_t.oe.eq(1),
            pads.rd_t.o.eq(~(self.rd & ~self.wr & ~self.oe)),
            pads.wr_t.oe.eq(1),
            pads.wr_t.o.eq(~(self.wr & ~self.rd)),
        ]
        if hasattr(pads, "cs_t"):
            self.comb += [
                pads.cs_t.oe.eq(1),
                pads.cs_t.o.eq(~self.cs),
            ]


class YamahaDACBus(Module):
    def __init__(self, pads):
        self.stb_sy = Signal()
        self.stb_sh = Signal()

        self.sh = Signal()
        self.mo = Signal()

        clk_sy_s = Signal()
        clk_sy_r = Signal()
        self.sync += [
            clk_sy_r.eq(clk_sy_s),
            self.stb_sy.eq(~clk_sy_r & clk_sy_s)
        ]

        sh_r = Signal()
        self.sync += [
            sh_r.eq(self.sh),
            self.stb_sh.eq(sh_r & ~self.sh)
        ]

        self.specials += [
            MultiReg(pads.clk_sy_t.i, clk_sy_s),
            MultiReg(pads.sh_t.i, self.sh),
            MultiReg(pads.mo_t.i, self.mo)
        ]


OP_ENABLE = 0x00
OP_WRITE  = 0x10
OP_READ   = 0x20
OP_WAIT   = 0x30
OP_MASK   = 0xf0


class YamahaOPxSubtarget(Module):
    def __init__(self, pads, in_fifo, out_fifo,
                 master_cyc, read_pulse_cyc, write_pulse_cyc,
                 address_clocks, data_clocks):
        self.submodules.cpu_bus = cpu_bus = YamahaCPUBus(pads, master_cyc)
        self.submodules.dac_bus = dac_bus = YamahaDACBus(pads)

        # Control

        pulse_timer = Signal(max=max(read_pulse_cyc, write_pulse_cyc))
        wait_timer  = Signal(16)

        enabled     = Signal()

        # The code below assumes that the FSM clock is under ~50 MHz, which frees us from the need
        # to explicitly satisfy setup/hold timings.
        self.submodules.control_fsm = FSM()
        self.control_fsm.act("IDLE",
            NextValue(cpu_bus.oe, 1),
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                Case(out_fifo.dout & OP_MASK, {
                    OP_ENABLE: [
                        NextValue(enabled, out_fifo.dout & ~OP_MASK),
                    ],
                    OP_WRITE:  [
                        NextValue(cpu_bus.a, out_fifo.dout & ~OP_MASK),
                        NextState("WRITE-DATA")
                    ],
                    # OP_READ: NextState("READ"),
                    OP_WAIT: [
                        NextState("WAIT-H-BYTE")
                    ]
                })
            )
        )
        self.control_fsm.act("WRITE-DATA",
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(cpu_bus.do, out_fifo.dout),
                NextValue(cpu_bus.cs, 1),
                NextValue(cpu_bus.wr, 1),
                NextValue(pulse_timer, write_pulse_cyc - 1),
                NextState("WRITE-PULSE")
            )
        )
        self.control_fsm.act("WRITE-PULSE",
            If(pulse_timer == 0,
                NextValue(cpu_bus.cs, 0),
                NextValue(cpu_bus.wr, 0),
                If(cpu_bus.a[0] == 0b0,
                    NextValue(wait_timer, address_clocks - 1)
                ).Else(
                    NextValue(wait_timer, data_clocks - 1)
                ),
                NextState("WAIT-LOOP")
            ).Else(
                NextValue(pulse_timer, pulse_timer - 1)
            )
        )
        self.control_fsm.act("WAIT-H-BYTE",
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(wait_timer[8:16], out_fifo.dout),
                NextState("WAIT-L-BYTE")
            )
        )
        self.control_fsm.act("WAIT-L-BYTE",
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(wait_timer[0:8], out_fifo.dout),
                NextState("WAIT-LOOP")
            )
        )
        self.control_fsm.act("WAIT-LOOP",
            If(wait_timer == 0,
                NextState("IDLE")
            ).Else(
                If(cpu_bus.stb_m,
                    NextValue(wait_timer, wait_timer - 1)
                )
            )
        )

        # Audio

        xfer_i = Record([
            ("z", 3),
            ("m", 9),
            ("s", 1),
            ("e", 3)
        ])
        xfer_o = Signal(16)
        self.comb += [
            # FIXME: this is uglier than necessary because of Migen bugs. Rewrite nicer in nMigen.
            xfer_o.eq(Cat((Cat(xfer_i.m, Replicate(~xfer_i.s, 7)) << xfer_i.e)[1:16], xfer_i.s))
        ]

        data_r = Signal(16)
        data_l = Signal(16)
        self.sync += If(dac_bus.stb_sy, data_r.eq(Cat(data_r[1:], dac_bus.mo)))
        self.comb += xfer_i.raw_bits().eq(data_l)

        self.submodules.data_fsm = FSM()
        self.data_fsm.act("WAIT-SH",
            NextValue(in_fifo.flush, ~enabled),
            If(dac_bus.stb_sh & enabled,
                NextState("SAMPLE")
            )
        )
        self.data_fsm.act("SAMPLE",
            NextValue(data_l, data_r),
            NextState("SEND-L-BYTE")
        )
        self.data_fsm.act("SEND-L-BYTE",
            in_fifo.din.eq(xfer_o[0:8]),
            in_fifo.we.eq(1),
            If(in_fifo.writable,
                NextState("SEND-H-BYTE")
            )
        )
        self.data_fsm.act("SEND-H-BYTE",
            in_fifo.din.eq(xfer_o[8:16]),
            in_fifo.we.eq(1),
            If(in_fifo.writable,
                NextState("WAIT-SH")
            )
        )


class YamahaOPxInterface(metaclass=ABCMeta):
    chips = []

    def __init__(self, interface, logger, instant_writes=True):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        # Adjust delays such that earlier writes borrow from later delays. Useful for VGM files,
        # where writes are unphysically assumed to take no time.
        self._instant_writes = instant_writes
        self._phase_accum    = 0

        self._feature_level  = 1
        self._feature_warned = False

    @abstractmethod
    def get_vgm_clock_rate(self, vgm_reader):
        pass

    address_clocks = None
    data_clocks    = None
    sample_clocks  = None

    @property
    def write_clocks(self):
        return self.address_clocks + self.data_clocks

    def _log(self, message, *args, level=None):
        self._logger.log(self._level if level is None else level, "OPx: " + message, *args)

    _registers = []

    async def reset(self):
        self._log("reset")
        await self.lower.reset()
        # Reset the synthesizer in software; some of them appear to have broken reset via ~IC pin,
        # and in any case this frees up one Glasgow pin, which we are short on. VGM files often
        # do not reset the chip appropriately, nor do they always terminate cleanly, so this is
        # necessary to get a reproducible result.
        old_instant_writes, self._instant_writes = self._instant_writes, False
        await self._reset_registers()
        self._instant_writes = old_instant_writes

    async def _use_highest_level(self):
        pass

    async def _use_lowest_level(self):
        pass

    async def _reset_registers(self):
        await self._use_highest_level()
        for addr in self._registers:
            await self.write_register(addr, 0x00, check_feature=False)
        await self._use_lowest_level()
        self._feature_level  = 1
        self._feature_warned = False

    async def enable(self):
        self._log("enable")
        await self.lower.write([OP_ENABLE|1])
        # Wait until the commands start arriving before flushing the enable command.

    async def disable(self):
        self._log("disable")
        await self.lower.write([OP_ENABLE|0])
        await self.lower.flush()

    def _enable_level(self, feature_level):
        if self._feature_level < feature_level:
            self._feature_level = feature_level
            self._log("enabled feature level %d",
                      self._feature_level)

    def _check_level(self, feature, feature_level):
        if not self._feature_warned and self._feature_level < feature_level:
            self._feature_warned = True
            self._log("client uses feature [%#04x] with level %d, but only level %d is enabled",
                      feature, feature_level, self._feature_level,
                      level=logging.WARN)
            self._log("retrying with level %d enabled",
                      feature_level,
                      level=logging.WARN)
            return True
        return False

    async def _check_enable_features(self, address, data):
        if address not in self._registers:
            self._log("client uses undefined feature [%#04x]",
                      address,
                      level=logging.WARN)

    async def write_register(self, address, data, check_feature=True):
        if check_feature:
            await self._check_enable_features(address, data)
        if self._instant_writes:
            old_phase_accum = self._phase_accum
            self._phase_accum += self.write_clocks
            self._log("write [%#04x]=%#04x; phase: %d→%d",
                      address, data, old_phase_accum, self._phase_accum)
        else:
            self._log("write [%#04x]=%#04x",
                      address, data)
        addr_high = (address >> 8) << 1
        addr_low  = address & 0xff
        await self.lower.write([OP_WRITE|addr_high|0, addr_low, OP_WRITE|1, data])

    async def wait_clocks(self, count):
        if self._instant_writes:
            old_phase_accum = self._phase_accum
            self._phase_accum -= count
            old_count = count
            if self._phase_accum < 0:
                count = -self._phase_accum
                self._phase_accum = 0
            else:
                count = 0
            self._log("wait %d→%d clocks; phase: %d→%d",
                      old_count, count, old_phase_accum, self._phase_accum)
        else:
            self._log("wait %d clocks",
                      count)
        while count > 65535:
            await self.lower.write([OP_WAIT, *struct.pack(">H", 65535)])
            count -= 65535
        await self.lower.write([OP_WAIT, *struct.pack(">H", count)])
        await self.lower.flush()

    async def read_samples(self, count):
        self._log("read %d samples", count)
        return await self.lower.read(count * 2)


class YamahaOPLInterface(YamahaOPxInterface):
    chips = ["YM3526 (OPL)"]

    def get_vgm_clock_rate(self, vgm_reader):
        return vgm_reader.ym3526_clk

    address_clocks = 12
    data_clocks    = 84
    sample_clocks  = 72

    _registers = [
        0x02, 0x03, 0x04, 0x08, *range(0x20, 0x36), *range(0x40, 0x56), *range(0x60, 0x76),
        *range(0x80, 0x96), *range(0xA0, 0xA9), *range(0xB0, 0xB9), 0xBD, *range(0xC0, 0xC9)
    ]

    async def _check_enable_features(self, address, data):
        if address == 0x01 and data == 0x00:
            pass
        else:
            await super()._check_enable_features(address, data)


class YamahaOPL2Interface(YamahaOPLInterface):
    chips = YamahaOPLInterface.chips + ["YM3812 (OPL2)"]

    def get_vgm_clock_rate(self, vgm_reader):
        return vgm_reader.ym3812_clk or YamahaOPLInterface.get_vgm_clock_rate(self, vgm_reader)

    _registers = YamahaOPLInterface._registers + [
        *range(0xE0, 0xF6)
    ]

    async def _use_highest_level(self):
        await self.write_register(0x01, 0x20, check_feature=False)

    async def _use_lowest_level(self):
        await self.write_register(0x01, 0x00, check_feature=False)

    async def _check_enable_features(self, address, data):
        if address == 0x01 and data & 0x20:
            self._enable_level(2)
        elif address in range(0xE0, 0xF6):
            if self._check_level(address, 2):
                await self.write_register(0x01, 0x20)
        else:
            await super()._check_enable_features(address, data)


class YamahaVGMStreamPlayer(VGMStreamPlayer):
    def __init__(self, reader, opx_iface, clock_rate):
        self._reader     = reader
        self._opx_iface  = opx_iface

        self.clock_rate  = clock_rate
        self.sample_time = opx_iface.sample_clocks / self.clock_rate

    async def play(self):
        try:
            await self._opx_iface.enable()
            await self._reader.parse_data(self)
        finally:
            await self._opx_iface.disable()

    async def record(self, queue, chunk_count=8192):
        total_count = int(self._reader.total_seconds / self.sample_time)
        done_count  = 0
        while done_count < total_count:
            chunk_count = min(chunk_count, total_count - done_count)
            samples = await self._opx_iface.read_samples(chunk_count)
            await queue.put(samples)
            done_count += chunk_count

        await queue.put(b"")

    async def ym3526_write(self, address, data):
        await self._opx_iface.write_register(address, data)

    async def ym3812_write(self, address, data):
        await self._opx_iface.write_register(address, data)

    async def wait_seconds(self, delay):
        await self._opx_iface.wait_clocks(int(delay * self.clock_rate))


class YamahaOPxWebInterface:
    def __init__(self, logger, opx_iface):
        self._logger    = logger
        self._opx_iface = opx_iface
        self._lock      = asyncio.Lock()

    async def serve_index(self, request):
        with open(os.path.join(os.path.dirname(__file__), "index.html")) as f:
            index_html = f.read()
            index_html = index_html.replace("{{chips}}", ", ".join(self._opx_iface.chips))
            return web.Response(text=index_html, content_type="text/html")

    def _make_resampler(self, actual, preferred):
        import numpy

        try:
            import samplerate
        except ImportError as e:
            self._logger.warning("samplerate not installed; expect glitches during playback")
            async def resample(input_queue, output_queue):
                while True:
                    input_data = await input_queue.get()
                    input_array = numpy.frombuffer(input_data, dtype="<u2")
                    output_array = (output_array - 32768).astype(numpy.int16)
                    if input_data:
                        await output_queue.put(output_array.tobytes())
                    if not input_data:
                        await output_queue.put(b"")
                        break
            return resample, actual

        resampler = samplerate.Resampler()
        def resample_worker(input_data, end):
            input_array = numpy.frombuffer(input_data, dtype="<u2")
            input_array = (input_array.astype(numpy.float32) - 32768) / 32768
            output_array = resampler.process(
                input_array, ratio=preferred / actual, end_of_input=end)
            output_array = (output_array * 32768).astype(numpy.int16)
            return output_array.tobytes()
        async def resample(input_queue, output_queue):
            while True:
                input_data  = await input_queue.get()
                output_data = await asyncio.get_running_loop().run_in_executor(None,
                    resample_worker, input_data, not input_data)
                if output_data:
                    await output_queue.put(output_data)
                if not input_data:
                    await output_queue.put(b"")
                    break
        return resample, preferred

    async def serve_vgm(self, request):
        vgm_data = await request.read()
        digest = hashlib.sha256(vgm_data).hexdigest()[:16]
        self._logger.info("web: %s: submitted by %s",
                          digest, request.remote)

        try:
            if len(vgm_data) < 0x80:
                raise ValueError("File is too short to be valid")

            try:
                vgm_stream = io.BytesIO(vgm_data)
                if not vgm_data.startswith(b"Vgm "):
                    vgm_stream = gzip.GzipFile(fileobj=vgm_stream)

                vgm_reader = VGMStreamReader(vgm_stream)
            except OSError:
                raise ValueError("File is not in VGM or VGZ format")

            self._logger.info("web: %s: VGM has commands for %s",
                              digest, ", ".join(vgm_reader.chips()))
            if len(vgm_reader.chips()) != 1:
                raise ValueError("VGM file does not contain commands for exactly one chip")

            clock_rate = self._opx_iface.get_vgm_clock_rate(vgm_reader)
            if clock_rate == 0:
                raise ValueError("VGM file does not contain commands for any supported chip")
            if clock_rate & 0xc0000000:
                raise ValueError("VGM file uses unsupported chip configuration")

            self._logger.info("web: %s: VGM is looped for %.2f/%.2f s",
                              digest, vgm_reader.loop_seconds, vgm_reader.total_seconds)

            vgm_player = YamahaVGMStreamPlayer(vgm_reader, self._opx_iface, clock_rate)
        except ValueError as e:
            self._logger.warning("web: %s: broken upload: %s",
                                 digest, str(e))
            return web.Response(status=400, text=str(e), content_type="text/plain")

        input_rate = 1 / vgm_player.sample_time
        preferred_rate = int(request.headers["X-Preferred-Sample-Rate"])
        resample, output_rate = self._make_resampler(input_rate, preferred_rate)
        self._logger.info("web: %s: sample rate: input %d, preferred %d, output %d",
                          digest, input_rate, preferred_rate, output_rate)

        async with self._lock:
            self._logger.info("web: %s: start streaming",
                              digest)

            await self._opx_iface.reset()

            input_queue    = asyncio.Queue()
            resample_queue = asyncio.Queue()
            resample_fut = asyncio.ensure_future(resample(input_queue, resample_queue))
            record_fut   = asyncio.ensure_future(vgm_player.record(input_queue))
            play_fut     = asyncio.ensure_future(vgm_player.play())

            try:
                response = web.StreamResponse()
                response.content_type = "text/plain"
                response.headers["X-Chip"] = vgm_reader.chips()[0]
                response.headers["X-Sample-Rate"] = str(output_rate)
                total_samples = int(vgm_reader.total_seconds * output_rate)
                response.headers["X-Total-Samples"] = str(total_samples)
                if vgm_reader.loop_samples in (0, vgm_reader.total_samples):
                    # Either 0 or the entire VGM here means we'll loop the complete track.
                    loop_skip_to = 0
                else:
                    loop_skip_to = int((vgm_reader.total_seconds - vgm_reader.loop_seconds)
                                       * output_rate)
                response.headers["X-Loop-Skip-To"] = str(loop_skip_to)
                response.enable_chunked_encoding()
                await response.prepare(request)

                TRANSPORT_SIZE = 3072
                output_buffer = bytearray()
                while True:
                    if not resample_fut.done() or not resample_queue.empty():
                        while len(output_buffer) < TRANSPORT_SIZE:
                            output_chunk   = await resample_queue.get()
                            output_buffer += output_chunk
                            if not output_chunk:
                                break

                    transport_chunk = output_buffer[:TRANSPORT_SIZE]
                    while len(transport_chunk) < TRANSPORT_SIZE:
                        # Pad last transport chunk with silence
                        transport_chunk += struct.pack("<H", 32768)
                    output_buffer   = output_buffer[TRANSPORT_SIZE:]
                    await response.write(base64.b64encode(transport_chunk))
                    if resample_fut.done() and not output_buffer:
                        break

                for fut in [play_fut, record_fut, resample_fut]:
                    await fut

                await response.write_eof()
                self._logger.info("web: %s: done streaming",
                                  digest)

            except asyncio.CancelledError:
                self._logger.info("web: %s: cancel streaming",
                                  digest)

                for fut in [play_fut, record_fut, resample_fut]:
                    if not fut.done():
                        fut.cancel()
                raise

            return response

    async def serve(self):
        app = web.Application()
        app.add_routes([
            web.get ("/", self.serve_index),
            web.post("/vgm", self.serve_vgm),
        ])

        try:
            from aiohttp_remotes import XForwardedRelaxed, setup as setup_remotes
            await setup_remotes(app, XForwardedRelaxed())
        except ImportError:
            self._logger.warning("aiohttp_remotes not installed; X-Forwarded-For will not be used")

        runner = web.AppRunner(app,
            access_log_format='%a(%{X-Forwarded-For}i) "%r" %s "%{Referer}i" "%{User-Agent}i"')
        await runner.setup()
        site = web.TCPSite(runner, "localhost", 8080)
        await site.start()
        await asyncio.Future()


class AudioYamahaOPLApplet(GlasgowApplet, name="audio-yamaha-opl"):
    logger = logging.getLogger(__name__)
    help = "drive and record Yamaha OPL* FM synthesizers"
    description = """
    Send commands and record digital output from Yamaha OPL* series FM synthesizers. The supported
    chips are:
        * YM3526 (OPL)
        * YM3812 (OPL2)

    The ~CS input should always be grounded, since there is only one chip on the bus in the first
    place.

    The digital output is losslessly converted to 16-bit unsigned PCM samples. (The Yamaha DACs
    only have 16 bit of dynamic range, and there is a direct mapping between the on-wire floating
    point sample format and ordinary 16-bit PCM.)

    The written samples can be played with the knowledge of the sample rate, which is derived from
    the master clock frequency specified in the input file. E.g. using SoX:

        $ play -r 49715 output.u16

    For the web interface, the browser dictates the sample rate. Streaming at the sample rate other
    than the one requested by the browser is possible, but degrades quality. This interface also
    has additional Python dependencies:
        * numpy (mandatory)
        * samplerate (optional, required for best possible quality)
    """

    __pin_sets = ("d", "a")
    __pins = ("clk_m", "rd", "wr",
              "clk_sy", "sh", "mo")

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_set_argument(parser, "d", width=8, default=True)
        access.add_pin_argument(parser, "clk_m", default=True)
        access.add_pin_set_argument(parser, "a", width=2, default=True)
        access.add_pin_argument(parser, "rd", default=True)
        access.add_pin_argument(parser, "wr", default=True)
        access.add_pin_argument(parser, "clk_sy", default=True)
        access.add_pin_argument(parser, "sh", default=True)
        access.add_pin_argument(parser, "mo", default=True)

        parser.add_argument(
            "-d", "--device", metavar="DEVICE", choices=["OPL", "OPL2"], required=True,
            help="Synthesizer family")

    @staticmethod
    def _device_iface_cls(args):
        if args.device == "OPL":
            return YamahaOPLInterface
        if args.device == "OPL2":
            return YamahaOPL2Interface

    def build(self, target, args):
        device_iface_cls = self._device_iface_cls(args)

        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        subtarget = iface.add_subtarget(YamahaOPxSubtarget(
            pads=iface.get_pads(args, pins=self.__pins, pin_sets=self.__pin_sets),
            # These FIFO depths are somewhat dependent on the (current, bad) arbiter in Glasgow,
            # but they work for now. With a better arbiter they should barely matter.
            out_fifo=iface.get_out_fifo(depth=512),
            in_fifo=iface.get_in_fifo(depth=8192, auto_flush=False),
            # It's useful to run the synthesizer at a frequency significantly higher than real-time
            # to reduce the time spent waiting.
            master_cyc=self.derive_clock(input_hz=target.sys_clk_freq, output_hz=15e6),
            read_pulse_cyc=int(target.sys_clk_freq * 200e-9),
            write_pulse_cyc=int(target.sys_clk_freq * 100e-9),
            address_clocks=device_iface_cls.address_clocks,
            data_clocks=device_iface_cls.data_clocks,
        ))
        return subtarget

    async def run(self, device, args):
        device_iface_cls = self._device_iface_cls(args)

        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        opx_iface = device_iface_cls(iface, self.logger)
        await opx_iface.reset()
        return opx_iface

    @classmethod
    def add_interact_arguments(cls, parser):
        # TODO(py3.7): add required=True
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION")

        p_convert = p_operation.add_parser(
            "convert", help="convert VGM to PCM using Yamaha hardware")
        p_convert.add_argument(
            "vgm_file", metavar="VGM-FILE", type=argparse.FileType("rb"),
            help="read commands from VGM-FILE (one of: .vgm .vgm.gz .vgz)")
        p_convert.add_argument(
            "pcm_file", metavar="PCM-FILE", type=argparse.FileType("wb"),
            help="write samples to PCM-FILE")

        p_web = p_operation.add_parser(
            "web", help="expose Yamaha hardware via a web interface")

    async def interact(self, device, args, opx_iface):
        if args.operation == "convert":
            vgm_reader = VGMStreamReader.from_file(args.vgm_file)
            self.logger.info("VGM file contains commands for %s", ", ".join(vgm_reader.chips()))
            if len(vgm_reader.chips()) != 1:
                raise GlasgowAppletError("VGM file does not contain commands for exactly one chip")

            clock_rate = opx_iface.get_vgm_clock_rate(vgm_reader)
            if clock_rate == 0:
                raise GlasgowAppletError("VGM file does not contain commands for any "
                                         "supported chip")
            if clock_rate & 0xc0000000:
                raise GlasgowAppletError("VGM file uses unsupported chip configuration")

            vgm_player = YamahaVGMStreamPlayer(vgm_reader, opx_iface, clock_rate)
            self.logger.info("recording at sample rate %d Hz", 1 / vgm_player.sample_time)

            async def write_pcm(input_queue):
                while True:
                    input_chunk = await input_queue.get()
                    if not input_chunk:
                        break
                    args.pcm_file.write(input_chunk)

            input_queue = asyncio.Queue()
            play_fut   = asyncio.ensure_future(vgm_player.play())
            record_fut = asyncio.ensure_future(vgm_player.record(input_queue))
            write_fut  = asyncio.ensure_future(write_pcm(input_queue))
            done, pending = await asyncio.wait([play_fut, record_fut, write_fut],
                                               return_when=asyncio.FIRST_EXCEPTION)
            print(done, pending)
            for fut in done:
                await fut

        if args.operation == "web":
            web_iface = YamahaOPxWebInterface(self.logger, opx_iface)
            await web_iface.serve()

# -------------------------------------------------------------------------------------------------

class AudioYamahaOPLAppletTestCase(GlasgowAppletTestCase, applet=AudioYamahaOPLApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
