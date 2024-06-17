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
# The Yamaha DAC bitstream format is somewhat underdocumented and confusing. The DAC bitstream
# has 16 bit dynamic range and uses 13 bit samples in a bespoke floating point format. These 13 bit
# samples are padded to 16 bits and transmitted over a serial protocol similar to I²S.
#
# The sample format is as follows, transmitted on wire LSB first:
#  (LSB)                                                                       (MSB)
#  +----+----+----+----+----+----+----+----+----+----+----+----+----+----+----+----+
#  | 0  | 0  | 0  | M0 | M1 | M2 | M3 | M4 | M5 | M6 | M7 | M8 | S  | E0 | E1 | E2 |
#  +----+----+----+----+----+----+----+----+----+----+----+----+----+----+----+----+
#
# Each sample defines a 9-bit M(antissa), 1-bit S(ign) and 3-bit E(xponent). The legal values
# for the exponent are 1..7. The sample format does not appear to follow any intrinsic structure
# and seems to have been chosen for the simplicity of DAC implementation alone. Therefore, no
# attempt is made here to describe the sample format in abstract terms.
#
# The DAC transfer function, which converts DAC bitstream to unsigned 16-bit voltage levels,
# is as follows, in a Verilog-like syntax:
#     assign V = {S, {{7{~S}}, M, 7'b0000000}[E+:15]};
#
# Bus cycles
# ----------
#
# The CPU bus interface is asynchronous to master or DAC clock, but is heavily registered (see
# the next section). Writes are referenced to the ~WR rising edge, and require chip-specific
# wait states. Reads are referenced to ~RD falling edge, and always read exactly one register,
# although there might be undocumented registers elsewhere.
#
# On some chips (e.g OPL4) the register that can be read has a busy bit, which seems to be always
# the LSB. On many others (e.g. OPL3) there is no busy bit. Whether the busy bit is available
# on any given silicon seems pretty arbitrary.
#
# Register compatibility
# ----------------------
#
# Yamaha chips that have compatibility features implement them in a somewhat broken way. When
# the compatibility feature is disabled (e.g. bit 5 of 0x01 TEST for YM3812), its registers are
# masked off. However, the actual feature is still (partially) enabled and it will result in
# broken playback if this is not accounted for. Therefore, for example, the reset sequence has to
# enable all available advanced features, reset the registers controlling advanced features, and
# then disable them back for compatibility with OPL clients that expect the compatibility mode
# to be on.
#
# Note that not all registers should always be reset to zero. For example, on OPL3, CHA/CHB should
# be reset to 1 with A1=L, or OPL2 compatibility breaks, manifesting as missing percussion. This
# is not documented, and cannot be verified on hardware because these registers cannot be read.
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
# Timing compatibility
# --------------------
#
# When OPL3, functions in the OPL3 mode (NEW=1), the address and data latency are the declared
# values, i.e. 32 and 32 master clock cycles. However, in OPL/OPL2 mode, OPL3 uses completely
# different timings. It is not clear what they are, but 32*4/32*4 is not enough (and lead to missed
# writes), whereas 36*4/36*4 seems to work fine. This is never mentioned in any documentation.
#
# Although it is not mentioned anywhere, it is generally understood that OPL3 in compatibility
# mode (NEW=0) is attempting to emulate two independent OPL2's present on the first release
# of Sound Blaster PRO, which could be the cause of the bizarre timings. See the following link:
# https://www.msx.org/forum/msx-talk/software/vgmplay-msx?page=29
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
#   * YM3812 stops working between 10 MHz (good) and 30 MHz (bad).
#   * YMF262 stops working between 24 MHz (good) and 48 MHz (bad).
#
# Test cases
# ----------
#
# Good test cases that stress the various timings and interfaces are:
#   * (YM3526) https://vgmrips.net/packs/pack/chelnov-atomic-runner-karnov track 03
#     Good general-purpose OPL test.
#   * (YM3812) https://vgmrips.net/packs/pack/ultima-vi-the-false-prohpet-ibm-pc-xt-at track 01
#     This track makes missing notes (due to timing mismatches) extremely noticeable.
#   * (YM3812) https://vgmrips.net/packs/pack/lemmings-dos
#     This pack does very few commands at a time and doesn't have software vibrato, so if commands
#     go missing, notes go out of tune.
#   * (YM3812) https://vgmrips.net/packs/pack/zero-wing-toaplan-1 track 02
#     Good general-purpose OPL2 test, exhibits serious glitches if the OPL2 isn't reset correctly
#     or if the LSI TEST register handling is broken.
#   * (YM3812) https://vgmrips.net/packs/pack/vimana-toaplan-1 track 02
#     This is an OPL2 track but the music is written for OPL and in fact the VGM file disables
#     WAVE SELECT as one of the first commands. Implementation bugs tend to silence drums,
#     which is easily noticeable but only if you listen to the reference first.
#   * (YMF262) https://vgmrips.net/packs/pack/touhou-eiyashou-imperishable-night-ibm-pc-at track 18
#     Good general-purpose OPL3 test.

from abc import ABCMeta, abstractmethod, abstractproperty
import os.path
import logging
import argparse
import struct
import asyncio
import aiohttp, aiohttp.web
import hashlib
import gzip
import io
from amaranth import *
from amaranth.lib import data
from amaranth.lib.cdc import FFSynchronizer
from urllib.parse import urlparse

