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
# The floppy drive bus (also called the Shugart bus, after the inventor) usually uses a 34-pin IDC
# cable and connector. (The original Shugart bus used a 50-pin connector, but the same electrical
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
#
# The comma K.C2 is produced if the sequence <000101001> is encoded and read 180° out of phase,
# resulting in a sequence containing K.C2:
#
#   ?0 10 10 01 00 01 00 10 01
#    0  0  0  1  0  1  0  0  1
#
# However, the *repeated* comma K.C2 cannot result from reading a stream of normal data 180° out
# of phase, because that would include an illegal sequence <1000> on their boundary:
#
#   ?0 10 10 01 00 01 00 10 00 10 10 01 00 01 00 10 0?
#    <       first K.C2     ><       second K.C2    >
#                           *  coding violation
#
# Note that encountering a comma implies a requirement to realign the bitstream immediately.
# This includes such sequences as <K.C2 0 K.A1 K.A1>, which would produce an invalid reading
# if the receiver stays synchronized to <K.C2> after encountering the <0 K.A1> sequence.
#
# Also note that since the single comma K.C2 can be produced by normal encoded data, it is less
# useful for synchronization, as it is necessary to watch for at least two repeats of it.
# The raw read track command of WD1772 resyncs on each single occurrence of K.A1 and K.C2, with
# the latter causing loss of sync in the middle of a track.
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
# The most common floppy disk track format is IBM System 34. Unlike the details in the previous
# section (which apply with minor modifications to any format that uses sector granularity
# writes), these are specific for this track format. Nevertheless, the actual System 34 track
# format is *very* redundant, and many parts of it (e.g. anything to do with the K.C2 comma)
# are not required for full functionality, not used by most controllers, not written by many
# formatters, do not provide any benefit for verification (other than for copy protection
# and forensics purposes, which are out of scope for this document), and can be extremely variable
# in practice (e.g. the 2.88M format does away with most gap bytes). Thus, only the essential
# parts of the track format are documented, which are necessary and sufficient to produce
# a reasonably interoperable implementation.
#
# The track format consists of self-delimiting chunks, hereafter called "packets". A track
# will contain a number and sequence of packets generally set during formatting and dependent
# only on the media density.
#
# There are two System 34 packet types: the header packet and the data packet. The header packet
# indicates the sector number and corresponding data packet size, and also includes (redundant)
# location information, specifically cylinder and head numbers. The data packet contains sector
# data as-is.
#
# Each packet begins with a <K.A1 K.A1 K.A1 tt> sequence, where <tt> is a byte indicating
# the packet type; <FE> is followed by a header packet, and <FB> by a data packet.
# Each packet ends with a two-byte 16-bit CRC with generator polynomial 0x11021 (alternatively,
# x^16 + x^12 + x^5 + 1), initial value 0xffff, and no bit reversal. (Astute readers
# will recognize this as the "incorrect" CCITT CRC-16. Go figure.) The CRC includes the entire
# packet, including the three initial commas. As is usual, running the CRC over the entire packet
# leaves the residue zero if the packet has not been corrupted.
#
# Each packet is preceded by a number of gap (4E) and sync (00) bytes. In theory, the number of
# preceding sync bytes should be 12, and the number of gap bytes should be at least 50 for
# header packets and at least 20 for data packets, but in practice these requirements are
# stretched, without much harm to any high-quality controller.
#
# In theory, before the gap and sync bytes for the header packet there should be a sync packet
# with the <K.C2 K.C2 K.C2 FC> sequence (and its own gap and sync bytes as well), but it does
# not carry any useful information and I have not observed it on any of my floppies. Combined
# with the issues synchronizing on K.C2 described above, there is likely no point in recognizing
# K.C2 at all.
#
# In a more visual form, the packet formats are as follows:
#
#   Header packet: <4E 4E... 4E 00... 00 00
#                   K.A1 K.A1 K.A1 FE cn hn sn sz ch cl>,
#   where:
#     - cn is the cylinder number,
#     - hn is the head number,
#     - sn is the sector number,
#     - sz is the encoded sector size, where size equals 1<<(7+sz),
#     - chcl is the CRC.
#
#   Data packet:   <4E 4E... 4E 00... 00 00
#                   K.A1 K.A1 K.A1 dd dd dd dd... ch cl>,
#   where:
#     - dd... are the 1<<(7+sz) data bytes, for sz from preceding header packet,
#     - chcl is the CRC.
#
# The number of gap bytes can be significant (easily ~20% of the entire floppy surface), and is
# directly related to rewritability of the drive. A non-rewritable disk (or a disk designed
# to be always rewritten at track granularity, although industry has not produced any such
# standard disks, drives, or formats to my knowledge) does not require any gap bytes other than
# however many are necessary for the PLL in the controller to lock, and some more to pad the space
# on the track where its end meets its beginning. Such a floppy would have a much larger density.

