# Ref: Using the XC9500/XL/XV JTAG Boundary Scan Interface
# Document Number: XAPP069
# Accession: G00014
# Ref: XC95288XL High Performance CPLD
# Document Number: DS055
# Accession: G00081
# Ref: XC95144XL High Performance CPLD
# Document Number: DS056
# Accession: G00082
# Ref: XC9572XL BSDL files
# Accession: G00015
# Ref: black box reverse engineering of XC9572XL by whitequark

# JTAG IR commands
# ----------------
#
# Beyond the documentation in XAPP069, observations given the information from BSDL files:
#
#   * ISPEX (also called CONLD) selects BYPASS[1].
#   * ISPEN, ISPENC select ISPENABLE[6].
#   * FERASE, FBULK, FBLANK select ISADDRESS[18].
#   * FPGMI, FVFYI select ISDATA[34].
#   * FPGM, FVFY select ISCONFIGURATION[50].
#   * ISPENC is encoded like a "command variant" of ISPEN (differs by LSB). Not documented,
#     function unclear.
#   * FBLANK is encoded rather unlike FERASE and FBULK. Not documented, function unclear.
#
# Functional observations from black-box hardware reverse engineering:
#   * There is no need to shift DR after selecting ISPENABLE. ISPENABLE is shifted and completely
#     ignored by SVF files.
#   * The general format of DR seems to be valid bit, strobe bit, then payload. FPGMI, FVFYI
#     use 32-bit data as payload; FERASE, FBULK, FBLANK use 16-bit address as payload;
#     FPGM, FVFY use a concatenated data plus address payload.
#
# Functional observations from ISE SVF files:
#   * Check for Read/Write Protection appears to use the value captured in Capture-IR.
#     It appears that one of the three MSBs will be set in a protected device.
#   * FVFY uses strobe bit as word read strobe. FPGM uses strobe bit as block (see below on blocks)
#     write strobe; an entire block is loaded into a buffer first, and then written in one cycle.
#   * Check for FBULK and FPGM success (and probably FERASE success too) is a check for valid bit
#     being high and strobe bit being low.
#   * FBULK needs 200 ms / 200k cycles, and FPGM w/ strobe needs 20 ms / 20 k cycles in Run-Test.
#
# Bitstream structure
# -------------------
#
# From the Xilinx JED files, the XC9572XL bitstream has 46656 individual fuse bits. The bitstream
# JED file uses two type of JED L fields, we will call them "4x8" L-field:
#    L0000000 00000000 00000000 00000000 00000000*
# and "4x6" L-field:
#    L0000288 000000 000000 000000 000000*
# The L-fields are organized into blocks of 15 L-fields, made from 9 4x8 L-fields followed
# by 6 4x6 L-fields. The entire XC9572XL bitstream consists of exactly 108 of such blocks.
# This can be verified by matching the JED file against a regexp:
#    (L\d{7}( [01]{8}){4}\*\n){9}(L\d{7}( [01]{6}){4}\*\n){6}
# There are 1620 L-fields in total.
#
# From reverse engineering, the XC9572XL bitstream is organized as 1620x32. This is determined
# because after 1620 reads from FVFYI, the bitstream starts to repeat.
#
# Conjecture (high confidence): each JED L-field maps to exactly one chip bitstream word.
#
# On 0th read, the first 2 words on my XC9572XL read as:
#   11001001110010011100100111001001
#   01001010010010100000000101001010
# and the next 34 words (for 36 words total) read as zero.
#
# On 1th and further reads, the first 20 words read as:
#   00000000000000000000000000000000
#   00000000000110000000000000000000
#   00000000001000000000000000000000
#   00000000000000000000000000000000
#   00000000000000000000000000000000
#   00000000000100000000000000011010
#   00000000001000000000000000000000
#   00000000000000010000000000000000
#   00000000001000000000000000000000
#   00000000000000000000000000000000
#   00000000001000000000000000001011
#   00000000000000000000000000000000
#   00000000001000000000000000000000
#   00000000000100000000000000000000
#   00000000000000000000000000000000
#   00000000000010000000000000001001
#   00000000000000000000000000000000
#   00000000000000000010000000000000
#   00000000001000000000000000000000
#   00000000001000000000000000000000
# and the next 14 words (for 36 words total) read as zero. The 20 different words from 1th read
# or any non-degenerate subset thereof do not appear in that sequence anywhere else in
# the bitstream.
#
# Conjecture (medium confidence): first several FVFYI reads (at least 20) actually happen from
# some sort of auxiliary memory. Moreover, these reads are not *prefixed* to the actual bitstream,
# but in fact *replace* a part of the actual bistream.
#
# Looking only at words that correspond to 6x4 L-fields, these words appear like this:
#   00010111000000000000000000000000
#   00010110000000100000000000000000
#   00010110001000000010000000010000
#   00000000001000000011000000000000
#   00000000000010000000000000001001
#   XX------XX------XX------XX------
#
# Conjecture (high confidence): 6x4 L-field is expanded into a 32-bit word by padding each
# 6-bit field part up to a 8-bit word part by adding zeroes as MSB. All words appear to separate
# into 4 8-bit chunks.
#
# JED address to word address mapping
# -----------------------------------
#
# Each JED block is 432-bit, i.e. the padding bits are not encoded. This makes mapping from
# JED blocks to bitstream words nontrivial. The mapping algorithm from field-aligned JED fuse
# addresses to word addresses is as follows:
#
#   block_num = jed_address // 432
#   block_bit = jed_address % 432
#   word_addr = block_num * 15
#   if block_bit < 9 * 32:
#     word_addr += block_bit // 32
#   else:
#     word_addr += 9 + (block_bit - 9 * 32) // 24
#
# Bitstream address structure
# ---------------------------
#
# While FVFYI reads out words (apparently) exactly as they are laid out in bitstream, FVFY and
# FPGM have a more complicated addressing scheme. This is likely because the blocks are not
# made from a power-of-2 amount of words, and the developers of the CPLD wanted an addressing
# scheme that has a direct relationship between address lines and words.
#
# Based on ISE SVF files, it is clear that each block (15 words) occupies 32 sequential addresses.
# The words inside a block are mapped to addresses as follows:
#     0->N+ 0   1->N+ 1   2->N+ 2   3->N+ 3   4->N+ 4
#     5->N+ 8   6->N+ 9   7->N+10   8->N+11   9->N+12
#    10->N+16  11->N+17  12->N+18  13->N+19  14->N+20
#
# Conjecture (high confidence): each block occupies 32 words of address space, split into 4
# groups of 8 words of address space. Of each group, only 5 first words are allocated.
#
# Additionally, based on SVF files and readout, it appears that the first 3 groups are written
# during flashing, but the 4th group is hardcoded, and points to some sort of identification
# or synchronization registers, laid out as follows:
#    SA->N+24  SB->N+25  SZ->N+26  SZ->N+27  SZ->N+27
# where:
#    SA=11001001110010011100100111001001 0x93939393
#    SB=01001010010010100000000101001010 0x52528052
#    SZ=00000000000000000000000000000000
#
# The SVF files do not verify these words.
#
# Revisiting earlier conjecture, it looks like with FVFYI command, the internal address counter
# starts at offset 24 and reads the 5-word 4th group as well. However, after that, it continues
# to read an entire 15-word empty block (i.e., FVFYI effectively starts with a 20-word padding)
# and then continues to read the first three groups of every block in sequence.
#
# Based on functional observation, FVFY sets the address counter used by FVFYI, and this can
# be used to avoid reading any of the "padding" with FVFYI.
#
# Word address to FPGM/FVFY address mapping
# -----------------------------------------
#
# The mapping algorithm from word address to FPGM/FVFY (device) address is as follows:
#
#   block_num = word_addr // 15
#   block_off = word_addr % 15
#   dev_addr  = 32 * block_num + 8 * (block_off // 5) + block_off % 5
#
# Bitstream encoding of USERCODE
# ------------------------------
#
# Comparing JED files for devices with USERCODE=0x30303030 (---) versus USERCODE=0xaaaaaaaa (+++):
#
#   +L0002592 00000010 00000000 00000000 00000000*
#   +L0002624 00000010 00000000 00000000 00000000*
#   +L0002656 00000010 00000000 00000000 00000000*
#   +L0002688 00000010 00000000 00000000 00000000*
#   +L0002720 00000010 00000000 00000000 00000000*
#   +L0002752 00000010 00000000 00000000 00000000*
#   +L0002784 00000010 00000000 00000000 00000000*
#   +L0002816 00000010 00000000 00000000 00000000*
#   +L0003024 00000010 00000000 00000000 00000000*
#   +L0003056 00000010 00000000 00000000 00000000*
#   +L0003088 00000010 00000000 00000000 00000000*
#   +L0003120 00000010 00000000 00000000 00000000*
#   +L0003152 00000010 00000000 00000000 00000000*
#   +L0003184 00000010 00000000 00000000 00000000*
#   +L0003216 00000010 00000000 00000000 00000000*
#   +L0003248 00000010 00000000 00000000 00000000*
#   -L0002592 00000000 00000000 00000000 00000000*
#   -L0002624 00000011 00000000 00000000 00000000*
#   -L0002656 00000000 00000000 00000000 00000000*
#   -L0002688 00000000 00000000 00000000 00000000*
#   -L0002720 00000000 00000000 00000000 00000000*
#   -L0002752 00000011 00000000 00000000 00000000*
#   -L0002784 00000000 00000000 00000000 00000000*
#   -L0002816 00000000 00000000 00000000 00000000*
#   -L0003024 00000000 00000000 00000000 00000000*
#   -L0003056 00000011 00000000 00000000 00000000*
#   -L0003088 00000000 00000000 00000000 00000000*
#   -L0003120 00000000 00000000 00000000 00000000*
#   -L0003152 00000000 00000000 00000000 00000000*
#   -L0003184 00000011 00000000 00000000 00000000*
#   -L0003216 00000000 00000000 00000000 00000000*
#   -L0003248 00000000 00000000 00000000 00000000*
#
# It can be seen that USERCODE is written in the following device words:
#    90,  91,  92,  93,  94,  95,  96,  97,
#   105, 106, 107, 108, 109, 110, 111, 112
#
# It is split into half-nibbles, and written MSB first into bits 6 and 7 of the device words.
#
# Other notes
# -----------
#
# The programming process is not self-timed and requires a clock to be provided in Run-Test/Idle
# state; otherwise programming will fail. Thus, this applet assumes that the number of clock
# cycles, and not the programming time, per se, is critical. This might not be true.
#
# The FPGMI instruction works similarly to FVFYI, but it looks like the counter is only set
# by FPGM in a way that it is reused by FPGMI once FPGM DR is updated once with the strobe bit
# set.

