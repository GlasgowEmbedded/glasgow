# Acknowledgements: thanks to William D. Jones (@cr1901), Eric Smith (@brouhaha) for explaining
# to me (whitequark) how floppy drives work.

# The protocols and standards are diffuse, scarce, and generally hard to understand, so here's
# a quick introduction to the entire stack.
#
# Note that all paragraphs below aren't authoritative statements on (ancient) circuit design,
# but just my own understanding and the results of my own experiments on floppy drives.
# I'm not old enough to actually have designed with any of these parts. Corrections welcome.
#   --whitequark
#
# Floppy drive bus logic
# ----------------------
#
# The entire Shugart bus is a TTL bus. Not TTL *level* bus, mind you (though it does use 5V);
# it uses actual transistor-transistor logic. To recap, TTL logic works by having a pull-up
# resistor and having (often a few) transistors in a common-emitter configuration. This resistor
# might actually be present on the die, or not! Conversely, the inputs connect to transistor
# bases, and so are *not* high-impedance. Note also that the common logic implemented in TTL
# would naturally have inverting outputs unless one specifically adds inverting transistors
# on the outputs.
#
# In practice, this has the following consequences:
#
#   1. The logic levels on the bus are inverted wrt physical levels. I.e. "active" is 0 V,
#      and "inactive" is Vcc (that is, 5 V).
#   2. Any inputs of the device sink a small amount of current when they are being driven
#      logically high (to 0 V), so the bus master needs to source that. They might be
#      pulled up with a small value resistor, so the bus master must be prepared to sink
#      the pull-up current, at least 32 mA.
#   3. Any outputs of the device can sink large amounts of current, at least 32 mA, and might
#      or might not be pulled up on the device. So, the bus master must add the pull-ups,
#      in case the outputs aren't already terminated.
#
# Floppy drive constraints
# ------------------------
#
# In spite of having a TTL interface, the floppy drive is effectively an analog device.
# It is not synchronous to any clock, the drive circuitry has plenty of constraints defined
# in terms of mechanical movement, and the magnetic head interface is entirely analog.
# The circuitry within the floppy drive does bare minimum maintenance (for example, it will
# maintain a constant and reasonably well defined rotational speed), but nothing beyond that.
# It is the job of the controller to transfer data into and out of the digital domain.
#
# Floppy drive bus signals
# ------------------------
#
# The floppy drive bus (also called the Shugart bus, after the inventor) usually uses a 34-pin IDC # cable and connector. (The original Shugart bus used a 50-pin connector, but the same electrical
# interface; these are used interchangeably in this document). All of the odd pins carry ground,
# and half of them are missing in the floppy drive connector.
#
# The remaining signals are assigned as follows, with "input" being the input of the drive:
#
#   No. Name  Dir Function
#    2. REDWC  I  Density Select
#    4.  N/C
#    6.  N/C
#    8. Index  O  Index (See Note 2)
#   10. MOTEA  I  Motor Enable A
#   12. DRVSA  I  Drive Select A
#   14. DRVSB  I  Drive Select B
#   16. MOTEB  I  Motor Enable B
#   18. DIR    I  Head Direction Select
#   20. STEP   I  Head Step Strobe
#   22. WDATA  I  Write Data
#   24. WGATE  I  Write Enable
#   26. TRK00  O  Track 00
#   28. WPT    O  Write Protect
#   30. RDATA  O  Read Data
#   32. SIDE1  I  Head Select
#   34. RDY    O  Drive Ready
#
# Pin functions are explained as follows:
#
#   * REDWC does not have any function on 3.5" drives, since the drives can handle disks of
#     any density, and the density is keyed on the disc itself. Should be treated as Reserved
#     on 3.5" drives.
#   * INDEX is a strobe that on 3.5" drives becomes active at some predefined region once per
#     revolution of the drive motor. (This is usually implemented with a Hall sensor.) This strobe
#     has no correlation to any positioning or data on the disk, and should only be used to read
#     a complete track, by reading from INDEX strobe to INDEX strobe.
#   * Any single drive is selected (activates its output drives) with a DRVSx signal, and spins
#     its motor when MOTEx signal is asserted. This is selected with a jumper, usually a solder
#     jumper, on the drive. By convention, drives are jumpered to respond to DRVSB/MOTEB.
#     The IBM PC floppy drive cables use a 7-pin twist that causes both drives to observe
#     the appropriate host control signals on DRVSB/MOTEB.
#   * A pulse on STEP moves the head one track in the direction determined by DIR; when DIR
#     is active, a STEP pulse moves the head towards track 0. DIR to STEP S/H time is 1/25 us.
#     Minimum STEP pulse width is 7 us and period is 6 ms.
#   * TRK00 becomes active when the head is positioned at track 0. This is done with
#     an optocoupler. The head will usually not move beyond track 0, but will attempt to move
#     (and fail to do so) beyond track 80.
#   * RDATA and WDATA transmit and receive pulse trains where pulses indicate changes in
#     magnetic flux. More on that later.
#   * When WGATE is active, pulse train on WDATA is written to the disk. Else, it is ignored.
#   * WPT is active when the disk is configured to be read-only by obscuring a window with
#     a sliding tab. This is detected with a microswitch. (TO BE EXPANDED)
#   * RDY is (TO BE EXPANDED)
#
# Floppy drive mechanics
# ----------------------
#
# A few timing requirements have to be absolutely respected in order for mechanics to work
# properly. These include:
#
#   1. Time from MOTEx rising edge to accessing any data: 250 ms.
#      This allows the motor to reach a stable rotational speed.
#   2. Time from moving the head to accessing any data: 15 ms.
#      This allows the head to cease vibrating.
#
# Fundamentals of data encoding
# -----------------------------
#
# The floppy disk read head is an inductive device, and so it senses a derivative of the magnetic
# flux. When the magnetic domain changes orientation, the read head produces a pulse. This pulse
# is detected by the analog circuitry in the drive, which performs basic signal conditioning.
# The pulse amplitude can vary greatly, and so automatic gain control is employed to bring
# the pulse to logic levels. AGC requires at least a single flux reversal per 12 us, or else it
# would overcompensate and start to amplify random noise. (This is sometimes used as a copy
# protection mechanism.)
#
# Thus, the pulse train that comes from RDATA can be described as pulse density modulated.
# Each pulse has roughly the same duration (defined by drive design), but the interval between
# pulses varies and corresponds to the flux domain sizes. There is no correspondence between
# absolute magnetization direction and pulse train, i.e. reading NNNNNNNNSS produces the same
# pulse as reading SSSSSSSSNN.
#
# Higher layers have to handle synchronization and minimum pulse density requirements for this
# encoding scheme. On IBM PC, only FM and MFM were used, with FM being largely irrelevant.
#
# MFM modulation scheme
# ---------------------
#
# The pulse train is generally divided into equal bit times, and presence of a pulse during
# a certain bit window is treated as line "1", whereas absence of a pulse as line "0".
# The duration of the pulse is, as can be seen from the description above, irrelevant, and
# for practical purposes a demodulator can be purely edge triggered.
#
# MFM, although not usually described as such, is a classic 1b2b line code. It only attempts to
# provide guaranteed state changes for AGC and clock recovery, and makes no attempt at e.g. DC
# balance (which indeed is not necessary for the medium). MFM uses three different symbols
# (conventionally called "cells" in the context of floppy drives), 01, 10 and 00, and uses
# coding violations as commas instead of special symbols.
#
# The MFM encoding process works as follows.
#
#   * Encode bit 1 as 01.
#   * Encode bit 0 as 00 -if- the preceding bit was 1 (symbol 01).
#   * Encode bit 0 as 10 -if- the preceding bit was 0 (symbol 00 or 10).
#
# It can be seen that this line code only produces pulses of 2, 3, or 4 bit times in length,
# in other words, 10, 100, and 1000. All other pulses are illegal, and indicative of a mis-locked
# PLL or faulty medium.
#
# The bits are encoded MSB first. For example, 0x9A (0b10011010) is encoded as follows:
#
#   01 00 10 01 01 10 01 10
#
# The MFM encoding does not inherently define any commas, but two commas are commonly used,
# C2 with coding violation and A1 with coding violation, hereafter called "K.C2" and "K.A1",
# (also conventionally called "5224" and "4489", respectively, in the context of floppy drives).
# Their encoding is as follows, with * marking the violation (symbol 00 after symbol 10):
#
#   K.C2: 01 01 00 10 00 10 01 00
#                      *
#   K.A1: 01 00 01 00 10 00 10 01
#                         *
#
# The comma K.A1 is used because normal MFM-encoded data never produces its bit stream, including
# if the output is considered 180° out of phase. Thus, it may be safely used for synchronization.
# The comma K.C2 is produced if the sequence <000101001> is encoded and read 180° out of phase,
# producing a sequence containing K.C2:
#
#   ?0 10 10 01 00 01 00 10 01
#    0  0  0  1  0  1  0  0  1
#
# Note that encountering a comma implies a requirement to realign the bitstream immediately.
# This includes such sequences as <K.C2 0 K.A1 K.A1>, which would produce an invalid reading
# if the receiver stays synchronized to <K.C2> after encountering the <0 K.A1> sequence.
#
# Also note that since the comma K.C2 can be produced by normal encoded data, it is not actually
# useful for synchronization. The raw read track WD1772 resyncs on each K.A1 and K.C2, and
# the latter causes loss of sync in the middle of a track, and this can indeed be easily
# reproduced. There is generally no point in recognizing K.C2 at all.
#
# Other than the (recognized and accepted) coding violation, a comma behaves exactly like any
# other encoded byte; if a zero is encoded after K.C2, it is encoded as 10, and if after K.A1,
# it is encoded as 00.
#
# Although not special in any way, an additional useful code is 0x4E. This is encoded as:
#
#     4E: 10 01 00 10 01 01 01 00
#
# A sequence of encoded 4E bytes produces infinite repeats of the pattern <1001001001010100>,
# which can be used to train a phase-locked loop. This is important because recovering a clock
# from the MFM encoded data is inherently ambiguous; e.g. for an incoming pulse train of the form
# <10101010...> where the bit time is 3x, it is equvally valid for a PLL to lock onto the smaller
# period, effectively treating the incoming pulse train as <100100100...> where the bit time is 2x.
# Rejecting the sequence <1000> as invalid while locking the PLL makes clock recovery easier by
# effectively placing a lower bound on the bit time.
#
# Track layout
# ------------
#
# The IBM floppy disk track format is designed to be rewritable sector-by-sector. As such,
# it has the following general layout, with N being roughly variable, and X roughly fixed:
#
#   (N gap bytes) (X zero bytes) (sync/type) (header) (CRC)
#   (N gap bytes) (X zero bytes) (sync/type) (data)   (CRC) ... and so on, repeated.
#
# The purpose of the gap bytes is as follows. Rewriting the data for a single sector requires
# first positioning the head at this sector, and then switching from reading to writing.
# The sector header, separate from data, allows for such positioning. Gap bytes (0x4E, for
# the reasons stated above), carry no semantic meaning and can be overwritten, requiring no
# precise timing for such writes, and additionally tolerating the erase head affecting a larger
# area of the medium than the write head. (I.e. there is always slightly more data erased
# than there is written.)
#
# Track format
# ------------
#
# (TO BE EXPANDED)