import logging
import asyncio
import argparse
import struct
import random
import itertools
import crcmod
import math
from migen import *
from migen.genlib.cdc import MultiReg

from ....gateware.pads import *
from ... import *


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

        cur_rot = Signal(max=16)
        tgt_rot = Signal.like(cur_rot)

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
                    NextValue(tgt_trk, out_fifo.dout[1:]),
                    NextValue(bus.dir, out_fifo.dout[1:] > cur_trk),
                    NextValue(bus.side1, out_fifo.dout[0]),
                    NextValue(timer, setup_cyc - 1),
                    NextState("TRACK-STEP")
                )
            ).Elif(cmd == CMD_MEAS,
                If(bus.index_e,
                    NextValue(trk_len, 1),
                    NextState("MEASURE")
                )
            ).Elif(cmd == CMD_READ_RAW,
                If(out_fifo.readable,
                    out_fifo.re.eq(1),
                    NextValue(cur_rot, 0),
                    NextValue(tgt_rot, out_fifo.dout),
                    NextState("READ-RAW-SYNC")
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
        self.fsm.act("READ-RAW-SYNC",
            If(bus.index_e,
                NextValue(shreg, bus.rdata),
                NextValue(bitno, 1),
                NextValue(pkt_len, 0),
                NextState("READ-RAW")
            )
        )
        self.fsm.act("READ-RAW",
            If((cur_rot == tgt_rot) & bus.index_e,
                NextValue(trailer, TLR_DATA + pkt_len),
                NextState("WRITE-TRAILER")
            ).Else(
                If(bus.index_e,
                    NextValue(cur_rot, cur_rot + 1)
                ),
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
    def __init__(self, interface, logger, sys_clk_freq):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._sys_clk_freq = sys_clk_freq

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
                  cycles,
                  cycles / self._sys_clk_freq * 1e3,
                  self._sys_clk_freq / cycles * 60)
        return cycles

    async def _read_packet(self):
        data     = await self.lower.read(254)
        trailer, = await self.lower.read(1)
        if trailer != TLR_ERROR:
            return data[:trailer]

    async def read_track_raw(self, redundancy=1):
        self._log("read track raw")
        index = 0
        data  = bytearray()
        await self.lower.write([CMD_READ_RAW, redundancy])
        while True:
            packet = await self._read_packet()
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
    def cycle(bitstream):
        yield from bitstream()
        yield from bitstream()

    def lock(self, bitstream):
        cur_bit   = 0
        bit_tol   = 12
        bit_min   = 16
        bit_time  = bit_min
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
            # /¯¯¯\________WWWWWWWWW________WWWWWWWWW_____________...
            # 0000000000111111111122222222223333333333444444444455
            # 0123456789012345678901234567890123456789012345678901...
            # ^ START      ^ WINDOW-NEG     ^ WINDOW-NEG
            #                  ^ WINDOW-EXA     ^ WINDOW-EXA
            #                   ^ WINDOW-POS     ^ WINDOW-POS
            #                      ^ CONTINUE       ^ CONTINUE    ...

            if state == "START":
                if edge:
                    in_phase   = 0
                    bit_time   = bit_min
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
                    if bit_time > bit_min:
                        bit_time  -= 1
                elif window == bit_tol:
                    state      = "WINDOW-EXA"
            elif state == "WINDOW-EXA":
                if edge:
                    if (not locked and window_no in (2, 3) or
                            locked and window_no in (2, 3, 4)):
                        in_phase += 1
                    else:
                        in_phase  = 0
                        if locked:
                            self._log("pll loss =win=%d bit-off=%d", window_no, offset)
                elif window == bit_tol + 1:
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
                elif window == bit_tol + 1 + bit_tol:
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
                if shreg[sync_offset:sync_offset + 16] == [0,1,0,0,0,1,0,0,1,0,0,0,1,0,0,1]:
                    if not synced or sync_offset != 0:
                        self._log("sync=K.A1 chip-off=%d", offset + sync_offset)
                    offset += sync_offset + 16
                    shreg   = shreg[sync_offset + 16:]
                    synced  = True
                    prev    = 1
                    bits    = []
                    yield (1, 0xA1)
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
                        yield (0, sum(bit << (7 - n) for n, bit in enumerate(bits)))
                        bits = []


class MemoryFloppyApplet(GlasgowApplet, name="memory-floppy"):
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
    # The TTL logic is not compatible with revA/B level shifters.
    required_revision = "C0"

    __pins = ("redwc", "drvs", "mote", "dir", "step", "wdata", "wgate", "side1", # out
              "index", "trk00", "wpt", "rdata", "dskchg") # in

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        for pin in cls.__pins:
            access.add_pin_argument(parser, pin, default=True)

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        self._sys_clk_freq = target.sys_clk_freq
        iface.add_subtarget(ShugartFloppySubtarget(
            pins=iface.get_pads(pins=self.__pins, args=args),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(auto_flush=False),
            sys_freq=target.sys_clk_freq,
        ))

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        return ShugartFloppyInterface(iface, self.logger, self._sys_clk_freq)

    @classmethod
    def add_interact_arguments(cls, parser):
        # TODO(py3.7): add required=True
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION")

        p_read_raw = p_operation.add_parser(
            "read-raw", help="read raw track data")
        p_read_raw.add_argument(
            "-R", "--redundancy", metavar="N", type=int, default=1,
            help="read track N+1 times (i.e. with N redundant copies)")
        p_read_raw.add_argument(
            "file", metavar="RAW-FILE", type=argparse.FileType("wb"),
            help="write raw image to RAW-FILE")
        p_read_raw.add_argument(
            "first", metavar="FIRST", type=int,
            help="read from track FIRST")
        p_read_raw.add_argument(
            "last", metavar="LAST", type=int,
            help="read until track LAST (inclusive; 161 for most 3.5\" disks)")

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
        await floppy_iface.measure_track()

        try:
            if args.operation == "read-raw":
                for track in range(args.first, args.last + 1):
                    await floppy_iface.seek_track(track)
                    data = await floppy_iface.read_track_raw(redundancy=args.redundancy)
                    args.file.write(struct.pack(">BBL", track & 1, track >> 1, len(data)))
                    args.file.write(data)
                    args.file.flush()

            if args.operation == "read-track":
                await floppy_iface.seek_track(args.track)
                bytestream = await floppy_iface.read_track_raw()
                mfm        = SoftwareMFMDecoder(self.logger)
                datastream = mfm.demodulate(mfm.lock(itertools.cycle(mfm.bits(bytestream))))
                for comma, data in itertools.islice(datastream, 10):
                    if comma:
                        print("K.%02X" % data, end=" ")
                    else:
                        print("%02X" % data, end=" ")
                print()

            if args.operation == "test-pll":
                await floppy_iface.seek_track(args.track)
                bytestream = await floppy_iface.read_track_raw()
                mfm        = SoftwareMFMDecoder(self.logger)
                bitstream  = list(mfm.bits(bytestream)) * 2

                lock_times = []
                bit_times  = []
                try:
                    for _ in range(args.count):
                        start = random.randint(0, len(bitstream) // 2)
                        next(mfm.lock(bitstream[start:]))
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

class MemoryFloppyAppletTool(GlasgowAppletTool, applet=MemoryFloppyApplet):
    help = "manipulate raw disk images captured from IBM/Shugart floppy drives"
    description = """
    Dissect raw disk images (i.e. RDATA samples) and extract MFM-encoded sectors into linear
    disk images.

    Any errors during extraction are logged, the linear image is filled and padded to
    the necessary geometry, and all areas that were not recovered from the raw image are filled
    with the following repeating byte patterns:

        * <FA11> for sectors completely missing from the raw image;
        * <DEAD> for sectors whose header was found but data was corrupted;
        * <BAAD> for sectors that were marked as "deleted" (i.e. bad blocks) in the raw image,
          and no decoding was attempted.

    ("Deleted" sectors are not currently recognized.)
    """

    @classmethod
    def add_arguments(cls, parser):
        # TODO(py3.7): add required=True
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION")

        p_index = p_operation.add_parser(
            "index", help="discover and verify raw disk image contents and MFM sectors")
        p_index.add_argument(
            "-n", "--no-decode", action="store_true", default=False,
            help="do not attempt to decode track data, just index tracks (much faster)")
        p_index.add_argument(
            "file", metavar="RAW-FILE", type=argparse.FileType("rb"),
            help="read raw disk image from RAW-FILE")

        p_raw2img = p_operation.add_parser(
            "raw2img", help="extract raw disk images into linear disk images")
        p_raw2img.add_argument(
            "-s", "--sector-size", metavar="BYTES", type=int, default=512,
            help="amount of bytes per sector (~always the default: %(default)s)")
        p_raw2img.add_argument(
            "-t", "--sectors-per-track", metavar="COUNT", type=int, required=True,
            help="amount of sectors per track (9 for DD, 18 for HD, ...)")
        p_raw2img.add_argument(
            "raw_file", metavar="RAW-FILE", type=argparse.FileType("rb"),
            help="read raw disk image from RAW-FILE")
        p_raw2img.add_argument(
            "linear_file", metavar="LINEAR-FILE", type=argparse.FileType("wb"),
            help="write linear disk image to LINEAR-FILE")

    crc_mfm = staticmethod(crcmod.mkCrcFun(0x11021, initCrc=0xffff, rev=False))

    def iter_tracks(self, file):
        while True:
            header = file.read(struct.calcsize(">BBL"))
            if header == b"": break
            head, track, size = struct.unpack(">BBL", header)
            yield track, head, file.read(size)

    def iter_mfm_sectors(self, symbstream, verbose=False):
        state   = "IDLE"
        count   = 0
        data    = bytearray()
        header  = None
        size    = None
        for offset, (comma, symbol) in enumerate(symbstream):
            self.logger.trace("state=%s sym=%s.%02X",
                              state, "K" if comma else "D", symbol)

            if comma and symbol == 0xA1:
                if state == "IDLE":
                    data.clear()
                    count  = 1
                    state  = "SYNC"
                elif state == "SYNC":
                    count += 1
                else:
                    self.logger.warning("desync sym-off=%d state=%s sym=K.A1",
                                        offset, state)
                    data.clear()
                    count  = 1
                    state  = "SYNC"

                data.append(symbol)
                continue

            data.append(symbol)
            if state == "IDLE":
                continue
            elif state == "SYNC":
                if count < 3:
                    self.logger.warning("early data sym-off=%d sync-n=%d",
                                        offset, count)
                if symbol == 0xFE:
                    count = 6 # CYL+HD+SEC+NO+CRCH/L
                    state = "FORMAT"
                elif symbol == 0xFB:
                    if header is None:
                        self.logger.warning("spurious sector sym-off=%d",
                                            offset)
                    else:
                        count = 2 + size # DATA+CRCH/L
                        state = "SECTOR"
                else:
                    self.logger.warning("unknown mark sym-off=%d type=%02X",
                                        offset, symbol)
                    state = "IDLE"
                continue

            if state in ("FORMAT", "SECTOR"):
                count -= 1
                if count == 0 and self.crc_mfm(data) != 0:
                    self.logger.warning("wrong checksum sym-off=%d state=%s type=%02X",
                                        offset, state, data[2])
                    state = "IDLE"
                    continue

            if count == 0 and state == "FORMAT":
                cyl, hd, sec, no = struct.unpack(">BBBB", data[4:-2])
                size = 1 << (7 + no)

                header = cyl, hd, sec
                self.logger.log(logging.INFO if verbose else logging.DEBUG,
                                "  header cyl=%2d hd=%d sec=%2d size=%d",
                                *header, size)

            if count == 0 and state == "SECTOR":
                yield (header, data[4:-2])

                header = None

            if count == 0:
                state = "IDLE"

    async def run(self, args):
        if args.operation == "index":
            for head, track, bytestream in self.iter_tracks(args.file):
                self.logger.info("track %d head %d: %d samples captured",
                                 head, track, len(bytestream) * 8)
                if args.no_decode:
                    continue

                mfm        = SoftwareMFMDecoder(self.logger)
                symbstream = mfm.demodulate(mfm.lock(mfm.bits(bytestream)))
                for _ in self.iter_mfm_sectors(symbstream, verbose=True):
                    pass

        if args.operation == "raw2img":
            image    = bytearray()
            next_lba = 0
            missing  = 0

            try:
                curr_lba = 0
                for head, track, bytestream in self.iter_tracks(args.raw_file):
                    self.logger.info("processing track %d head %d",
                                     head, track)

                    mfm        = SoftwareMFMDecoder(self.logger)
                    symbstream = mfm.demodulate(mfm.lock(mfm.bits(bytestream)))

                    sectors    = {}
                    seen       = set()
                    for (cyl, hd, sec), data in self.iter_mfm_sectors(symbstream):
                        if sec not in range(1, 1 + args.sectors_per_track):
                            self.logger.error("sector at C/H/S %d/%d/%d overflows track geometry "
                                              "(%d sectors per track)",
                                              cyl, hd, sec, args.sectors_per_track)
                            continue

                        if sec in seen:
                            # Due to read redundancy, seeing this is not an error in general,
                            # though this could be a sign of a strange invalid track. We do not
                            # currently aim to handle these cases, so just ignore them.
                            self.logger.debug("duplicate sector at C/H/S %d/%d/%d",
                                              cyl, hd, sec)
                            continue
                        else:
                            seen.add(sec)

                        lba = ((cyl << 1) + hd) * args.sectors_per_track + (sec - 1)
                        self.logger.info("  mapping C/H/S %d/%d/%d to LBA %d",
                                         cyl, hd, sec, lba)

                        if len(data) != args.sector_size:
                            self.logger.error("sector at LBA %d has size %d (%d expected)",
                                              lba, len(data), args.sector_size)
                        elif lba in sectors:
                            self.logger.error("duplicate sector at LBA %d",
                                              lba)
                        else:
                            sectors[lba] = data

                        if len(seen) == args.sectors_per_track:
                            self.logger.debug("found all sectors on this track")
                            break

                    last_lba = curr_lba + args.sectors_per_track
                    while curr_lba < last_lba:
                        if curr_lba in sectors:
                            args.linear_file.seek(curr_lba * args.sector_size)
                            args.linear_file.write(sectors[curr_lba])
                        else:
                            missing  += 1
                            args.linear_file.seek(curr_lba * args.sector_size)
                            args.linear_file.write(b"\xFA\x11" * (args.sector_size // 2))
                            self.logger.error("sector at LBA %d missing",
                                              curr_lba)
                        curr_lba += 1
            finally:
                self.logger.info("%d/%d sectors missing", missing, last_lba)

# -------------------------------------------------------------------------------------------------

class MemoryFloppyAppletTestCase(GlasgowAppletTestCase, applet=MemoryFloppyApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
