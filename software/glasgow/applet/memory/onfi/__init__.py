# Memory organization
# -------------------
#
# The NAND flash architecture is highly parallel to improve throughput, and is built around
# limitations of the storage medium. This results in a somewhat confusing set of terms used to
# refer to various subdivisions of the memory array. The following is a short introduction that
# should clear things up.
#
# To recap, NAND memory is programmed in smaller multi-byte units and erased in larger multi-byte
# units. The programming operation can only change a bit from 1 to 0, and the erase operation can
# only change a bit from 0 to 1.
#
# The basic unit of a NAND memory is a page. A page is the smallest unit that can be independently
# programmed. A page consists of a power-of-two sized data area, and an arbitrarily sized spare
# area, e.g. 4096 and 224 bytes correspondingly. The spare area is used to store ECC data, block
# erase counters, and any other necessary auxiliary data.
#
# Pages are grouped into blocks; a block is the smallest unit that can be independently erased.
# A block consists of a power-of-two number of pages, which is a multiple of 32 on ONFI compliant
# memories.
#
# Blocks are grouped into LUNs (short for "logical unit"); a LUN is a single physical die, with
# its own command decoder, page cache(s), drive circuits, etc.
#
# LUNs are grouped into targets; a target is one or more dice that share all of their electrical
# connections, including the data bus and the CE# pin. Bus contention is avoided because each LUN
# will only drive the bus when it detects its own address. It is usually possible to issue
# operations to multiple LUNs at once as well, though it is not trivial to get the right commands
# and data to the right LUN.
#
# Targets are grouped into packages; a package is one or more dice encapsulated into the same piece
# of epoxy with electrical connections. A package has a separate CE# pin or pad for each target,
# and may have more than one data bus, depending on the pinout.
#
# The memory can be addressed in terms of rows and columns. A column is an index pointing to
# an individual byte within the page. It can point into both the data and spare area, which
# logically appear consecutive, and are read as one contiguous block. (There is usually no
# physical distinction between data and spare areas.)
#
# A row is an index pointing to an individual page, and by extension a block containing that page.
# The row address bits can be separated, from least to most significant, into page index, block
# index, and LUN index. Some devices have structure beyond just being a linear array of blocks and
# pages, and so some row address bits will gain additional significance.
#
# There are no gaps between rows. That is, all pages inside a target may be addressed by
# incrementing a row counter starting from zero. In particular, unless multi-LUN operations are
# used, a target may consist of any number of LUNs yet respond to exact same commands.
#
# Besides uniquely addressing a page, a row may be used to address a single block, e.g. for
# the Block Erase command. In this case the low order bits that select a page within a block
# are ignored.
#
# Subpages
# --------
#
# Although, naively, it may appear that a page may be programmed arbitrarily many times, changing
# more and more bits from 1 to 0, this is not actually permitted by device manufacturers. Indeed,
# in the case where page programming is possible more than once (typically only on SLC memories),
# the page is divided into several subpages, and each subpage can in turn be programmed only once,
# sometimes with restrictions on order of programming of individual subpages.
#
# Planes
# ------
#
# The simplest memory die has a cache that fits a single page, and can program or erase only one
# page or block at a time. Naively, increasing programming speed would require increasing page size
# (which makes fragmentation worse), or using more than one die (which makes packaging more
# expensive). A middle ground between these is to add a second page cache, and allow programming
# more than one page, or erasing more than one block, at a time. This is called "multiple planes".
#
# In a device with multiple planes, blocks are grouped into planes through interleaving. For
# example, in a device with two planes, odd blocks belong to plane 0, and even blocks belong to
# plane 1. When issuing multi-plane operations, there is an additional constraint that in all
# of the selected planes, the page index must be the same. For example, in a device with two
# planes, a multi-plane operation may affect any even and any odd block, and if the operation
# is page-oriented, the offset into the block must be the same for both.

import argparse
import logging
import asyncio
import struct
from nmigen.compat import *
from nmigen.compat.genlib.cdc import MultiReg

from ....support.logging import *
from ....database.jedec import *
from ....protocol.onfi import *
from ... import *