import logging
import asyncio
import argparse
import struct
import random
import math
from migen import *
from migen.genlib.fsm import FSM
from migen.genlib.cdc import MultiReg

from . import *
from ..gateware.pads import *


class ShugartFloppyBus(Module):
    def __init__(self, pins):
        self.redwc  = Signal()
        self.index  = Signal()
        self.drvs   = Signal()
        self.mote   = Signal()
        self.dir    = Signal()
        self.step   = Signal()
        self.wdata  = Signal()
        self.wgate  = Signal()
        self.trk00  = Signal()
        self.wpt    = Signal()
        self.rdata  = Signal()
        self.side1  = Signal()
        self.dskchg = Signal()

        self.index_e = Signal()

        ###

        self.comb += [
            pins.redwc_t.oe.eq(1),
            pins.redwc_t.o.eq(~self.redwc),
            pins.drvs_t.oe.eq(1),
            pins.drvs_t.o.eq(~self.drvs),
            pins.mote_t.oe.eq(1),
            pins.mote_t.o.eq(~self.mote),
            pins.dir_t.oe.eq(1),
            pins.dir_t.o.eq(~self.dir),
            pins.step_t.oe.eq(1),
            pins.step_t.o.eq(~self.step),
            pins.wdata_t.oe.eq(1),
            pins.wdata_t.o.eq(~self.wdata),
            pins.wgate_t.oe.eq(1),
            pins.wgate_t.o.eq(~self.wgate),
            pins.side1_t.oe.eq(1),
            pins.side1_t.o.eq(~self.side1),
        ]
        self.specials += [
            MultiReg(~pins.index_t.i, self.index),
            MultiReg(~pins.trk00_t.i, self.trk00),
            MultiReg(~pins.wpt_t.i, self.wpt),
            MultiReg(~pins.rdata_t.i, self.rdata),
            MultiReg(~pins.dskchg_t.i, self.dskchg),
        ]

        index_r = Signal()
        self.sync += index_r.eq(self.index)
        self.comb += self.index_e.eq(index_r & ~self.index)