import struct
import logging
import argparse
import math
import re
from enum import Enum, auto

from ....arch.jtag import *
from ....arch.xilinx.xc9500xl import *
from ....support.bits import *
from ....support.logging import *
from ....database.xilinx.xc9500xl import *
from ...interface.jtag_probe import JTAGProbeApplet
from ....protocol.jesd3 import *
from ... import *


class XC9500XLBitstream:
    def __init__(self, device):
        self.device = device
        self.fbs = [
            [
                bytearray(0 for _ in range(BS_COLS))
                for _ in range(BS_ROWS)
            ]
            for _ in range(device.fbs)
        ]

    @classmethod
    def from_fuses(cls, fuses, device):
        self = cls(device)
        total_bits = BS_ROWS * device.fbs * (9 * 8 + 6 * 6)
        if len(fuses) != total_bits:
            raise GlasgowAppletError(
                "JED file does not have the right fuse count (expected %d, got %d)"
                % (total_bits, len(fuses)))
        pos = 0
        for row in range(BS_ROWS):
            for col in range(BS_COLS):
                for fb in range(device.fbs):
                    sz = 8 if col < 9 else 6
                    byte = int(fuses[pos:pos+sz])
                    pos += sz
                    self.fbs[fb][row][col] = byte
        assert pos == total_bits
        return self

    def to_fuses(self):
        fuses = bitarray()
        for row in range(BS_ROWS):
            for col in range(BS_COLS):
                for fb in range(self.device.fbs):
                    sz = 8 if col < 9 else 6
                    fuses += bits(self.fbs[fb][row][col], sz)
        return fuses

    def clear_prot_done(self):
        """Clears the read/write protection and DONE bits from the bitstream."""
        for pbit in [READ_PROT_BIT, WRITE_PROT_BIT]:
            (row, col, bit) = pbit
            for fb in range(self.device.fbs):
                self.fbs[fb][row][col] &= ~(1 << bit)
        if self.device.kind == "xv":
            (fb, row, col, bit) = DONE_BIT
            self.fbs[fb][row][col] &= ~(1 << bit)

    def get_word(self, row, col):
        word = 0
        for fb in range(self.device.fbs):
            word |= self.fbs[fb][row][col] << (fb * 8)
        return word

    def put_word(self, row, col, word):
        for fb in range(self.device.fbs):
            self.fbs[fb][row][col] = (word >> (fb * 8)) & 0xff

    def verify(self, other):
        assert self.device is other.device
        for fb in range(self.device.fbs):
            for row in range(BS_ROWS):
                for col in range(BS_COLS):
                    if self.fbs[fb][row][col] != other.fbs[fb][row][col]:
                        raise GlasgowAppletError(f"bitstream verification failed at FB={fb} row={row} col={col}")