CMD_SELECT  = 0x01
CMD_CONTROL = 0x02
BIT_CE      = 0x01
BIT_CLE     = 0x02
BIT_ALE     = 0x04
CMD_WRITE   = 0x03
CMD_READ    = 0x04
CMD_WAIT    = 0x05


class MemoryONFIBus(Module):
    def __init__(self, pads):
        self.doe = Signal()
        self.do  = Signal.like(pads.io_t.o)
        self.di  = Signal.like(pads.io_t.i)
        self.ce  = Signal.like(pads.ce_t.o)
        self.cle = Signal()
        self.ale = Signal()
        self.re  = Signal()
        self.we  = Signal()
        self.rdy = Signal()

        ###

        self.comb += [
            pads.io_t.oe.eq(self.doe),
            pads.io_t.o.eq(self.do),
            pads.ce_t.oe.eq(1),
            pads.ce_t.o.eq(~self.ce),
            pads.cle_t.oe.eq(1),
            pads.cle_t.o.eq(self.cle),
            pads.ale_t.oe.eq(1),
            pads.ale_t.o.eq(self.ale),
            pads.re_t.oe.eq(1),
            pads.re_t.o.eq(~self.re),
            pads.we_t.oe.eq(1),
            pads.we_t.o.eq(~self.we),
        ]
        self.specials += [
            MultiReg(pads.io_t.i, self.di),
            MultiReg(pads.r_b_t.i, self.rdy),
        ]


class MemoryONFISubtarget(Module):
    def __init__(self, pads, in_fifo, out_fifo):
        self.submodules.bus = bus = MemoryONFIBus(pads)

        ###

        command = Signal(8)
        select  = Signal(max=4)
        control = Signal(3)
        length  = Signal(16)

        wait_cyc = 3 # currently required for reliable reads
        timer    = Signal(max=wait_cyc + 2, reset=wait_cyc)

        self.submodules.fsm = FSM(reset_state="RECV-COMMAND")
        self.fsm.act("RECV-COMMAND",
            in_fifo.flush.eq(1),
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(command, out_fifo.dout),
                If(out_fifo.dout == CMD_SELECT,
                    NextState("RECV-SELECT")
                ).Elif(out_fifo.dout == CMD_CONTROL,
                    NextState("RECV-CONTROL")
                ).Elif((out_fifo.dout == CMD_READ) | (out_fifo.dout == CMD_WRITE),
                    NextState("RECV-LENGTH-1")
                ).Elif((out_fifo.dout == CMD_WAIT),
                    NextState("ONFI-SETUP")
                )
            ),
            NextValue(bus.doe, 0)
        )
        self.fsm.act("RECV-SELECT",
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(select, out_fifo.dout),
                NextState("RECV-COMMAND")
            )
        )
        self.fsm.act("RECV-CONTROL",
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(control, out_fifo.dout),
                NextState("ONFI-SETUP")
            )
        )
        self.fsm.act("RECV-LENGTH-1",
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(length[0:8], out_fifo.dout),
                NextState("RECV-LENGTH-2")
            )
        )
        self.fsm.act("RECV-LENGTH-2",
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(length[8:16], out_fifo.dout),
                NextState("ONFI-SETUP")
            )
        )
        self.fsm.act("ONFI-SETUP",
            If(timer != 0,
                NextValue(timer, timer - 1),
            ).Else(
                NextValue(timer, wait_cyc),
                If(command == CMD_CONTROL,
                    NextValue(bus.ce, Mux(control & BIT_CE, 1 << select, 0)),
                    NextValue(bus.cle, (control & BIT_CLE) != 0),
                    NextValue(bus.ale, (control & BIT_ALE) != 0),
                    NextState("RECV-COMMAND")
                ).Elif(command == CMD_WRITE,
                    If(length == 0,
                        NextState("RECV-COMMAND")
                    ).Else(
                        NextState("RECV-DATA")
                    )
                ).Elif(command == CMD_READ,
                    If(length == 0,
                        NextState("RECV-COMMAND")
                    ).Else(
                        NextValue(bus.re, 1),
                        NextState("ONFI-READ-HOLD")
                    )
                ).Elif(command == CMD_WAIT,
                    If(bus.rdy,
                        NextState("RECV-COMMAND")
                    )
                )
            )
        )
        self.fsm.act("RECV-DATA",
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(bus.do, out_fifo.dout),
                NextValue(bus.we, 1),
                NextState("ONFI-WRITE-HOLD")
            )
        )
        self.fsm.act("ONFI-WRITE-HOLD",
            NextValue(bus.doe, 1),
            If(timer != 0,
                NextValue(timer, timer - 1),
            ).Else(
                NextValue(bus.we, 0),
                NextValue(timer, wait_cyc),
                NextValue(length, length - 1),
                NextState("ONFI-SETUP")
            )
        )
        self.fsm.act("ONFI-READ-HOLD",
            NextValue(bus.doe, 0),
            If(timer != 0,
                NextValue(timer, timer - 1),
            ).Else(
                NextValue(bus.re, 0),
                NextValue(in_fifo.din, bus.di),
                NextValue(timer, wait_cyc),
                NextState("SEND-DATA")
            )
        )
        self.fsm.act("SEND-DATA",
            If(in_fifo.writable,
                in_fifo.we.eq(1),
                NextValue(length, length - 1),
                NextState("ONFI-SETUP")
            )
        )