CMD_SYNC  = 0x00
CMD_START = 0x01
CMD_STOP  = 0x02
CMD_TRK0  = 0x03
CMD_TRK   = 0x04
CMD_MEAS  = 0x05
CMD_READ_RAW = 0x06

TLR_DATA  = 0x00
TLR_ERROR = 0xff


class ShugartFloppySubtarget(Module):
    def __init__(self, pins, out_fifo, in_fifo, sys_freq):
        self.submodules.bus = bus = ShugartFloppyBus(pins)

        spin_up_cyc  = math.ceil(250e-3 * sys_freq) # motor spin up
        setup_cyc    = math.ceil(1e-6   * sys_freq) # pulse setup time
        trk_step_cyc = math.ceil(7e-6   * sys_freq) # step pulse width
        trk_trk_cyc  = math.ceil(6e-3   * sys_freq) # step pulse period
        settle_cyc   = math.ceil(15e-3  * sys_freq) # step to head settle interval
        timer        = Signal(max=max(spin_up_cyc, setup_cyc, trk_step_cyc, trk_trk_cyc,
                                      settle_cyc))

        cmd     = Signal(8)

        cur_trk = Signal(max=80)
        tgt_trk = Signal.like(cur_trk)
        trk_len = Signal(24)

        shreg   = Signal(8)
        bitno   = Signal(max=8)
        trailer = Signal(max=254)
        pkt_len = Signal(max=254)

        self.submodules.fsm = FSM(reset_state="READ-COMMAND")
        self.fsm.act("READ-COMMAND",
            in_fifo.flush.eq(1),
            If(timer == 0,
                If(out_fifo.readable,
                    out_fifo.re.eq(1),
                    NextValue(cmd, out_fifo.dout),
                    NextState("COMMAND")
                )
            ).Else(
                NextValue(timer, timer - 1)
            )
        )
        self.fsm.act("COMMAND",
            If(cmd == CMD_SYNC,
                If(in_fifo.writable,
                    in_fifo.we.eq(1),
                    NextState("READ-COMMAND")
                )
            ).Elif(cmd == CMD_START,
                NextValue(bus.drvs, 1),
                NextValue(bus.mote, 1),
                NextValue(timer, spin_up_cyc - 1),
                NextState("READ-COMMAND")
            ).Elif(cmd == CMD_STOP,
                NextValue(bus.drvs, 0),
                NextValue(bus.mote, 0),
                NextState("READ-COMMAND")
            ).Elif(cmd == CMD_TRK0,
                NextValue(bus.dir, 0), # DIR->STEP S/H=1/24us
                NextValue(timer, setup_cyc - 1),
                NextState("TRACK-STEP")
            ).Elif(cmd == CMD_TRK,
                If(out_fifo.readable,
                    out_fifo.re.eq(1),
                    NextValue(tgt_trk, out_fifo.dout),
                    NextValue(bus.dir, out_fifo.dout > cur_trk),
                    NextValue(timer, setup_cyc - 1),
                    NextState("TRACK-STEP")
                )
            ).Elif(cmd == CMD_MEAS,
                If(bus.index_e,
                    NextValue(trk_len, 1),
                    NextState("MEASURE")
                )
            ).Elif(cmd == CMD_READ_RAW,
                If(bus.index_e,
                    NextValue(shreg, bus.rdata),
                    NextValue(bitno, 1),
                    NextValue(pkt_len, 0),
                    NextState("READ-RAW")
                )
            )
        )
        self.fsm.act("TRACK-STEP",
            If(timer == 0,
                If((cmd == CMD_TRK0) & bus.trk00,
                    NextValue(cur_trk, 0),
                    NextValue(timer, settle_cyc - 1),
                    NextState("READ-COMMAND")
                ).Elif((cmd == CMD_TRK) & (cur_trk == tgt_trk),
                    NextValue(timer, settle_cyc - 1),
                    NextState("READ-COMMAND")
                ).Else(
                    If(bus.dir,
                        NextValue(cur_trk, cur_trk + 1)
                    ).Else(
                        NextValue(cur_trk, cur_trk - 1)
                    ),
                    NextValue(bus.step, 1),
                    NextValue(timer, trk_step_cyc - 1),
                    NextState("TRACK-HOLD")
                )
            ).Else(
                NextValue(timer, timer - 1)
            )
        )
        self.fsm.act("TRACK-HOLD",
            If(timer == 0,
                NextValue(bus.step, 0),
                NextValue(timer, trk_trk_cyc - 1),
                NextState("TRACK-STEP")
            ).Else(
                NextValue(timer, timer - 1)
            )
        )
        self.fsm.act("MEASURE",
            If(bus.index_e,
                NextState("WRITE-MEASURE-0")
            ).Else(
                NextValue(trk_len, trk_len + 1),
            )
        )
        for n in range(3):
            self.fsm.act("WRITE-MEASURE-%d" % n,
                If(in_fifo.writable,
                    in_fifo.we.eq(1),
                    in_fifo.din.eq(trk_len[8 * n:]),
                    NextState("WRITE-MEASURE-%d" % (n + 1) if n < 2 else "READ-COMMAND")
                )
            )
        self.fsm.act("READ-RAW",
            If(bus.index_e,
                NextValue(trailer, TLR_DATA + pkt_len),
                NextState("WRITE-TRAILER")
            ).Else(
                NextValue(shreg, Cat(bus.rdata, shreg)),
                NextValue(bitno, bitno + 1),
                If(bitno == 7,
                    If(pkt_len == 254,
                        NextValue(trailer, TLR_ERROR),
                        NextState("WRITE-TRAILER")
                    ).Else(
                        in_fifo.we.eq(1),
                        in_fifo.din.eq(shreg),
                        NextValue(pkt_len, pkt_len + 1),
                    )
                ).Elif(pkt_len == 254,
                    in_fifo.we.eq(1),
                    in_fifo.din.eq(TLR_DATA + pkt_len),
                    NextValue(pkt_len, 0)
                ),
                If(in_fifo.we & ~in_fifo.writable,
                    NextValue(trailer, TLR_ERROR),
                    NextValue(pkt_len, pkt_len),
                    NextState("WRITE-TRAILER")
                )
            )
        )
        self.fsm.act("WRITE-TRAILER",
            If(in_fifo.writable,
                in_fifo.we.eq(1),
                If(pkt_len != 254,
                    in_fifo.din.eq(0xaa),
                    NextValue(pkt_len, pkt_len + 1),
                ).Else(
                    in_fifo.din.eq(trailer),
                    NextState("READ-COMMAND")
                )
            )
        )