class BlankCheckResult(Enum):
    BLANK = auto()
    PROGRAMMED = auto()
    WRITE_PROTECTED = auto()


class XC9500XLError(GlasgowAppletError):
    pass


class XC9500XLInterface:
    def __init__(self, interface, logger, frequency):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._frequency = frequency

    def _log(self, message, *args):
        self._logger.log(self._level, "XC9500XL: " + message, *args)

    async def identify(self):
        await self.lower.test_reset()
        idcode_bits = await self.lower.read_dr(32)
        idcode = DR_IDCODE.from_bits(idcode_bits)
        self._log("read idcode mfg-id=%03x part-id=%04x",
                  idcode.mfg_id, idcode.part_id)
        device = devices_by_idcode[idcode.mfg_id, idcode.part_id]
        if device is None:
            xc95xx_iface = None
        else:
            xc95xx_iface = XC95xxXLInterface(self.lower, self._logger, self._frequency, device)
        return idcode, device, xc95xx_iface

    async def read_usercode(self):
        await self.lower.write_ir(IR_USERCODE)
        usercode_bits = await self.lower.read_dr(32)
        self._log("read usercode <%s>", dump_bin(usercode_bits))
        return bytes(usercode_bits)[::-1]


class XC95xxXLInterface:
    def __init__(self, interface, logger, frequency, device):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._frequency = frequency
        self.device  = device
        self.DR_ISDATA = DR_ISDATA(device.fbs)
        self.DR_ISCONFIGURATION = DR_ISCONFIGURATION(device.fbs)

    def _time_us(self, time):
        return math.ceil(time * self._frequency / 1_000_000)

    def _log(self, message, *args):
        self._logger.log(self._level, "XC95xxXL: " + message, *args)

    async def programming_enable(self):
        self._log("programming enable")
        await self.lower.write_ir(IR_ISPEN)
        await self.lower.run_test_idle(1)

    async def programming_disable(self):
        self._log("programming disable")
        await self.lower.write_ir(IR_ISPEX)
        await self.lower.run_test_idle(self._time_us(WAIT_ISPEX))
        await self.lower.write_ir(IR_BYPASS)
        await self.lower.run_test_idle(1)

    async def blank_check(self):
        self._log("blank check")
        await self.lower.write_ir(IR_FBLANK)
        isaddr = DR_ISADDRESS(control=CTRL_START, address=0)
        await self.lower.write_dr(isaddr.to_bits())

        await self.lower.run_test_idle(self._time_us(WAIT_BLANK_CHECK))

        isaddr = DR_ISADDRESS(control=CTRL_OK, address=0)
        isaddr_bits = await self.lower.exchange_dr(isaddr.to_bits())
        isaddr = DR_ISADDRESS.from_bits(isaddr_bits)
        if isaddr.control == CTRL_OK:
            return BlankCheckResult.BLANK
        elif isaddr.control == CTRL_START:
            return BlankCheckResult.PROGRAMMED
        elif isaddr.control == CTRL_WPROT:
            return BlankCheckResult.WRITE_PROTECTED
        else:
            raise XC9500XLError(f"blank check failed {isaddr.bits_repr()}")

    async def _dr_isconfiguration(self, control, address, data=0):
        isconf = self.DR_ISCONFIGURATION(control=control, address=address, data=data)
        isconf_bits = await self.lower.exchange_dr(isconf.to_bits())
        isconf = self.DR_ISCONFIGURATION.from_bits(isconf_bits)
        return isconf

    async def _dr_isdata(self, control, data=0):
        isdata = self.DR_ISDATA(control=control, data=data)
        isdata_bits = await self.lower.exchange_dr(isdata.to_bits())
        isdata = self.DR_ISDATA.from_bits(isdata_bits)
        return isdata

    async def read(self, fast=True):
        self._log("device read")
        bs = XC9500XLBitstream(self.device)
        status_bits = await self.lower.exchange_ir(IR_FVFY)
        status = IR_STATUS.from_bits(status_bits)
        if status.read_protect:
            raise XC9500XLError("read failed: device is read protected")

        if fast:
            # Use FVFY just to set the address counter.
            await self._dr_isconfiguration(CTRL_START, 0)
            await self.lower.write_ir(IR_FVFYI)
            for row in range(BS_ROWS):
                for col in range(BS_COLS):
                    await self.lower.run_test_idle(1)
                    last = row == BS_ROWS - 1 and col == BS_COLS - 1
                    res = await self._dr_isdata(CTRL_OK if last else CTRL_START)
                    if res.control != CTRL_OK:
                        raise XC9500XLError(f"fast read failed {res.bits_repr()} at ({row}, {col})")
                    bs.put_word(row, col, res.data)
        else:
            # Use FVFY for all reads.
            prev_row = prev_col = None
            for row in range(BS_ROWS):
                for col in range(BS_COLS):
                    res = await self._dr_isconfiguration(CTRL_START, bs_address(row, col))
                    if prev_row is not None:
                        if res.control != CTRL_OK:
                            raise XC9500XLError(f"read failed {res.bits_repr()} at ({prev_row}, {prev_col})")
                        bs.put_word(prev_row, prev_col, res.data)
                    await self.lower.run_test_idle(1)
                    prev_row = row
                    prev_col = col
            res = await self._dr_isconfiguration(CTRL_OK, 0)
            if res.control != CTRL_OK:
                raise XC9500XLError(f"read failed {res.bits_repr()} at ({prev_row}, {prev_col})")
            bs.put_word(prev_row, prev_col, res.data)

        return bs

    async def bulk_erase(self):
        self._log("bulk erase")
        await self.lower.write_ir(IR_FBULK)
        isaddr = DR_ISADDRESS(control=CTRL_START, address=0)
        await self.lower.write_dr(isaddr.to_bits())

        await self.lower.run_test_idle(self._time_us(WAIT_ERASE))

        isaddr = DR_ISADDRESS(control=CTRL_OK, address=0)
        isaddr_bits = await self.lower.exchange_dr(isaddr.to_bits())
        isaddr = DR_ISADDRESS.from_bits(isaddr_bits)
        if isaddr.control == CTRL_WPROT:
            raise XC9500XLError("bulk erase failed: device is write protected")
        if isaddr.control != CTRL_OK:
            raise XC9500XLError(f"bulk erase failed {isaddr.bits_repr()}")

    async def override_erase(self):
        self._log("override erase")
        await self.lower.write_ir(IR_FERASE)
        isaddr = DR_ISADDRESS(control=CTRL_START, address=ADDR_OVERRIDE_MAGIC)
        await self.lower.write_dr(isaddr.to_bits())

    async def program(self, bs, fast=True):
        self._log("program device")
        if fast:
            # Use FPGM to program first word and set the address counter.
            # Use FPGMI for much faster following writes.
            await self.lower.write_ir(IR_FPGM)
            prev_row = None
            for row in range(BS_ROWS):
                for col in range(BS_COLS):
                    word = bs.get_word(row, col)
                    if row == 0 and col == 0:
                        await self._dr_isconfiguration(
                            CTRL_START if col == BS_COLS - 1 else CTRL_OK,
                            address=bs_address(row, col),
                            data=word)
                        await self.lower.write_ir(IR_FPGMI)
                    else:
                        res = await self._dr_isdata(
                            CTRL_START if col == BS_COLS - 1 else CTRL_OK,
                            data=word)
                        if col == 0 and prev_row is not None:
                            if res.control == CTRL_WPROT:
                                raise XC9500XLError("fast programming failed: device is write protected")
                            elif res.control != CTRL_OK:
                                raise XC9500XLError(f"fast programming failed {res.bits_repr()} at row {prev_row}")
                await self.lower.run_test_idle(self._time_us(WAIT_PROGRAM))
                prev_row = row

            res = await self._dr_isdata(CTRL_OK)
            if res.control == CTRL_WPROT:
                raise XC9500XLError("fast programming failed: device is write protected")
            elif res.control != CTRL_OK:
                raise XC9500XLError(f"fast programming failed {res.bits_repr()} at row {prev_row}")
        else:
            # Use FPGM for all writes.
            await self.lower.write_ir(IR_FPGM)
            prev_row = None
            for row in range(BS_ROWS):
                for col in range(BS_COLS):
                    word = bs.get_word(row, col)
                    res = await self._dr_isconfiguration(
                        CTRL_START if col == BS_COLS - 1 else CTRL_OK,
                        address=bs_address(row, col),
                        data=word)
                    if col == 0 and prev_row is not None:
                        if res.control == CTRL_WPROT:
                            raise XC9500XLError("programming failed: device is write protected")
                        elif res.control != CTRL_OK:
                            raise XC9500XLError(f"programming failed {res.bits_repr()} at row {prev_row}")
                await self.lower.run_test_idle(self._time_us(WAIT_PROGRAM))
                prev_row = row

            res = await self._dr_isconfiguration(CTRL_OK, 0)
            if res.control == CTRL_WPROT:
                raise XC9500XLError("programming failed: device is write protected")
            elif res.control != CTRL_OK:
                raise XC9500XLError(f"programming failed {res.bits_repr()} at row {prev_row}")

    async def program_prot_done(self, bs, fast=True, read_protect=False, write_protect=False):
        if not read_protect and not write_protect and self.device.kind != "xv":
            # Nothing to do.
            return

        self._log("program protection and DONE bits")
        assert READ_PROT_BIT[0] == WRITE_PROT_BIT[0] == DONE_BIT[1]
        row = READ_PROT_BIT[0]
        await self.lower.write_ir(IR_FPGM)
        for col in range(BS_COLS):
            word = bs.get_word(row, col)
            if col == READ_PROT_BIT[1] and read_protect:
                for fb in range(self.device.fbs):
                    word |= 1 << (READ_PROT_BIT[2] + 8 * fb)
            if col == WRITE_PROT_BIT[1] and write_protect:
                for fb in range(self.device.fbs):
                    word |= 1 << (WRITE_PROT_BIT[2] + 8 * fb)
            if col == DONE_BIT[2] and self.device.kind == "xv":
                word |= 1 << (DONE_BIT[3] + 8 * DONE_BIT[0])

            if col == 0 or not fast:
                await self._dr_isconfiguration(
                    CTRL_START if col == BS_COLS - 1 else CTRL_OK,
                    address=bs_address(row, col),
                    data=word)
                if fast:
                    await self.lower.write_ir(IR_FPGMI)
            else:
                await self._dr_isdata(
                    CTRL_START if col == BS_COLS - 1 else CTRL_OK,
                    data=word)

        await self.lower.run_test_idle(self._time_us(WAIT_PROGRAM))

        if fast:
            res = await self._dr_isdata(CTRL_OK)
        else:
            res = await self._dr_isconfiguration(CTRL_OK, 0)
        if res.control != CTRL_OK:
            raise XC9500XLError(f"programming protection and DONE bits failed {isaddr.bits_repr()}")