BIT_STATUS_FAIL        = 1 << 0
BIT_STATUS_FAIL_PREV   = 1 << 1
BIT_STATUS_CACHE_READY = 1 << 5
BIT_STATUS_READY       = 1 << 6
BIT_STATUS_WRITE_PROT  = 1 << 7


class ONFIInterface:
    def __init__(self, interface, logger):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

    def _log(self, message, *args):
        self._logger.log(self._level, "ONFI: " + message, *args)

    async def select(self, chip):
        assert chip in range(0, 4)
        self._log("select chip=%d", chip)
        await self.lower.write(struct.pack("<BB", CMD_SELECT, chip))

    async def _control(self, bits):
        await self.lower.write(struct.pack("<BB", CMD_CONTROL, bits))

    async def _write(self, data):
        data = bytes(data)
        await self.lower.write(struct.pack("<BH", CMD_WRITE, len(data)) + data)

    async def _read(self, length):
        await self.lower.write(struct.pack("<BH", CMD_READ, length))

    async def _wait(self):
        await self.lower.write(struct.pack("<B", CMD_WAIT))

    async def _do(self, command, address=[], wait=False):
        address = bytes(address)
        if len(address) > 0:
            self._log("command=%#04x address=<%s>", command, address.hex())
        else:
            self._log("command=%#04x", command)
        await self._control(BIT_CE|BIT_CLE)
        await self._write([command])
        if len(address) > 0:
            await self._control(BIT_CE|BIT_ALE)
            await self._write(address)
        await self._control(BIT_CE)
        if wait:
            self._log("r/b wait")
            await self._wait()

    async def _do_write(self, command, address=[], wait=False, data=[]):
        data = bytes(data)
        await self._do(command, address, wait)
        self._log("write data=<%s>", dump_hex(data))
        await self._write(data)

    async def _do_read(self, command, address=[], wait=False, length=0):
        await self._do(command, address, wait)
        await self._read(length)
        data = await self.lower.read(length)
        self._log("read data=<%s>", dump_hex(data))
        return data

    async def reset(self):
        self._log("reset")
        await self._do(command=0xff, wait=True)

    async def _read_id(self, address, length):
        self._log("read ID addr=%#04x", address)
        return await self._do_read(command=0x90, address=[address], length=length)

    async def read_jedec_id(self):
        manufacturer_id, device_id = await self._read_id(address=0x00, length=2)
        return manufacturer_id, device_id

    async def read_signature(self):
        return await self._read_id(address=0x00, length=4)

    async def read_onfi_signature(self):
        return await self._read_id(address=0x20, length=4)

    async def read_status(self):
        self._log("read status")
        status, = await self._do_read(command=0x70, length=1)
        return status

    async def is_write_protected(self):
        return (await self.read_status() & BIT_STATUS_WRITE_PROT) == 0

    async def read_parameter_page(self, copies=3):
        self._log("read parameter page copies=%d", copies)
        return await self._do_read(command=0xEC, address=[0x00], wait=True, length=copies * 256)

    async def read_unique_id(self):
        self._log("read unique ID")
        return await self._do_read(command=0xED, address=[0x00], wait=True, length=32)

    async def read(self, row, column, length):
        self._log("read row=%#08x column=%#06x", row, column)
        await self._do(command=0x00, address=[
            (column >>  0) & 0xff,
            (column >>  8) & 0xff,
            (row >>  0) & 0xff,
            (row >>  8) & 0xff,
            (row >> 16) & 0xff,
        ])
        return await self._do_read(command=0x30, wait=True, length=length)

    async def program(self, row, chunks):
        self._log("program row=%#08x", row)
        await self._do_write(command=0x80, address=[
            0,
            0,
            (row >>  0) & 0xff,
            (row >>  8) & 0xff,
            (row >> 16) & 0xff,
        ])

        for (column, data) in chunks:
            data = bytes(data)
            self._log("column=%#06x data=<%s>", column, dump_hex(data))
            await self._do_write(command=0x85, address=[
                (column >>  0) & 0xff,
                (column >>  8) & 0xff,
            ], data=data)

        await self._do(command=0x10, wait=True)
        return (await self.read_status() & BIT_STATUS_FAIL) == 0

    async def erase(self, row):
        self._log("erase row=%#08x", row)
        await self._do(command=0x60, address=[
            (row >>  0) & 0xff,
            (row >>  8) & 0xff,
            (row >> 16) & 0xff,
        ])
        await self._do(command=0xD0, wait=True)
        return (await self.read_status() & BIT_STATUS_FAIL) == 0