class ShugartFloppyInterface:
    def __init__(self, interface, logger):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

    def _log(self, message, *args):
        self._logger.log(self._level, "Shugart Floppy: " + message, *args)

    async def _sync(self):
        await self.lower.write([CMD_SYNC])
        await self.lower.read(1)

    async def start(self):
        self._log("start")
        await self.lower.write([CMD_START, CMD_TRK0])
        await self._sync()

    async def stop(self):
        self._log("stop")
        await self.lower.write([CMD_STOP])
        await self._sync()

    async def seek_track(self, track):
        self._log("seek track=%d", track)
        await self.lower.write([CMD_TRK, track])
        await self._sync()

    async def measure_track(self):
        await self.lower.write([CMD_MEAS])
        result = await self.lower.read(3)
        cycles = result[0] | (result[1] << 8) | (result[2] << 16)
        self._log("measure track cycles=%d ms=%.3f rpm=%.3f",
                  cycles, cycles / 30e6 * 1e3, 30e6 / cycles * 60)
        return cycles

    async def _read_packet(self, hint):
        data     = await self.lower.read(254, hint)
        trailer, = await self.lower.read(1, hint)
        if trailer != TLR_ERROR:
            return data[:trailer]

    async def read_track_raw(self, hint):
        self._log("read track raw")
        index = 0
        data  = bytearray()
        await self.lower.write([CMD_READ_RAW])
        while True:
            packet = await self._read_packet(hint)
            if packet is None:
                raise GlasgowAppletError("FIFO overflow while reading track")

            data  += packet
            index += 1
            if len(packet) < 254:
                return data