from ....gateware.pads import *
from ....gateware.clockgen import *
from ....protocol.vgm import *
from ... import *


class YamahaCPUBus(Elaboratable):
    def __init__(self, pads, master_cyc):
        self.pads = pads
        self.master_cyc = master_cyc

        self.rst   = Signal()
        self.stb_m = Signal()

        self.a  = Signal(2)

        self.oe = Signal(init=1)
        self.di = Signal(8)
        self.do = Signal(8)

        self.cs = Signal()
        self.rd = Signal()
        self.wr = Signal()

        self.clkgen_ce = Signal()

    def elaborate(self, platform):
        m = Module()

        m.submodules.clkgen = clkgen = EnableInserter(self.clkgen_ce)(ClockGen(self.master_cyc))
        m.d.comb += self.stb_m.eq(clkgen.stb_r)

        m.d.comb += [
            self.pads.clk_m_t.oe.eq(1),
            self.pads.clk_m_t.o.eq(clkgen.clk),
            self.pads.a_t.oe.eq(1),
            self.pads.a_t.o.eq(self.a),
            self.pads.d_t.oe.eq(self.oe),
            self.pads.d_t.o.eq(self.do),
            self.di.eq(self.pads.d_t.i),
            # handle (self.rd & (self.wr | self.oe)) == 1 safely
            self.pads.rd_t.oe.eq(1),
            self.pads.rd_t.o.eq(~(self.rd & ~self.wr & ~self.oe)),
            self.pads.wr_t.oe.eq(1),
            self.pads.wr_t.o.eq(~(self.wr & ~self.rd)),
        ]
        if hasattr(self.pads, "cs_t"):
            m.d.comb += [
                self.pads.cs_t.oe.eq(1),
                self.pads.cs_t.o.eq(~self.cs),
            ]
        if hasattr(self.pads, "ic_t"):
            m.d.comb += [
                self.pads.ic_t.oe.eq(1),
                self.pads.ic_t.o.eq(~self.rst),
            ]

        return m


class YamahaDACBus(Elaboratable):
    def __init__(self, pads):
        self.pads = pads

        self.stb_sy = Signal()
        self.stb_sh = Signal()

        self.sh = Signal()
        self.mo = Signal()

    def elaborate(self, platform):
        m = Module()

        clk_sy_s = Signal()
        clk_sy_r = Signal()
        m.d.sync += [
            clk_sy_r.eq(clk_sy_s),
            self.stb_sy.eq(clk_sy_r & ~clk_sy_s)
        ]

        sh_r = Signal()
        m.d.sync += [
            sh_r.eq(self.sh),
            self.stb_sh.eq(sh_r & ~self.sh)
        ]

        m.submodules += [
            FFSynchronizer(self.pads.clk_sy_t.i, clk_sy_s),
            FFSynchronizer(self.pads.sh_t.i, self.sh),
            FFSynchronizer(self.pads.mo_t.i, self.mo)
        ]

        return m


OP_ENABLE = 0x00
OP_WRITE  = 0x10
OP_READ   = 0x20
OP_WAIT   = 0x30
OP_MASK   = 0xf0