class MemoryONFIApplet(GlasgowApplet, name="memory-onfi"):
    preview = True
    logger = logging.getLogger(__name__)
    help = "read and write ONFI-like NAND Flash memories"
    description = """
    Identify, read and write memories compatible with ONFI NAND Flash memory. The applet roughly
    follows the ONFI 1.0 specification, but tolerates the very common non-ONFI-compliant memories
    by gracefully degrading autodetection of memory functionality.

    Only the asynchronous NAND interface is supported. All R/B# pins should be tied together,
    and externally pulled up. All CE# pins must be either connected or pulled high to avoid
    bus contention; for unidentified devices, this means all 4 CE# pins available on the package.

    The NAND Flash command set is not standardized in practice. This applet uses the following
    commands when identifying the memory:

        * Cmd 0xFF: Reset (all devices)
        * Cmd 0x90 Addr 0x00: Read ID, JEDEC Manufacturer and Device (all devices)
        * Cmd 0x90 Addr 0x20: Read ID, ONFI Signature (ONFI and some non-ONFI devices)
        * Cmd 0xEC: Read Parameter Page (ONFI only)

    If the memory doesn't respond or gives invalid response to ONFI commands, it can still be
    used, but the array parameters need to be specified explicitly.

    The applet use the following commands while reading and writing data:

        * Cmd 0x70: Read Status (all devices)
        * Cmd 0x00 Addr Col1..2,Row1..3 Cmd 0x30: Read (all devices)
        * Cmd 0x60 Addr Row1..3 Cmd 0xD0: Erase (all devices)
        * Cmd 0x80 Addr Col1..2,Row1..3 [Cmd 0x85 Col1..2]+ Cmd 0x10: Page Program (all devices)
    """
    pin_sets = ("io", "ce")
    pins = ("cle", "ale", "re", "we", "r_b")

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_build_arguments(parser)
        access.add_pin_set_argument(parser, "io", 8, default=True)
        for pin in cls.pins:
            access.add_pin_argument(parser, pin, default=True)
        access.add_pin_set_argument(parser, "ce", range(1, 5), default=2)

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        iface.add_subtarget(MemoryONFISubtarget(
            pads=iface.get_pads(args, pin_sets=self.pin_sets, pins=self.pins),
            in_fifo=iface.get_in_fifo(auto_flush=False),
            out_fifo=iface.get_out_fifo(),
        ))

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)

        parser.add_argument(
            "-c", "--chip", metavar="CHIP", type=int, default=1,
            help="select chip connected to CE# signal CHIP (one of: 1..4, default: 1)")

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        onfi_iface = ONFIInterface(iface, self.logger)

        # Reset every target, to make sure all of them are in a defined state and aren't driving
        # the shared data bus.
        for chip in range(len(args.pin_set_ce)):
            await onfi_iface.select(chip)
            await onfi_iface.reset()

        available_ce = range(1, 1 + len(args.pin_set_ce))
        if args.chip not in available_ce:
            raise GlasgowAppletError("cannot select chip {}; available select signals are {}"
                .format(args.chip, ", ".join("CE{}#".format(n) for n in available_ce)))
        await onfi_iface.select(args.chip - 1)

        return onfi_iface

    @classmethod
    def add_interact_arguments(cls, parser):
        def size(arg):
            return int(arg, 0)
        def address(arg):
            return int(arg, 0)
        def count(arg):
            return int(arg, 0)

        parser.add_argument(
            "-P", "--page-size", metavar="SIZE", type=size,
            help="Flash page (without spare) size, in bytes (default: autodetect)")
        parser.add_argument(
            "-S", "--spare-size", metavar="SIZE", type=size,
            help="Flash spare size, in bytes (default: autodetect)")
        parser.add_argument(
            "-B", "--block-size", metavar="SIZE", type=size,
            help="Flash block size, in pages (default: autodetect)")

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

        p_identify = p_operation.add_parser(
            "identify", help="identify device using ONFI parameter page")

        p_read = p_operation.add_parser(
            "read", help="read data and spare contents for a page range")
        p_read.add_argument(
            "start_page", metavar="PAGE", type=address,
            help="read starting at page PAGE")
        p_read.add_argument(
            "count", metavar="COUNT", type=count,
            help="read COUNT pages")
        p_read.add_argument(
            "data_file", metavar="DATA-FILE", type=argparse.FileType("wb"),
            help="write bytes from data and possibly spare area to DATA-FILE")
        p_read.add_argument(
            "spare_file", metavar="SPARE-FILE", type=argparse.FileType("wb"), nargs="?",
            help="write bytes from spare area to SPARE-FILE instead of DATA-FILE")

        p_program = p_operation.add_parser(
            "program", help="program data and spare contents for a page range")
        p_program.add_argument(
            "start_page", metavar="PAGE", type=address,
            help="program starting at page PAGE")
        p_program.add_argument(
            "count", metavar="COUNT", type=count,
            help="program COUNT pages")
        p_program.add_argument(
            "data_file", metavar="DATA-FILE", type=argparse.FileType("rb"),
            help="program bytes to data area from DATA-FILE")
        p_program.add_argument(
            "spare_file", metavar="SPARE-FILE", type=argparse.FileType("rb"),
            help="program bytes to spare area from SPARE-FILE")

        p_erase = p_operation.add_parser(
            "erase", help="erase any blocks containing a page range")
        p_erase.add_argument(
            "start_page", metavar="PAGE", type=address,
            help="erase starting at block containing page PAGE")
        p_erase.add_argument(
            "count", metavar="COUNT", type=count, nargs="?", default=1,
            help="erase blocks containing the next COUNT pages")

    async def interact(self, device, args, onfi_iface):
        manufacturer_id, device_id = await onfi_iface.read_jedec_id()
        if manufacturer_id in (0x00, 0xff):
            self.logger.error("JEDEC identification not present")
            return

        manufacturer_name = jedec_mfg_name_from_bytes([manufacturer_id]) or "unknown"
        self.logger.info("JEDEC manufacturer %#04x (%s) device %#04x",
                         manufacturer_id, manufacturer_name, device_id)

        # First four bytes of Read ID are often used as-is in data recovery software,
        # so print these for convenience as well.
        signature = await onfi_iface.read_signature()
        self.logger.info("ID signature: %s",
                         " ".join("{:02x}".format(byte) for byte in signature))

        onfi_param = None
        if await onfi_iface.read_onfi_signature() == b"ONFI":
            parameter_page = await onfi_iface.read_parameter_page()
            try:
                onfi_param = ONFIParameters(parameter_page)
            except ONFIParameterError as e:
                self.logger.warning("invalid ONFI parameter page: %s", str(e))
        else:
            self.logger.warning("ONFI signature not present")

        if args.operation == "identify" and onfi_param is None:
            self.logger.error("cannot identify non-ONFI device")
            return
        elif args.operation == "identify":
            self.logger.info("ONFI revision %d.%d%s",
                *onfi_param.revision,
                "+" if onfi_param.revisions.unknown else "")

            blocks = {}

            onfi_jedec_manufacturer_name = \
                jedec_mfg_name_from_bytes([onfi_param.jedec_manufacturer_id]) or "unknown"
            blocks["ONFI manufacturer information"] = {
                "JEDEC ID":     "{:#04x} ({})"
                    .format(onfi_param.jedec_manufacturer_id, onfi_jedec_manufacturer_name),
                "manufacturer": onfi_param.manufacturer,
                "model":        onfi_param.model,
                "date code":
                    "(not specified)" if onfi_param.date_code is None else
                    "year %02d, week %02d".format(onfi_param.date_code.year,
                                                  onfi_param.date_code.week)
            }

            blocks["Features"] = {
                "data bus width":
                    "16-bit" if onfi_param.features._16_bit_data_bus else "8-bit",
                "multi-LUN operations":
                    "yes" if onfi_param.features.multiple_lun_ops else "no",
                "block programming order":
                    "random" if onfi_param.features.non_seq_page_program else "sequential",
                "interleaved operations":
                    "yes" if onfi_param.features.interleaved_ops else "no",
                "odd-to-even copyback":
                    "yes" if onfi_param.features.odd_to_even_copyback else "no",
            }

            blocks["Optional commands"] = {
                "Page Cache Program":
                    "yes" if onfi_param.opt_commands.page_cache_program else "no",
                "Read Cache (Enhanced/End)":
                    "yes" if onfi_param.opt_commands.read_cache else "no",
                "Get/Set Features":
                    "yes" if onfi_param.opt_commands.get_set_features else "no",
                "Read Status Enhanced":
                    "yes" if onfi_param.opt_commands.read_status_enhanced else "no",
                "Copyback Program/Read":
                    "yes" if onfi_param.opt_commands.copyback else "no",
                "Read Unique ID":
                    "yes" if onfi_param.opt_commands.read_unique_id else "no",
            }

            blocks["Memory organization"] = {
                "page size":          "{} + {} bytes"
                    .format(onfi_param.bytes_per_page, onfi_param.bytes_per_spare),
                "partial page size":  "{} + {} bytes"
                    .format(onfi_param.bytes_per_partial_page, onfi_param.bytes_per_partial_spare),
                "block size":         "{} pages"
                    .format(onfi_param.pages_per_block),
                "LUN size":           "{} blocks; {} pages"
                    .format(onfi_param.blocks_per_lun,
                            onfi_param.blocks_per_lun * onfi_param.pages_per_block),
                "target size":        "{} LUNs; {} blocks; {} pages"
                    .format(onfi_param.luns_per_target,
                            onfi_param.luns_per_target * onfi_param.blocks_per_lun,
                            onfi_param.luns_per_target * onfi_param.blocks_per_lun
                                                       * onfi_param.pages_per_block),
                "address cycles":     "{} row, {} column"
                    .format(onfi_param.address_cycles.row, onfi_param.address_cycles.column),
                "bits per cell":      "{}"
                    .format(onfi_param.bits_per_cell),
                "bad blocks per LUN": "{} (maximum)"
                    .format(onfi_param.max_bad_blocks_per_lun),
                "block endurance":    "{} cycles (maximum)"
                    .format(onfi_param.block_endurance),
                "guaranteed blocks":  "{} (at target beginning)"
                    .format(onfi_param.guaranteed_valid_blocks),
                "guaranteed block endurance": "{} cycles"
                    .format(onfi_param.guaranteed_valid_block_endurance),
                "programs per page":  "{} (maximum)"
                    .format(onfi_param.programs_per_page),
                # Partial programming constraints not displayed.
                "ECC correctability": "{} bits (maximum, per 512 bytes)"
                    .format(onfi_param.ecc_correctability_bits),
                # Interleaved operations not displayed.
            }

            blocks["Electrical parameters"] = {
                "I/O pin capacitance": "{} pF"
                    .format(onfi_param.io_pin_capacitance),
                "timing modes":
                    ", ".join(str(mode) for mode in onfi_param.timing_modes),
                "program cache timing modes":
                    ", ".join(str(mode) for mode in onfi_param.program_cache_timing_modes) or
                    "(not supported)",
                "page program time":   "{} us (maximum)"
                    .format(onfi_param.max_page_program_time),
                "block erase time":    "{} us (maximum)"
                    .format(onfi_param.max_block_erase_time),
                "page read time":      "{} us (maximum)"
                    .format(onfi_param.max_page_read_time),
                "change column setup time": "{} us (minimum)"
                    .format(onfi_param.min_change_column_setup_time),
            }

            for block, params in blocks.items():
                self.logger.info("%s:", block)
                for name, value in params.items():
                    self.logger.info("%27s: %s", name, value)

            return

        if onfi_param is not None:
            if (args.page_size is not None or
                    args.block_size is not None or
                    args.spare_size is not None):
                self.logger.warning("explicitly specified geometry is ignored in favor of "
                                    "ONFI parameters")

            page_size  = onfi_param.bytes_per_page
            spare_size = onfi_param.bytes_per_spare
            block_size = onfi_param.pages_per_block
        else:
            if (args.page_size is None or
                    args.block_size is None or
                    args.spare_size is None):
                self.logger.error("your cursed device doesn't support ONFI properly")
                self.logger.error("in the future, avoid angering witches")
                self.logger.error("meanwhile, configure the Flash array parameters explicitly via "
                                  "--page-size, --spare-size and --block-size")
                return

            page_size  = args.page_size
            spare_size = args.spare_size
            block_size = args.block_size

        if args.operation in ("program", "erase"):
            if await onfi_iface.is_write_protected():
                self.logger.error("device is write-protected")
                return

        if args.operation == "read":
            row   = args.start_page
            count = args.count
            while count > 0:
                self.logger.info("reading page (row) %d", row)
                chunk = await onfi_iface.read(column=0, row=row, length=page_size + spare_size)

                if args.spare_file:
                    args.data_file.write(chunk[:page_size])
                    args.data_file.flush()
                    args.spare_file.write(chunk[-spare_size:])
                    args.spare_file.flush()
                else:
                    args.data_file.write(chunk)
                    args.data_file.flush()

                row   += 1
                count -= 1

        if args.operation == "program":
            row   = args.start_page
            count = args.count
            while count > 0:
                if args.spare_file:
                    data   = args.data_file.read(page_size)
                    spare  = args.spare_file.read(spare_size)
                    chunks = [(0, data), (page_size, spare)]
                else:
                    chunk  = args.data_file.read(page_size + spare_size)
                    chunks = [(0, chunk)]

                self.logger.info("programming page (row) %d", row)
                if not await onfi_iface.program(row=row, chunks=chunks):
                    self.logger.error("failed to program page (row) %d", row)

                row   += 1
                count -= 1

        if args.operation == "erase":
            row   = args.start_page
            count = args.count
            while count > 0:
                self.logger.info("erasing block %d (row %d)", row // block_size, row)
                if not await onfi_iface.erase(row=row):
                    self.logger.error("failed to erase block %d (row %d)", row // block_size, row)

                row   += block_size
                count -= block_size

# -------------------------------------------------------------------------------------------------

class MemoryONFIAppletTestCase(GlasgowAppletTestCase, applet=MemoryONFIApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--port", "AB"])