class SoftwareMFMDecoder:
    def __init__(self, logger):
        self._logger    = logger
        self._lock_time = 0
        self._bit_time  = 0

    def _log(self, message, *args):
        self._logger.log(logging.DEBUG, "soft-MFM: " + message, *args)

    def bits(self, bytestream):
        curr_bit = 0
        for byte in bytestream:
            for bit in range(7, -1, -1):
                yield (byte >> bit) & 1

    @staticmethod
    def repeat(bitstream):
        yield from bitstream()
        yield from bitstream()
        yield from bitstream()

    def pll(self, bitstream):
        cur_bit   = 0
        bit_tol   = 10
        bit_time  = 2 * bit_tol
        state     = "START"
        cell      = 0
        window    = 0
        window_no = 0
        in_phase  = 0
        locked    = False
        for offset, new_bit in enumerate(bitstream):
            edge    = cur_bit and not new_bit
            cur_bit = new_bit

            # |clk-------------|clk-------------|clk-------------|...
            # /¯¯¯\________WWWWWWWW_________WWWWWWWW______________...
            # 0000000000111111111122222222223333333333444444444455
            # 0123456789012345678901234567890123456789012345678901...
            # ^ START      ^ WINDOW-NEG     ^ WINDOW-NEG
            #                  ^ WINDOW-POS     ^ WINDOW-POS
            #                      ^ CONTINUE       ^ CONTINUE    ...

            if state == "START":
                if edge:
                    in_phase   = 0
                    bit_time   = 2 * bit_tol
                    self._log("pll loss leader bit-off=%d", offset)
                elif window == bit_time - bit_tol:
                    window     = 0
                    window_no  = 1
                    state      = "WINDOW-NEG"
            elif state == "WINDOW-NEG":
                if edge:
                    if (not locked and window_no in (2, 3) or
                            locked and window_no in (2, 3, 4)):
                        in_phase += 1
                    else:
                        in_phase  = 0
                        if locked:
                            self._log("pll loss +win=%d bit-off=%d", window_no, offset)
                    if bit_time > 2 * bit_tol:
                        bit_time  -= 1
                elif window == bit_tol:
                    state      = "WINDOW-POS"
            elif state == "WINDOW-POS":
                if edge:
                    if (not locked and window_no in (2, 3) or
                            locked and window_no in (2, 3, 4)):
                        in_phase += 1
                    else:
                        in_phase  = 0
                        if locked:
                            self._log("pll loss -win=%d bit-off=%d", window_no, offset)
                    bit_time  += 1
                elif window == bit_tol + bit_tol:
                    if locked: yield [0]
                    state      = "CONTINUE"
            elif state == "CONTINUE":
                if edge:
                    in_phase   = 0
                    bit_time  += 1
                    if locked:
                        self._log("pll loss gap bit-off=%d", offset)
                elif window == bit_time:
                    window     = 0
                    window_no += 1
                    state      = "WINDOW-NEG"

            if edge:
                if locked: yield [1]
                state   = "START"
                window  = 0
            else:
                window += 1

            # self._log("pll edge=%d cell=%3d win=%3d state=%10s bit=%3d inФ=%d",
            #           edge, cell, window, state, bit_time, in_phase)
            # if edge:
            #     cell  = 0
            # else:
            #     cell += 1

            if not locked and in_phase == 64:
                locked = True
                self._bit_time  = bit_time
                self._lock_time = offset
                self._log("pll locked bit-off=%d bit=%d", offset, bit_time)
            elif locked and in_phase == 0:
                locked = False

    def demodulate(self, chipstream):
        shreg  = []
        offset = 0
        synced = False
        prev   = 0
        bits   = []
        while True:
            while len(shreg) < 64:
                shreg += next(chipstream)

            synced_now = False
            for sync_offset in (0, 1):
                if shreg[sync_offset:sync_offset + 16] == [0,1,0,0,0,1,0,0, 1,0,0,0,1,0,0,1]:
                    if not synced or sync_offset != 0:
                        self._log("sync=K.A1 chip-off=%d", offset + sync_offset)
                    offset += sync_offset + 16
                    shreg   = shreg[sync_offset + 16:]
                    synced  = True
                    prev    = 1
                    bits    = []
                    yield "K.A1"
                    synced_now = True
                if synced_now: break

            if synced_now:
                continue
            elif not synced and len(shreg) >= 1:
                offset += 1
                shreg   = shreg[1:]

            if synced and len(shreg) >= 2:
                if shreg[0:2] == [0,1]:
                    curr = 1
                elif prev == 1 and shreg[0:2] == [0,0]:
                    curr = 0
                elif prev == 0 and shreg[0:2] == [1,0]:
                    curr = 0
                else:
                    synced = False
                    self._log("desync chip-off=%d bitno=%d prev=%d cell=%d%d",
                              offset, len(bits), prev, *shreg[0:2])

                if synced:
                    offset += 2
                    shreg   = shreg[2:]
                    prev    = curr

                    bits.append(curr)
                    if len(bits) == 8:
                        yield "%02X" % sum(bit << (7 - n) for n, bit in enumerate(bits))
                        bits = []