class ProgramXC9500XLApplet(JTAGProbeApplet):
    logger = logging.getLogger(__name__)
    help = "program Xilinx XC9500XL and XC9500XV CPLDs via JTAG"
    description = """
    Program, verify, and read out Xilinx XC9500XL and XC9500XV series CPLD bitstreams via the JTAG interface.

    It is recommended to use TCK frequency between 100 and 250 kHz for programming.

    Some CPLDs in the wild have been observed to return failures during programming, possibly
    because they are taken from the rejects bin or recycled, see [1]. The "program word failed"
    messages during programming do not necessarily mean a failed device; if the bitstream verifies
    afterwards, it is likely to operate correctly.

    [1]: http://tech.mattmillman.com/making-use-of-recycled-xilinx-xc9500-cplds/

    Supported devices are:
{devices}
    """.format(
        devices="\n".join(f"        * {device.name}" for device in devices)
    )

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)
        super().add_run_tap_arguments(parser)

    async def run(self, device, args):
        tap_iface = await self.run_tap(ProgramXC9500XLApplet, device, args)
        return XC9500XLInterface(tap_iface, self.logger, args.frequency * 1000)

    @classmethod
    def add_interact_arguments(cls, parser):
        parser.add_argument(
            "--slow", default=False, action="store_true",
            help="use slower but potentially more robust algorithms, where applicable")

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION")

        p_read = p_operation.add_parser(
            "read", help="read bitstream from the device and save it to a .jed file")
        p_read.add_argument(
            "jed_file", metavar="JED-FILE", type=argparse.FileType("wb"),
            help="JED file to write")

        p_program = p_operation.add_parser(
            "program", help="read bitstream from a .jed file and program it to the device")
        p_program.add_argument(
            "jed_file", metavar="JED-FILE", type=argparse.FileType("rb"),
            help="JED file to read")
        p_program.add_argument(
            "--override", default=False, action="store_true",
            help="override write-protection")
        p_program.add_argument(
            "--erase", default=False, action="store_true",
            help="erase before programming, if necessary")
        p_program.add_argument(
            "--verify", default=False, action="store_true",
            help="verify after programming")
        p_program.add_argument(
            "--write-protect", default=False, action="store_true",
            help="enable write protection")
        p_program.add_argument(
            "--read-protect", default=False, action="store_true",
            help="enable read protection")

        p_verify = p_operation.add_parser(
            "verify", help="read bitstream from a .jed file and verify it against the device")
        p_verify.add_argument(
            "jed_file", metavar="JED-FILE", type=argparse.FileType("rb"),
            help="JED file to read")

        p_erase = p_operation.add_parser(
            "erase", help="erase bitstream from the device")
        p_erase.add_argument(
            "--override", default=False, action="store_true",
            help="override write-protection")

    async def interact(self, device, args, xc9500_iface):
        idcode, xc9500_device, xc95xx_iface = await xc9500_iface.identify()
        if xc9500_device is None:
            raise GlasgowAppletError("cannot operate on unknown device with IDCODE=%#10x"
                                     % idcode.to_int())

        self.logger.info("found %s rev=%d",
                         xc9500_device.name, idcode.version)

        usercode = await xc9500_iface.read_usercode()
        self.logger.info("USERCODE=%s (%s)",
                         usercode.hex(),
                         re.sub(rb"[^\x20-\x7e]", b"?", usercode).decode("ascii"))

        try:
            if args.operation == "read":
                await xc95xx_iface.programming_enable()
                bs = await xc95xx_iface.read(fast=not args.slow)
                bs.clear_prot_done()
                fuses = bs.to_fuses()
                emitter = JESD3Emitter(fuses, quirk_no_design_spec=True)
                emitter.add_comment(b"DEVICE %s" % xc9500_device.name.encode())
                args.jed_file.write(emitter.emit())

            if args.operation in ("program", "verify"):
                try:
                    parser = JESD3Parser(args.jed_file.read(), quirk_no_design_spec=True)
                    parser.parse()
                except JESD3ParsingError as e:
                    raise GlasgowAppletError(str(e))

                bs = XC9500XLBitstream.from_fuses(parser.fuse, xc9500_device)

            if args.operation == "program":
                await xc95xx_iface.programming_enable()

                blank = await xc95xx_iface.blank_check()

                if args.erase:
                    if args.override:
                        await xc95xx_iface.override_erase()
                    elif blank == BlankCheckResult.WRITE_PROTECTED:
                        raise GlasgowAppletError("device is write-protected")
                    await xc95xx_iface.bulk_erase()
                    await xc95xx_iface.programming_disable()
                    await xc95xx_iface.programming_enable()
                elif blank != BlankCheckResult.BLANK:
                    raise GlasgowAppletError("device is not blank")

                await xc95xx_iface.program(bs, fast=not args.slow)

                if args.verify:
                    dev_bs = await xc95xx_iface.read(fast=not args.slow)
                    bs.verify(dev_bs)

                await xc95xx_iface.program_prot_done(bs, fast=not args.slow,
                                                     read_protect=args.read_protect,
                                                     write_protect=args.write_protect)

            if args.operation == "verify":
                await xc95xx_iface.programming_enable()
                dev_bs = await xc95xx_iface.read(fast=not args.slow)
                dev_bs.clear_prot_done()
                bs.verify(dev_bs)

            if args.operation == "erase":
                await xc95xx_iface.programming_enable()
                if args.override:
                    await xc95xx_iface.override_erase()
                await xc95xx_iface.bulk_erase()

        finally:
            await xc95xx_iface.programming_disable()