class YamahaOPxSubtarget(Elaboratable):
    def __init__(self, pads, in_fifo, out_fifo, sample_decoder_cls, channel_count,
                 master_cyc, read_pulse_cyc, write_pulse_cyc,
                 address_clocks, data_clocks):
        self.in_fifo = in_fifo
        self.out_fifo = out_fifo
        self.channel_count = channel_count
        self.read_pulse_cyc = read_pulse_cyc
        self.write_pulse_cyc = write_pulse_cyc
        self.address_clocks = address_clocks
        self.data_clocks = data_clocks

        self.decoder = sample_decoder_cls()
        self.cpu_bus = YamahaCPUBus(pads, master_cyc)
        self.dac_bus = YamahaDACBus(pads)

    def elaborate(self, platform):
        m = Module()

        m.submodules.cpu_bus = self.cpu_bus
        m.submodules.dac_bus = self.dac_bus

        # Control

        pulse_timer = Signal(range(max(self.read_pulse_cyc, self.write_pulse_cyc)))
        wait_timer  = Signal(16)

        enabled     = Signal()
        m.d.comb += self.cpu_bus.rst.eq(~enabled)

        # The code below assumes that the FSM clock is under ~50 MHz, which frees us from the need
        # to explicitly satisfy setup/hold timings.
        m.d.comb += self.cpu_bus.clkgen_ce.eq(self.out_fifo.r_rdy)
        with m.FSM() as fsm:
            with m.State("IDLE"):
                m.d.sync += self.cpu_bus.oe.eq(1)
                with m.If(self.out_fifo.r_rdy):
                    m.d.comb += self.out_fifo.r_en.eq(1)
                    with m.Switch(self.out_fifo.r_data & OP_MASK):
                        with m.Case(OP_ENABLE):
                            m.d.sync += enabled.eq(self.out_fifo.r_data & ~OP_MASK)
                        with m.Case(OP_WRITE):
                            m.d.sync += self.cpu_bus.a.eq(self.out_fifo.r_data & ~OP_MASK)
                            m.next = "WRITE-DATA"
                        # OP_READ: m.next = "READ",
                        with m.Case(OP_WAIT):
                            m.next = "WAIT-H-BYTE"
            with m.State("WRITE-DATA"):
                with m.If(self.out_fifo.r_rdy):
                    m.d.comb += self.out_fifo.r_en.eq(1)
                    m.d.sync += [
                        self.cpu_bus.do.eq(self.out_fifo.r_data),
                        self.cpu_bus.cs.eq(1),
                        self.cpu_bus.wr.eq(1),
                        pulse_timer.eq(self.write_pulse_cyc - 1),
                    ]
                    m.next = "WRITE-PULSE"
            with m.State("WRITE-PULSE"):
                with m.If(pulse_timer == 0):
                    m.d.sync += [
                        self.cpu_bus.cs.eq(0),
                        self.cpu_bus.wr.eq(0),
                    ]
                    with m.If(self.cpu_bus.a[0] == 0b0):
                        m.d.sync += wait_timer.eq(self.address_clocks - 1)
                    with m.Else():
                        m.d.sync += wait_timer.eq(self.data_clocks - 1)
                    m.next = "WAIT-LOOP"
                with m.Else():
                    m.d.sync += pulse_timer.eq(pulse_timer - 1)
            with m.State("WAIT-H-BYTE"):
                with m.If(self.out_fifo.r_rdy):
                    m.d.comb += self.out_fifo.r_en.eq(1)
                    m.d.sync += wait_timer[8:16].eq(self.out_fifo.r_data)
                    m.next = "WAIT-L-BYTE"
            with m.State("WAIT-L-BYTE"):
                with m.If(self.out_fifo.r_rdy):
                    m.d.comb += self.out_fifo.r_en.eq(1)
                    m.d.sync += wait_timer[0:8].eq(self.out_fifo.r_data)
                    m.next = "WAIT-LOOP"
            with m.State("WAIT-LOOP"):
                with m.If(wait_timer == 0):
                    m.next = "IDLE"
                with m.Else():
                    with m.If(self.cpu_bus.stb_m):
                        m.d.sync += wait_timer.eq(wait_timer - 1)

        # Audio

        m.submodules.decoder = self.decoder

        channel_width = len(self.decoder.i.as_value())
        shreg  = Signal(channel_width * self.channel_count)
        sample = Signal.like(shreg)
        with m.If(self.dac_bus.stb_sy):
            m.d.sync += shreg.eq(Cat(shreg[1:], self.dac_bus.mo))

        channel = Signal(1)
        with m.FSM() as fsm:
            with m.State("WAIT-SH"):
                m.d.sync += self.in_fifo.flush.eq(~enabled)
                with m.If(self.dac_bus.stb_sh & enabled):
                    m.next = "SAMPLE"
            with m.State("SAMPLE"):
                m.d.sync += [
                    sample.eq(shreg),
                    channel.eq(0),
                ]
                m.next = "SEND-CHANNEL"
            with m.State("SEND-CHANNEL"):
                m.d.sync += [
                    self.decoder.i.eq(
                          sample.word_select(channel, channel_width)),
                ]
                m.next = "SEND-BYTE"
            byteno = Signal(1)
            with m.State("SEND-BYTE"):
                m.d.comb += self.in_fifo.w_data.eq(self.decoder.o.word_select(byteno, 8))
                with m.If(self.in_fifo.w_rdy):
                    m.d.comb += self.in_fifo.w_en.eq(1)
                    m.d.sync += byteno.eq(byteno + 1)
                    with m.If(byteno == 1):
                        m.d.sync += channel.eq(channel + 1)
                        with m.If(channel == self.channel_count - 1):
                            m.next = "WAIT-SH"
                        with m.Else():
                            m.next = "SEND-CHANNEL"
                with m.Elif(self.dac_bus.stb_sh):
                    m.next = "OVERFLOW"
            with m.State("OVERFLOW"):
                m.next = "OVERFLOW"

        return m


