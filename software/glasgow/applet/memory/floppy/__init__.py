# Ref: INTEL 82077AA CHMOS SINGLE-CHIP FLOPPY DISK CONTROLLER
# Accession: G00032
# Ref: SAMSUNG OEM MANUAL SFD-321B 3.5inch DUAL DENSITY MICRO FLOPPY DISK DRIVE SPECIFICATIONS
# Accession: G00033

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
from nmigen.compat import *
from nmigen.compat.genlib.cdc import MultiReg

from ....gateware.pads import *
from ... import *
from .mfm import *


class ShugartFloppyBus(Module):
    def __init__(self, pins):
        self.redwc  = Signal()
        self.index  = Signal()
        self.drvs   = Signal(2)
        self.mote   = Signal(2)
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
        self.rdata_e = Signal()

        ###

        self.comb += [
            pins.redwc_t.oe.eq(1),
            pins.redwc_t.o.eq(~self.redwc),
            pins.motea_t.oe.eq(1),
            pins.motea_t.o.eq(~self.mote[0]),
            pins.drvsb_t.oe.eq(1),
            pins.drvsb_t.o.eq(~self.drvs[1]),
            pins.drvsa_t.oe.eq(1),
            pins.drvsa_t.o.eq(~self.drvs[0]),
            pins.moteb_t.oe.eq(1),
            pins.moteb_t.o.eq(~self.mote[1]),
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

        rdata_r = Signal()
        self.sync += rdata_r.eq(self.rdata)
        self.comb += self.rdata_e.eq(~rdata_r & self.rdata)


CMD_SYNC  = 0x00
CMD_START = 0x01
CMD_STOP  = 0x02
CMD_TRK0  = 0x03
CMD_TRK   = 0x04
CMD_MEAS  = 0x05
CMD_READ_RAW = 0x06


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

        self.submodules.fsm = FSM(reset_state="RECV-COMMAND")
        self.fsm.act("RECV-COMMAND",
            in_fifo.flush.eq(1),
            If(timer == 0,
                If(out_fifo.readable,
                    out_fifo.re.eq(1),
                    NextValue(cmd, out_fifo.dout),
                    NextState("PARSE-COMMAND")
                )
            ).Else(
                NextValue(timer, timer - 1)
            )
        )
        self.fsm.act("PARSE-COMMAND",
            If(cmd == CMD_SYNC,
                If(in_fifo.writable,
                    in_fifo.we.eq(1),
                    NextState("RECV-COMMAND")
                )
            ).Elif(cmd == CMD_START,
                NextValue(bus.drvs, 0b11),
                NextValue(bus.mote, 0b11),
                NextValue(timer, spin_up_cyc - 1),
                NextState("RECV-COMMAND")
            ).Elif(cmd == CMD_STOP,
                NextValue(bus.drvs, 0),
                NextValue(bus.mote, 0),
                NextState("RECV-COMMAND")
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

        # === Track positioning
        self.fsm.act("TRACK-STEP",
            If(timer == 0,
                If((cmd == CMD_TRK0) & bus.trk00,
                    NextValue(cur_trk, 0),
                    NextValue(timer, settle_cyc - 1),
                    NextState("RECV-COMMAND")
                ).Elif((cmd == CMD_TRK) & (cur_trk == tgt_trk),
                    NextValue(timer, settle_cyc - 1),
                    NextState("RECV-COMMAND")
                ).Else(
                    NextValue(cur_trk, Mux(bus.dir, cur_trk + 1, cur_trk - 1)),
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

        # === Speed measurement
        self.fsm.act("MEASURE",
            If(bus.index_e,
                NextState("MEASURE-SEND-0")
            ).Else(
                NextValue(trk_len, trk_len + 1),
            )
        )
        for n in range(3):
            self.fsm.act("MEASURE-SEND-%d" % n,
                If(in_fifo.writable,
                    in_fifo.we.eq(1),
                    in_fifo.din.eq(trk_len[8 * n:]),
                    NextState("MEASURE-SEND-%d" % (n + 1) if n < 2 else "RECV-COMMAND")
                )
            )

        # === Raw data reads
        rdata_cyc = Signal(8)
        rdata_ovf = Signal()

        self.fsm.act("READ-RAW-SYNC",
            If(bus.index_e,
                NextValue(rdata_ovf, 0),
                NextState("READ-RAW-SEND-DATA")
            )
        )
        self.fsm.act("READ-RAW-SEND-DATA",
            If(bus.index_e,
                NextValue(cur_rot, cur_rot + 1),
                If(cur_rot == tgt_rot,
                    NextState("READ-RAW-SEND-TRAILER")
                ),
            ),
            NextValue(rdata_cyc, Mux(bus.rdata_e, 0, rdata_cyc + 1)),
            If(bus.rdata_e | (rdata_cyc == 0xfd),
                in_fifo.din.eq(rdata_cyc),
                in_fifo.we.eq(1),
                If(~in_fifo.writable,
                    NextValue(rdata_ovf, 1),
                    NextState("READ-RAW-SEND-TRAILER")
                )
            ),
        )
        self.fsm.act("READ-RAW-SEND-TRAILER",
            If(in_fifo.writable,
                in_fifo.we.eq(1),
                in_fifo.din.eq(0xfe | rdata_ovf),
                NextState("RECV-COMMAND")
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

    async def read_track_raw(self, redundancy=1):
        self._log("read track raw")
        data  = []
        await self.lower.write([CMD_READ_RAW, redundancy])
        while True:
            packet = await self.lower.read()
            if packet[-1] == 0xff:
                raise GlasgowAppletError("FIFO overflow while reading track")
            elif packet[-1] == 0xfe:
                data.append(packet[:-1])
                return b"".join(data)
            else:
                data.append(packet)


class MemoryFloppyApplet(GlasgowApplet, name="memory-floppy"):
    preview = True
    logger = logging.getLogger(__name__)
    help = "read and write disks using IBM/Shugart floppy drives"
    description = """
    Read and write floppy disks using IBM/Shugart floppy drive interface. This is the interface
    used in common IBM/PC 5.25" and 3.5" floppy drives, as well as Amiga, various synthesizers,
    and so on.

    NOTE: Writes are not currently supported.

    The default applet pinout uses a sequential assignment of every pin except REDWC. This allows
    splitting the FDC ribbon cable such that two 20-pin IDC connectors may be crimped onto it
    for easy connection as follows:

        * Conductors 1-7 are unused (cut off the cable);
        * Conductors 8-23 are crimped to connect to pins 3-18 of connector A;
        * Conductors 24-34 are crimped to connect to pins 3-14 of connector B.

    If desired, conductors 2-3 may be crimped to connect to pins 15-16 of connector B to connect
    the REDWC pin as well.
    """
    # The TTL logic is not compatible with revA/B level shifters, and would require external
    # buffering.
    required_revision = "C0"

    __pins = ("index", "motea", "drvsb", "drvsa", "moteb", "dir", "step", "wdata", "wgate",
              "trk00", "wpt", "rdata", "side1", "dskchg", "redwc")

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

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)

        parser.add_argument(
            "--pulls", default=False, action="store_true",
            help="enable internal bus termination")

    async def run(self, device, args):
        pulls = set()
        if args.pulls:
            pulls = {args.pin_index, args.pin_trk00, args.pin_wpt, args.pin_rdata, args.pin_dskchg}
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args,
                                                           pull_high=pulls)
        return ShugartFloppyInterface(iface, self.logger, self._sys_clk_freq)

    @classmethod
    def add_interact_arguments(cls, parser):
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

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
            help="read until track LAST (inclusive; 159 for most 3.5\" disks)")

    async def interact(self, device, args, floppy_iface):
        self.logger.info("starting up the drive")
        await floppy_iface.start()
        await floppy_iface.measure_track()

        try:
            if args.operation == "read-raw":
                for track in range(args.first, args.last + 1):
                    cylinder, head = track >> 1, track & 1
                    self.logger.info("reading C/H %d/%d", cylinder, head)

                    await floppy_iface.seek_track(track)
                    data = await floppy_iface.read_track_raw(redundancy=args.redundancy)
                    args.file.write(struct.pack(">LBB", len(data), cylinder, head))
                    args.file.write(data)
                    args.file.flush()

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

    _timebase = 1e6 / 48e6

    @classmethod
    def add_arguments(cls, parser):
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

        cls._add_histogram_arguments(p_operation)
        cls._add_train_arguments(p_operation)
        cls._add_index_arguments(p_operation)
        cls._add_raw2img_arguments(p_operation)

    async def run(self, args):
        if args.operation == "histogram":
            self._run_histogram(args)
        if args.operation == "train":
            self._run_train(args)
        if args.operation == "index":
            self._run_index(args)
        if args.operation == "raw2img":
            self._run_raw2img(args)

    @classmethod
    def _add_histogram_arguments(self, p_operation):
        p_histogram = p_operation.add_parser(
            "histogram", help="plot distribution of transition periods")
        p_histogram.add_argument(
            "file", metavar="RAW-FILE", type=argparse.FileType("rb"),
            help="read raw disk image from RAW-FILE")
        p_histogram.add_argument(
            "cylinders", metavar="CYLINDER", type=int, nargs="*", default=[0, 1, 10, 30, 50, 70],
            help="plot data for each CYLINDER read by one head (deafult: %(default)s)")
        p_histogram.add_argument(
            "--head", metavar="HEAD", type=int, action="append",
            help="consider only head HEAD (one of: %(choices)s, default: all)")
        p_histogram.add_argument(
            "--range", metavar="MAX", type=int, default=10,
            help="consider only edges in [0, MAX] range, in microseconds")

    def _run_histogram(self, args):
        import numpy as np
        import matplotlib.pyplot as plt

        data = []
        labels = []
        for cylinder, head, bytestream in self.iter_tracks(args.file):
            if cylinder not in args.cylinders or args.head is not None and head not in args.head:
                continue
            self.logger.info("processing C/H %d/%d",
                             cylinder, head)

            mfm = SoftwareMFMDecoder(self.logger)
            data.append(np.array(list(mfm.edges(bytestream))) * self._timebase)
            labels.append("cylinder {}, head {}".format(cylinder, head))

        fig, ax = plt.subplots()
        fig.suptitle("Domain size histogram for {} (heads: {})"
                     .format(args.file.name,
                             ", ".join(str(h) for h in args.head) if args.head else "all"))
        ax.hist(data,
            bins     = [x * self._timebase for x in range(600)],
            label    = labels,
            alpha    = 0.5,
            histtype = "step")
        ax.set_xlabel("domain size (µs)")
        ax.set_ylabel("count")
        ax.set_yscale("log")
        ax.set_xlim(0, args.range)
        ax.grid()
        ax.legend()

        plt.show()

    @classmethod
    def _add_train_arguments(self, p_operation):
        p_train = p_operation.add_parser(
            "train", help="train PLL and collect statistics")
        p_train.add_argument(
            "--ui", metavar="PERIOD", type=float, required=True,
            help="set UI length to PERIOD, in microseconds")
        p_train.add_argument(
            "file", metavar="RAW-FILE", type=argparse.FileType("rb"),
            help="read raw disk image from RAW-FILE")
        p_train.add_argument(
            "track", metavar="TRACK", type=int,
            help="use track number TRACK")
        p_train.add_argument(
            "offset", metavar="OFFSET", type=int, nargs="?",
            help="skip first OFFSET data edges (default: don't skip)")
        p_train.add_argument(
            "limit", metavar="LIMIT", type=int, nargs="?",
            help="only consider first LIMIT data edges (default: consider all)")

    def _run_train(self, args):
        import numpy as np
        import matplotlib.pyplot as plt

        for cylinder, head, bytestream in self.iter_tracks(args.file):
            if (cylinder << 1) | head != args.track:
                continue
            self.logger.info("processing C/H %d/%d",
                             cylinder, head)

            if args.offset is not None or args.limit is not None:
                bytestream = bytestream[args.offset:args.offset + args.limit]
            mfm = SoftwareMFMDecoder(self.logger)

            bits    = list(mfm.bits(bytestream))
            edges   = list(mfm.edges(bytestream))
            domains = list(mfm.domains(bits))
            plldata = list(mfm.lock(bits, debug=True))

            ui_cycles = args.ui / self._timebase

            ui_time = 0
            ui_times, ui_lengths = [], []
            for edge in edges:
                ui_times.append(ui_time * self._timebase)
                ui_lengths.append(edge / ui_cycles)
                ui_time += edge

            fig, (ax1, ax2, ax3) = plt.subplots(3, 1, sharex=True)
            fig.suptitle("PLL debug output for {}, track {}, range {}+{}"
                         .format(args.file.name, args.track, args.offset or 0, len(bytestream)))
            times = np.arange(0, len(bits)) * self._timebase

            ax1.plot(times, np.array([x[1] / ui_cycles for x in plldata]),
                     color="green", label="NCO period", linewidth=1)
            ax1.axhline(y=ui_cycles * self._timebase,
                        color="gray")
            ax1.set_ylim(0)
            ax1.set_ylabel("UI")
            ax1.grid()
            ax1.legend(loc="upper right")

            ax2.plot(times, np.array([x[2] / ui_cycles for x in plldata]),
                     label="phase error", linewidth=1)
            ax2.set_ylim(-0.5, 0.5)
            ax2.set_yticks([-0.5 + 0.2 * x for x in range(6)])
            ax2.set_ylabel("UI")
            ax2.grid()
            ax2.legend(loc="upper right")

            ax3.plot(ui_times, ui_lengths, "+",
                     color="red", label="edge-to-edge time", linewidth=1)
            ax3.set_xlabel("us")
            ax3.set_ylim(1, 6)
            ax3.set_yticks(range(1, 7))
            ax3.set_ylabel("UI")
            ax3.grid()
            ax3.legend(loc="upper right")

            plt.show()

    @classmethod
    def _add_index_arguments(self, p_operation):
        p_index = p_operation.add_parser(
            "index", help="discover and verify raw disk image contents and MFM sectors")
        p_index.add_argument(
            "-n", "--no-decode", action="store_true", default=False,
            help="do not attempt to decode track data, just index tracks (much faster)")
        p_index.add_argument(
            "--ignore-data-crc", action="store_true", default=False,
            help="do not reject sector data with incorrect CRC")
        p_index.add_argument(
            "file", metavar="RAW-FILE", type=argparse.FileType("rb"),
            help="read raw disk image from RAW-FILE")

    def _run_index(self, args):
        for cylinder, head, bytestream in self.iter_tracks(args.file):
            self.logger.info("indexing C/H %d/%d: %d edges captured",
                             cylinder, head, len(bytestream))
            if args.no_decode:
                continue

            mfm        = SoftwareMFMDecoder(self.logger)
            symbstream = mfm.demodulate(mfm.lock(mfm.bits(bytestream)))
            for _ in self.iter_mfm_sectors(symbstream, verbose=True,
                    ignore_data_crc=args.ignore_data_crc):
                pass

    @classmethod
    def _add_raw2img_arguments(self, p_operation):
        p_raw2img = p_operation.add_parser(
            "raw2img", help="extract raw disk images into linear disk images")
        p_raw2img.add_argument(
            "--ignore-data-crc", action="store_true", default=False,
            help="do not reject sector data with incorrect CRC")
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

    def _run_raw2img(self, args):
        image    = bytearray()
        next_lba = 0
        missing  = 0

        try:
            curr_lba = 0
            for cylinder, head, bytestream in self.iter_tracks(args.raw_file):
                self.logger.info("processing C/H %d/%d", cylinder, head)

                mfm        = SoftwareMFMDecoder(self.logger)
                symbstream = mfm.demodulate(mfm.lock(mfm.bits(bytestream)))

                sectors    = {}
                seen       = set()
                for (cyl, hd, sec), data in self.iter_mfm_sectors(symbstream,
                        ignore_data_crc=args.ignore_data_crc):
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
                        args.linear_file.write(b"\x00\x00" * (args.sector_size // 2))
                        self.logger.error("sector at LBA %d missing",
                                          curr_lba)
                    curr_lba += 1
        finally:
            self.logger.info("%d/%d sectors missing", missing, last_lba)

    def iter_tracks(self, file):
        while True:
            header = file.read(struct.calcsize(">LBB"))
            if header == b"": break
            size, cylinder, head = struct.unpack(">LBB", header)
            yield cylinder, head, file.read(size)

    crc_mfm = staticmethod(crcmod.mkCrcFun(0x11021, initCrc=0xffff, rev=False))

    def iter_mfm_sectors(self, symbstream, *, verbose=False, ignore_data_crc=False):
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
                    self.logger.error("desync sym-off=%d state=%s sym=K.A1",
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
                    count = 4 + 2 # CYL+HD+SEC+NO+CRCH/L
                    state = "FORMAT"
                elif symbol == 0xFB:
                    if header is None:
                        self.logger.warning("spurious sector sym-off=%d",
                                            offset)
                    else:
                        count = size + 2 # DATA+CRCH/L
                        state = "SECTOR"
                else:
                    self.logger.warning("unknown mark sym-off=%d type=%02X",
                                        offset, symbol)
                    state = "IDLE"
                continue

            if state in ("FORMAT", "SECTOR"):
                count -= 1
                if count == 0 and self.crc_mfm(data) != 0:
                    if state == "SECTOR" and ignore_data_crc:
                        fail_crc = False
                    else:
                        fail_crc = True
                    self.logger.log(logging.ERROR if fail_crc else logging.WARN,
                                    "wrong checksum sym-off=%d state=%s type=%02X",
                                    offset, state, data[2])
                    if fail_crc:
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

# -------------------------------------------------------------------------------------------------

class MemoryFloppyAppletTestCase(GlasgowAppletTestCase, applet=MemoryFloppyApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