class ShugartFloppyApplet(GlasgowApplet, name="shugart-floppy"):
    preview = True
    logger = logging.getLogger(__name__)
    help = "read and write disks using IBM/Shugart floppy drives"
    description = """
    Read and write floppy disks using IBM/Shugart floppy drive interface. This is the interface
    used in common IBM/PC 5.25" and 3.5" floppy drives, as well as Amiga, various synthesizers,
    and so on.

    The connections should be made as follows (note that all odd numbered pins, i.e. entire
    key-side pin row, are all assigned to GND):

        * Output signals, with an external buffer that can sink at least 32 mA:
          REDWC=2 DRVS=12 MOTE=16 DIR=18 STEP=20 WDATA=22 WGATE=24 SIDE1=32
        * Input signals:
          INDEX=8 TRK00=26 WPT=28 RDATA=30 DSKCHG=34

    Or alternatively, from the perspective of the floppy drive connector, from pin 2 to pin 34,
    and assuming ports A and B are used:

        * REDWC=A0  NC        NC        INDEX=B0  NC        DRVSB=A1  NC        MOTEB=A2
          DIR=A3    STEP=A4   WDATA=A5  WGATE=A6  TRK00=B1  WPT=B2    RDATA=B3  SIDE1=A7
          DSKCHG=B4

    Note that all input signals require pull-ups, since the floppy drive outputs are open-drain.

    This applet supports reading raw (modulated), and raw (MFM-demodulated, in software)
    track data.
    """
    pins = ("redwc", "drvs", "mote", "dir", "step", "wdata", "wgate", "side1", # out
            "index", "trk00", "wpt", "rdata", "dskchg") # in

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        for pin in cls.pins:
            access.add_pin_argument(parser, pin, default=True)

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        iface.add_subtarget(ShugartFloppySubtarget(
            pins=iface.get_pads(pins=self.pins, args=args),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(auto_flush=False),
            sys_freq=target.sys_clk_freq,
        ))

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        return ShugartFloppyInterface(iface, self.logger)

    @classmethod
    def add_interact_arguments(cls, parser):
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION")

        p_read_raw = p_operation.add_parser(
            "read-raw", help="read raw track data")
        p_read_raw.add_argument(
            "file", metavar="FILE", type=argparse.FileType("wb"),
            help="write bit stream to FILE")
        p_read_raw.add_argument(
            "first", metavar="FIRST", type=int,
            help="read from track FIRST")
        p_read_raw.add_argument(
            "last", metavar="LAST", type=int,
            help="read until track LAST (inclusive)")

        p_read_track = p_operation.add_parser(
            "read-track", help="read and MFM-decode track data")
        p_read_track.add_argument(
            "track", metavar="TRACK", type=int,
            help="read track TRACK")

        p_test_pll = p_operation.add_parser(
            "test-pll", help="test software delay-locked loop for robustness")
        p_test_pll.add_argument(
            "count", metavar="COUNT", type=int,
            help="lock PLL on random bit offset COUNT times")
        p_test_pll.add_argument(
            "track", metavar="TRACK", type=int,
            help="read track TRACK")

    async def interact(self, device, args, floppy_iface):
        self.logger.info("starting up the drive")
        await floppy_iface.start()
        cycles = await floppy_iface.measure_track()

        try:
            if args.operation == "read-raw":
                for track in range(args.first, args.last + 1):
                    await floppy_iface.seek_track(track)
                    data = await floppy_iface.read_track_raw(hint=cycles // 8)
                    args.file.write(struct.pack(">BL", track, len(data)))
                    args.file.write(data)
                    args.file.flush()

            if args.operation == "read-track":
                await floppy_iface.seek_track(args.track)
                bytestream = await floppy_iface.read_track_raw(hint=cycles // 8)
                mfm        = SoftwareMFMDecoder(self.logger)
                bitstream  = mfm.repeat(lambda: mfm.bits(bytestream))
                chipstream = mfm.pll(bitstream)
                datastream = mfm.demodulate(chipstream)
                for _ in range(600*2):
                    print(next(datastream), end=" ", flush=True)
                print()

            if args.operation == "test-pll":
                await floppy_iface.seek_track(args.track)
                bytestream = await floppy_iface.read_track_raw(hint=cycles // 8)
                mfm        = SoftwareMFMDecoder(self.logger)
                bitstream  = list(mfm.bits(bytestream)) * 2

                lock_times = []
                bit_times  = []
                try:
                    for _ in range(args.count):
                        start = random.randint(0, len(bitstream) // 2)
                        next(mfm.pll(bitstream[start:]))
                        lock_times.append(mfm._lock_time)
                        bit_times.append(mfm._bit_time)
                        print(".", end="", flush=True)
                except Exception as e:
                    self.logger.warning("failed to lock (%s)", type(e))
                else:
                    print()
                    self.logger.info("locks=%d ttl=%d(%d-%d)us bit=%d(%d-%d)clk",
                                     args.count,
                                     sum(lock_times) // len(lock_times) // 30000,
                                     min(lock_times) // 30000,
                                     max(lock_times) // 30000,
                                     sum(bit_times) // len(bit_times),
                                     min(bit_times),
                                     max(bit_times))
        finally:
            await floppy_iface.stop()

# -------------------------------------------------------------------------------------------------

class ShugartFloppyAppletTestCase(GlasgowAppletTestCase, applet=ShugartFloppyApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