class YamahaOPxInterface(metaclass=ABCMeta):
    chips = []

    def __init__(self, interface, logger, *, instant_writes=True, filter=None):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        # Adjust delays such that earlier writes borrow from later delays. Useful for VGM files,
        # where writes are unphysically assumed to take no time.
        self._instant_writes = instant_writes
        self._phase_accum    = 0

        self.filter = filter

        self._feature_level  = 1
        self._feature_warned = False

    @abstractmethod
    def get_vgm_clock_rate(self, vgm_reader):
        pass

    max_master_hz  = abstractproperty()
    sample_decoder = abstractproperty()
    channel_count  = 1

    address_clocks = abstractproperty()
    data_clocks    = abstractproperty()
    sample_clocks  = abstractproperty()

    @property
    def write_clocks(self):
        return self.address_clocks + self.data_clocks

    def _log(self, message, *args, level=None):
        self._logger.log(self._level if level is None else level, "OPx: " + message, *args)

    _registers = []

    async def reset(self):
        self._log("reset")
        await self.lower.reset()
        # Don't run reset commands through the filter.
        old_filter, self.filter = self.filter, None
        # Reset the synthesizer in software; some of them appear to have broken reset via ~IC pin,
        # and in any case this frees up one Glasgow pin, which we are short on. VGM files often
        # do not reset the chip appropriately, nor do they always terminate cleanly, so this is
        # necessary to get a reproducible result.
        old_instant_writes, self._instant_writes = self._instant_writes, False
        await self._use_highest_level()
        await self._reset_registers()
        await self._use_lowest_level()
        self._feature_level  = 1
        self._feature_warned = False
        self._instant_writes = old_instant_writes
        self.filter = old_filter
        if self.filter is not None:
            self.filter.reset()

    async def _use_highest_level(self):
        pass

    async def _use_lowest_level(self):
        pass

    async def _reset_registers(self):
        for addr in self._registers:
            await self.write_register(addr, 0x00, check_feature=False)

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
            self._log("client uses undefined feature [%#04x]=%#04x",
                      address, data,
                      level=logging.WARN)

    async def write_register(self, address, data, check_feature=True):
        if self.filter is not None:
            filtered = await self.filter.write_register(address, data)
            if filtered is None:
                self._log("filter write [%#04x]=%#04x⇒remove", address, data)
                return
            elif (address, data) != filtered:
                self._log("filter write [%#04x]=%#04x⇒[%#04x]=%#04x", address, data, *filtered)
                address, data = filtered

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
        if self.filter is not None:
            filtered = await self.filter.wait_clocks(count)
            if filtered is None:
                self._log("filter wait %d⇒remove clocks")
                return
            elif count != filtered:
                self._log("filter wait %d⇒%d clocks")
                count = filtered

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

    async def read_samples(self, count):
        self._log("read %d samples", count)
        return await self.lower.read(count * self.channel_count * 2, flush=False)


class YamahaOPxCommandFilter:
    def __init__(self):
        self.offset_clocks = 0
        self.sample_rate   = 0

    @property
    def offset_seconds(self):
        return self.offset_clocks / self.sample_rate

    def reset(self):
        self.offset_clocks = 0

    async def write_register(self, address, data):
        return address, data

    async def wait_clocks(self, count):
        self.offset_clocks += count
        return count


class YM301xSample(data.Struct):
    z: unsigned(3)
    m: unsigned(9)
    s: unsigned(1)
    e: unsigned(3)


class YM301xSampleDecoder(Elaboratable):
    def __init__(self):
        self.i = Signal(YM301xSample)
        self.o = Signal(16)

    def elaborate(self, platform):
        m = Module()

        m.d.comb += [
            self.o.eq(Cat((Cat(self.i.m, (~self.i.s).replicate(7)) << self.i.e)[1:16], ~self.i.s))
        ]

        return m


class YamahaOPLInterface(YamahaOPxInterface):
    chips = ["YM3526/OPL"]

    def get_vgm_clock_rate(self, vgm_reader):
        return vgm_reader.ym3526_clk, 1

    max_master_hz  = 4.0e6 # 2.0/3.58/4.0
    sample_decoder = YM301xSampleDecoder
    channel_count  = 1

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
    chips = YamahaOPLInterface.chips + ["YM3812/OPL2"]

    def get_vgm_clock_rate(self, vgm_reader):
        if vgm_reader.ym3812_clk:
            return vgm_reader.ym3812_clk, 1
        else:
            return YamahaOPLInterface.get_vgm_clock_rate(self, vgm_reader)

    _registers = YamahaOPLInterface._registers + [
        *range(0xE0, 0xF6)
    ]

    async def _use_highest_level(self):
        await self.write_register(0x01, 0x20, check_feature=False)

    async def _use_lowest_level(self):
        await self.write_register(0x01, 0x00, check_feature=False)

    async def _check_enable_features(self, address, data):
        if address == 0x01 and data in (0x00, 0x20):
            if data & 0x20:
                self._enable_level(2)
        elif address in range(0xE0, 0xF6):
            if self._check_level(address, 2):
                await self.write_register(0x01, 0x20)
        else:
            await super()._check_enable_features(address, data)


class YAC512Sample(data.Struct):
    # There are 2 dummy clocks between each sample. The DAC doesn't rely on it (it uses two
    # phases for two channels per DAC, and a clever arrangement to provide four channels
    # without requiring four phases), but we want to save pins and so we do.
    z: unsigned(2)
    d: unsigned(16)


class YAC512SampleDecoder(Elaboratable):
    def __init__(self):
        self.i = Signal(YAC512Sample)
        self.o = Signal(16)

    def elaborate(self, platform):
        m = Module()

        m.d.comb += self.o.eq(self.i.d + 0x8000)

        return m