# -------------------------------------------------------------------------------------------------

class ProgramXC9500XLAppletTool(GlasgowAppletTool, applet=ProgramXC9500XLApplet):
    help = "manipulate Xilinx XC9500XL and XC9500XV CPLD bitstreams"
    description = """
    See `run program-xc9500xl --help` for details.
    """

    @classmethod
    def add_arguments(cls, parser):
        def idcode(arg):
            if arg.upper() in devices_by_name:
                return devices_by_name[arg.upper()]
            try:
                idcode = DR_IDCODE.from_int(int(arg, 16))
            except ValueError:
                raise argparse.ArgumentTypeError("unknown device")

            device = devices_by_idcode[idcode.mfg_id, idcode.part_id]
            if device is None:
                raise argparse.ArgumentTypeError("unknown IDCODE")
            return device

        parser.add_argument(
            "-d", "--device", metavar="DEVICE", type=idcode, required=True,
            help="select device with given name or JTAG IDCODE")

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION")

        p_read_usercode = p_operation.add_parser(
            "read-usercode", help="read USERCODE from a .jed file")
        p_read_usercode.add_argument(
            "jed_file", metavar="JED-FILE", type=argparse.FileType("rb"),
            help="bitstream file to read")

    async def run(self, args):
        if args.operation == "read-usercode":
            try:
                parser = JESD3Parser(args.jed_file.read(), quirk_no_design_spec=True)
                parser.parse()
            except JESD3ParsingError as e:
                raise GlasgowAppletError(str(e))

            bs = XC9500XLBitstream.from_fuses(parser.fuse, args.device)

            usercode = 0
            for i, (fb, row, col, bit) in enumerate(USERCODE_BITS):
                data = bs.fbs[fb][row][col] >> bit & 1
                usercode |= data << i

            usercode = struct.pack(">L", usercode)
            self.logger.info("USERCODE=%s (%s)",
                             usercode.hex(),
                             re.sub(rb"[^\x20-\x7e]", b"?", usercode).decode("ascii"))