class YamahaOPL3Interface(YamahaOPL2Interface):
    chips = [chip + " (no CSM)" for chip in YamahaOPL2Interface.chips] + ["YMF262/OPL3"]

    def get_vgm_clock_rate(self, vgm_reader):
        if vgm_reader.ymf262_clk:
            return vgm_reader.ymf262_clk, 1
        else:
            ym3812_clk, _ = YamahaOPL2Interface.get_vgm_clock_rate(self, vgm_reader)
            return ym3812_clk, 4

    max_master_hz  = 16.0e6 # 10.0/14.32/16.0
    sample_decoder = YAC512SampleDecoder
    channel_count  = 2 # OPL3 has 4 channels, but we support only 2

    # The datasheet says use 32 master clock cycle latency. That's a lie, there's a /4 pre-divisor.
    # So you'd think 32 * 4 master clock cycles would work. But 32 is also a lie, that doesn't
    # result in robust playback. It appears that 36 is the real latency number.
    address_clocks = 36 * 4
    data_clocks    = 36 * 4
    sample_clocks  = 72 * 4

    _registers = YamahaOPL2Interface._registers + [
        0x104, *range(0x120, 0x136), *range(0x140, 0x156), *range(0x160, 0x176),
        *range(0x180, 0x196), *range(0x1A0, 0x1A9), *range(0x1B0, 0x1B9), *range(0x1C0, 0x1C9),
        *range(0x1E0, 0x1F6)
    ]

    async def _use_highest_level(self):
        await super()._use_highest_level()
        await self.write_register(0x105, 0x01, check_feature=False)

    async def _use_lowest_level(self):
        await self.write_register(0x105, 0x00, check_feature=False)
        for address in range(0xC0, 0xC9):
            await self.write_register(address, 0x30, check_feature=False)
        await super()._use_lowest_level()

    async def _check_enable_features(self, address, data):
        if address == 0x08 and data & 0x80:
            self._log("client uses deprecated and removed feature [0x08]|0x80",
                      level=logging.WARN)
        elif address == 0x105 and data in (0x00, 0x01):
            if data & 0x01:
                self._enable_level(3)
        elif address in range(0x100, 0x200) and address in self._registers:
            if self._check_level(address, 3):
                await self.write_register(0x105, 0x01)
        else:
            await super()._check_enable_features(address, data)

    async def _reset_registers(self):
        await super()._reset_registers()
        for address in range(0x0C0, 0x0C8):
            await self.write_register(address, 0x30, check_feature=False) # RL enable
        for address in range(0x1C0, 0x1C8):
            await self.write_register(address, 0x30, check_feature=False) # RL enable


class YamahaOPMInterface(YamahaOPxInterface):
    chips = ["YM2151/OPM"]

    def get_vgm_clock_rate(self, vgm_reader):
        return vgm_reader.ym2151_clk, 1

    max_master_hz  = 4.0e6 # 2.0/3.58/4.0
    sample_decoder = YM301xSampleDecoder
    channel_count  = 2

    address_clocks = 12
    data_clocks    = 68
    sample_clocks  = 64

    _registers = [
        0x08, 0x0F, 0x10, 0x11, 0x12, 0x14, 0x18, 0x19, 0x1B,
        *range(0x20, 0x28), *range(0x28, 0x30), *range(0x30, 0x38), *range(0x38, 0x40),
        *range(0x40, 0x60), *range(0x60, 0x80), *range(0x80, 0xA0), *range(0xA0, 0xC0),
        *range(0xC0, 0xE0), *range(0xE0, 0x100)
    ]

    async def _check_enable_features(self, address, data):
        if address == 0x01 and data in (0x00, 0x02):
            pass # LFO reset
        else:
            await super()._check_enable_features(address, data)

    async def _reset_registers(self):
        await super()._reset_registers()
        await self.write_register(0x01, 0x02) # LFO reset
        await self.write_register(0x01, 0x00)
        await self.write_register(0x14, 0x30) # flag reset
        await self.write_register(0x14, 0x00)
        for address in range(0x60, 0x80):
            await self.write_register(address, 0x7F) # lowest TL
        for address in range(0x20, 0x28):
            await self.write_register(address, 0xC0) # RL enable


class YamahaVGMStreamPlayer(VGMStreamPlayer):
    def __init__(self, reader, opx_iface, clock_rate):
        self._reader     = reader
        self._opx_iface  = opx_iface

        self.clock_rate  = clock_rate
        self.sample_time = opx_iface.sample_clocks / self.clock_rate

    async def play(self):
        try:
            await self._opx_iface.enable()
            # Flush out the state after reset.
            await self._opx_iface.wait_clocks(self._opx_iface.sample_clocks * 1024)
            await self._reader.parse_data(self)
        finally:
            # Various parts of our stack are not completely synchronized to each other, resulting
            # in small mismatches in calculated and produced sample counts. Pad the trailing end
            # of the VGM file with some additional silence to make sure recording ends.
            await self._opx_iface.wait_clocks(self.clock_rate)
            await self._opx_iface.disable()

    async def record(self, queue, chunk_count=16384):
        # Skip a few initial samples that are used to flush state.
        await self._opx_iface.read_samples(1024)

        total_count = int(self._reader.total_seconds / self.sample_time)
        done_count  = 0
        while done_count < total_count:
            chunk_count = min(chunk_count, total_count - done_count)
            samples = await self._opx_iface.read_samples(chunk_count)
            await queue.put(samples)
            done_count += chunk_count

        await queue.put(b"")

    async def ym2151_write(self, address, data):
        await self._opx_iface.write_register(address, data)

    async def ym3526_write(self, address, data):
        await self._opx_iface.write_register(address, data)

    async def ym3812_write(self, address, data):
        await self._opx_iface.write_register(address, data)

    async def ymf262_write(self, address, data):
        await self._opx_iface.write_register(address, data)

    async def wait_seconds(self, delay):
        await self._opx_iface.wait_clocks(int(delay * self.clock_rate))


class YamahaOPxWebInterface:
    def __init__(self, logger, opx_iface, set_voltage, allow_urls):
        self._logger    = logger
        self._opx_iface = opx_iface
        self._lock      = asyncio.Lock()

        self._set_voltage = set_voltage
        self._allow_urls = allow_urls

    async def serve_index(self, request):
        with open(os.path.join(os.path.dirname(__file__), "index.html")) as f:
            index_html = f.read()
            index_html = index_html.replace("{{chip}}", self._opx_iface.chips[-1])
            index_html = index_html.replace("{{compat}}", ", ".join(self._opx_iface.chips))
            index_html = index_html.replace("{{url_display}}",
                                            "block" if self._allow_urls else "none")
            return aiohttp.web.Response(text=index_html, content_type="text/html")

    async def serve_vgm(self, request):
        sock = aiohttp.web.WebSocketResponse()
        await sock.prepare(request)

        headers = await sock.receive_json()
        vgm_msg = await sock.receive()

        if vgm_msg.type == aiohttp.WSMsgType.BINARY:
            vgm_data = vgm_msg.data
        elif vgm_msg.type == aiohttp.WSMsgType.TEXT:
            self._logger.info("web: URL %s submitted by %s",
                              vgm_msg.data, request.remote)

            if not self._allow_urls:
                self._logger.warning("Received URL submission when disabled")
                await sock.close(code=405, message="URL submissions not allowed")
                return sock

            async with aiohttp.ClientSession() as client_sess:
                async with client_sess.get(vgm_msg.data) as client_resp:
                    if client_resp.status != 200:
                        await sock.close(code=2000 + client_resp.status,
                                         message=client_resp.reason)
                        return sock

                    if "Content-Length" not in client_resp.headers:
                        await sock.close(code=2999, message=
                            "Remote server did not specify Content-Length")
                        return sock
                    elif int(client_resp.headers["Content-Length"]) > (1<<20):
                        await sock.close(code=2999, message=
                            "File too large ({} bytes) to be fetched"
                            .format(client_resp.headers["Content-Length"]))
                        return sock

                    vgm_data = await client_resp.read()
        else:
            assert vgm_msg.type == aiohttp.WSMsgType.ERROR
            self._logger.warning("web: broken upload: %s", vgm_msg.data)
            return sock

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

            clock_rate, clock_prescaler = self._opx_iface.get_vgm_clock_rate(vgm_reader)
            if clock_rate == 0:
                raise ValueError("VGM file contains commands for {}, which is not a supported chip"
                                 .format(", ".join(vgm_reader.chips())))
            if clock_rate & 0xc0000000:
                raise ValueError("VGM file uses unsupported chip configuration")
            if len(vgm_reader.chips()) != 1:
                raise ValueError("VGM file contains commands for {}, but only playback of exactly "
                                 "one chip is supported"
                                 .format(", ".join(vgm_reader.chips())))
            clock_rate *= clock_prescaler

            self._logger.info("web: %s: VGM is looped for %.2f/%.2f s",
                              digest, vgm_reader.loop_seconds, vgm_reader.total_seconds)

            vgm_player = YamahaVGMStreamPlayer(vgm_reader, self._opx_iface, clock_rate)
        except ValueError as e:
            self._logger.warning("web: %s: broken upload: %s",
                                 digest, str(e))
            await sock.close(code=1001, message=str(e))
            return sock

        sample_rate = 1 / vgm_player.sample_time
        self._logger.info("web: %s: sample rate %d", digest, sample_rate)

        async with self._lock:
            try:
                voltage = float(headers["Voltage"])
                self._logger.info("web: %s: setting voltage to %.2f V", digest, voltage)
                await self._set_voltage(voltage)

            except Exception as error:
                await sock.close(code=2000, message=str(error))
                return sock

            self._logger.info("web: %s: start streaming", digest)

            await self._opx_iface.reset()
            if self._opx_iface.filter is not None:
                self._opx_iface.filter.sample_rate = sample_rate * self._opx_iface.sample_clocks
            # Soft reset does not clear all the state immediately, so wait a bit to make sure
            # all notes decay, etc.
            await vgm_player.wait_seconds(1)

            sample_queue = asyncio.Queue()
            record_fut = asyncio.ensure_future(vgm_player.record(sample_queue))
            play_fut   = asyncio.ensure_future(vgm_player.play())

            try:
                total_samples = int(vgm_reader.total_seconds * sample_rate)
                if vgm_reader.loop_samples in (0, vgm_reader.total_samples):
                    # Either 0 or the entire VGM here means we'll loop the complete track.
                    loop_skip_to = 0
                else:
                    loop_skip_to = int((vgm_reader.total_seconds - vgm_reader.loop_seconds)
                                       * sample_rate)
                await sock.send_json({
                    "Chip": vgm_reader.chips()[0],
                    "Channel-Count": self._opx_iface.channel_count,
                    "Sample-Rate": sample_rate,
                    "Total-Samples": total_samples,
                    "Loop-Skip-To": loop_skip_to,
                })

                while True:
                    if play_fut.done() and play_fut.exception():
                        break

                    samples = await asyncio.wait_for(sample_queue.get(), timeout=5.0)
                    if not samples:
                        break
                    await sock.send_bytes(samples)

                for fut in [play_fut, record_fut]:
                    try:
                        await fut
                    except NotImplementedError as e:
                        self._logger.exception("web: %s: error streaming",
                                               digest)
                        await sock.close(code=2000, message=str(e))
                        return sock

                self._logger.info("web: %s: done streaming",
                                  digest)
                await sock.close()

            except asyncio.TimeoutError:
                self._logger.info("web: %s: timeout streaming",
                                  digest)
                await sock.close(code=1002, message="Streaming timeout (glitched too hard?)")

                for fut in [play_fut, record_fut]:
                    if not fut.done():
                        fut.cancel()

            except asyncio.CancelledError:
                self._logger.info("web: %s: cancel streaming",
                                  digest)

                for fut in [play_fut, record_fut]:
                    if not fut.done():
                        fut.cancel()
                raise

            return sock

    async def serve(self, endpoint):
        app = aiohttp.web.Application()
        app.add_routes([
            aiohttp.web.get("/",    self.serve_index),
            aiohttp.web.get("/vgm", self.serve_vgm),
        ])

        try:
            from aiohttp_remotes import XForwardedRelaxed, setup as setup_remotes
            await setup_remotes(app, XForwardedRelaxed())
        except ImportError:
            self._logger.warning("aiohttp_remotes not installed; X-Forwarded-For will not be used")

        runner = aiohttp.web.AppRunner(app,
            access_log_format='%a(%{X-Forwarded-For}i) "%r" %s "%{Referer}i" "%{User-Agent}i"')
        await runner.setup()
        parsed_endpoint = urlparse(f"//{endpoint}")
        site = aiohttp.web.TCPSite(runner, parsed_endpoint.hostname, parsed_endpoint.port)
        await site.start()
        await asyncio.Future()


class AudioYamahaOPxApplet(GlasgowApplet):
    logger = logging.getLogger(__name__)
    help = "drive and record Yamaha OP* FM synthesizers"
    description = """
    Send commands and record digital output from Yamaha OP* series FM synthesizers.
    The supported chips are:
        * YM3526 (OPL)
        * YM3812 (OPL2)
        * YMF262 (OPL3)
        * YM2151 (OPM)

    The ~CS input should always be grounded, since there is only one chip on the bus in the first
    place.

    The digital output is losslessly converted to 16-bit signed PCM samples. (The Yamaha DACs
    only have 16 bit of dynamic range, and there is a direct mapping between the on-wire format
    and ordinary 16-bit PCM.)

    The written samples can be played with the knowledge of the sample rate, which is derived from
    the master clock frequency specified in the input file. E.g. using SoX:

        $ play -r 49715 output.s16

    # Scripting

    Commands for the synthesizer can be generated procedurally with a Python script, using
    the `run` subcommand and a file such as the following:

    ::
        samples = 49715
        async def main(iface):
            await iface.enable()
            await iface.write_register(...)
            await iface.wait_clocks(iface.sample_clocks * samples)
            await iface.disable()

    Commands submitted to the synthesizer can be preprocessed with a Python script, e.g.
    for glitching, using the --filter option and a file such as the following:

    ::
        class CommandFilter(YamahaOPxCommandFilter):
            async def write_register(self, address, data):
                ...
                return (address, data)
    """

    __pin_sets = ("d", "a")
    __pins = ("wr", "rd", "clk_m",
              "sh", "mo", "clk_sy",
              "cs", "ic")

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_set_argument(parser, "d", width=8, default=True)
        access.add_pin_set_argument(parser, "a", width=range(1, 3), default=2)
        access.add_pin_argument(parser, "wr", default=True)
        access.add_pin_argument(parser, "rd", default=True)
        access.add_pin_argument(parser, "clk_m", default=True)
        access.add_pin_argument(parser, "sh", default=True)
        access.add_pin_argument(parser, "mo", default=True)
        access.add_pin_argument(parser, "clk_sy", default=True)
        access.add_pin_argument(parser, "cs", required=False)
        access.add_pin_argument(parser, "ic", required=False)

        parser.add_argument(
            "-d", "--device", metavar="DEVICE", choices=["OPL", "OPL2", "OPL3", "OPM"],
            required=True,
            help="synthesizer family")
        parser.add_argument(
            "-o", "--overclock", metavar="FACTOR", type=float, default=1.0,
            help="overclock device by FACTOR to improve throughput")

    @staticmethod
    def _device_iface_cls(args):
        if args.device == "OPL":
            return YamahaOPLInterface
        if args.device == "OPL2":
            return YamahaOPL2Interface
        if args.device == "OPL3":
            return YamahaOPL3Interface
        if args.device == "OPM":
            return YamahaOPMInterface
        assert False

    def build(self, target, args):
        device_iface_cls = self._device_iface_cls(args)

        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        subtarget = iface.add_subtarget(YamahaOPxSubtarget(
            pads=iface.get_pads(args, pins=self.__pins, pin_sets=self.__pin_sets),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(auto_flush=False),
            sample_decoder_cls=device_iface_cls.sample_decoder,
            channel_count=device_iface_cls.channel_count,
            master_cyc=self.derive_clock(
                input_hz=target.sys_clk_freq,
                output_hz=device_iface_cls.max_master_hz * args.overclock),
            read_pulse_cyc=int(target.sys_clk_freq * 200e-9),
            write_pulse_cyc=int(target.sys_clk_freq * 100e-9),
            address_clocks=device_iface_cls.address_clocks,
            data_clocks=device_iface_cls.data_clocks,
        ))
        return subtarget

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)

        parser.add_argument(
            "--filter-script", dest="filter_script_file", metavar="FILTER-SCRIPT-FILE",
            type=argparse.FileType("rb"),
            help="filter commands via Python script FILTER-SCRIPT-FILE")

    async def run(self, device, args):
        device_iface_cls = self._device_iface_cls(args)

        if args.filter_script_file is None:
            filter = None
        else:
            filter_context = dict(YamahaOPxCommandFilter=YamahaOPxCommandFilter)
            exec(compile(args.filter_script_file.read(), args.filter_script_file.name,
                         mode="exec"), filter_context)
            filter_cls = filter_context.get("CommandFilter", None)
            if not filter_cls:
                raise GlasgowAppletError("Script should define a class 'CommandFilter'")
            filter = filter_cls()

        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args,
            write_buffer_size=128)
        opx_iface = device_iface_cls(iface, self.logger, filter=filter)
        await opx_iface.reset()
        return opx_iface

    @classmethod
    def add_interact_arguments(cls, parser):
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

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
        p_web.add_argument(
            "--allow-urls", action='store_true',
            help="allow users to specify a URL to play a VGM/VGZ file from (use with caution)")
        p_web.add_argument(
            "endpoint", metavar="ENDPOINT", type=str, default="localhost:8080",
            help="listen for requests on ENDPOINT (default: %(default)s)")

        p_run = p_operation.add_parser(
            "run", help="run a Python script driving the synthesizer and record PCM")
        p_run.add_argument(
            "script_file", metavar="SCRIPT-FILE", type=argparse.FileType("rb"),
            help="run Python script SCRIPT-FILE")
        p_run.add_argument(
            "pcm_file", metavar="PCM-FILE", type=argparse.FileType("wb"),
            help="write samples to PCM-FILE")

    async def interact(self, device, args, opx_iface):
        if args.operation == "convert":
            vgm_reader = VGMStreamReader.from_file(args.vgm_file)
            self.logger.info("VGM file contains commands for %s", ", ".join(vgm_reader.chips()))
            if len(vgm_reader.chips()) != 1:
                raise GlasgowAppletError("VGM file does not contain commands for exactly one chip")

            clock_rate, clock_prescaler = opx_iface.get_vgm_clock_rate(vgm_reader)
            if clock_rate == 0:
                raise GlasgowAppletError("VGM file does not contain commands for any supported "
                                         "chip")
            if clock_rate & 0xc0000000:
                raise GlasgowAppletError("VGM file uses unsupported chip configuration")
            clock_rate *= clock_prescaler

            vgm_player = YamahaVGMStreamPlayer(vgm_reader, opx_iface, clock_rate)
            sample_rate = 1 / vgm_player.sample_time
            if opx_iface.filter:
                opx_iface.filter.sample_rate = sample_rate * opx_iface.sample_clocks
            self.logger.info("recording %d channels at sample rate %d Hz",
                             opx_iface.channel_count, sample_rate)

            async def write_pcm(sample_queue):
                while True:
                    samples = await sample_queue.get()
                    if not samples:
                        break
                    args.pcm_file.write(samples)

            sample_queue = asyncio.Queue()
            play_fut   = asyncio.ensure_future(vgm_player.play())
            record_fut = asyncio.ensure_future(vgm_player.record(sample_queue))
            write_fut  = asyncio.ensure_future(write_pcm(sample_queue))
            done, pending = await asyncio.wait([play_fut, record_fut, write_fut],
                                               return_when=asyncio.FIRST_EXCEPTION)
            for fut in done:
                await fut

        if args.operation == "web":
            async def set_voltage(voltage):
                await device.set_voltage(args.port_spec, voltage)
            web_iface = YamahaOPxWebInterface(self.logger, opx_iface, set_voltage, args.allow_urls)
            await web_iface.serve(args.endpoint)

        if args.operation == "run":
            context = dict()
            exec(compile(args.script_file.read(), args.script_file.name, mode="exec"), context)
            if not isinstance(context.get("samples", None), int):
                raise GlasgowAppletError("Script should set 'samples' to an int")
            if not hasattr(context.get("main"), "__call__"):
                raise GlasgowAppletError("Script should define a function 'main'")

            self.logger.info("recording %d channels", opx_iface.channel_count)
            await opx_iface._use_highest_level()
            record_fut = asyncio.ensure_future(opx_iface.read_samples(context["samples"]))
            play_fut   = asyncio.ensure_future(context["main"](opx_iface))
            done, pending = await asyncio.wait([play_fut, record_fut],
                                               return_when=asyncio.FIRST_EXCEPTION)
            for fut in done:
                await fut
            args.pcm_file.write(record_fut.result())

    @classmethod
    def tests(cls):
        from . import test
        return test.AudioYamahaOPxAppletTestCase
