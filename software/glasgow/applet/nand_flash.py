import argparse
import logging
import asyncio
import struct
from migen import *
from migen.genlib.fsm import *

from . import *
from ..database.jedec import *
from ..pyrepl import *


CMD_CONTROL = 0x01
BIT_CE      = 0x01
BIT_CLE     = 0x02
BIT_ALE     = 0x04
CMD_WRITE   = 0x02
CMD_READ    = 0x03
CMD_WAIT    = 0x04


class ONFIBus(Module):
    def __init__(self, pads):
        self.doe = Signal()
        self.do  = Signal.like(pads.io_t.o)
        self.di  = Signal.like(pads.io_t.i)
        self.ce  = Signal()
        self.cle = Signal()
        self.ale = Signal()
        self.re  = Signal()
        self.we  = Signal()
        self.rdy = Signal()

        ###

        self.comb += [
            pads.io_t.oe.eq(self.doe),
            pads.io_t.o.eq(self.do),
            self.di.eq(pads.io_t.i),
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
            self.rdy.eq(pads.r_b_t.i),
        ]


class ONFISubtarget(Module):
    def __init__(self, pads, in_fifo, out_fifo):
        self.submodules.bus = bus = ONFIBus(pads)

        ###

        command = Signal(8)
        control = Signal(3)
        length  = Signal(16)

        wait_cyc = 2 # revB needs at least two wait states for reliable reads
        timer    = Signal(max=wait_cyc + 2, reset=wait_cyc)

        self.submodules.fsm = FSM(reset_state="RECV-COMMAND")
        self.fsm.act("RECV-COMMAND",
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(command, out_fifo.dout),
                If(out_fifo.dout == CMD_CONTROL,
                    NextState("RECV-CONTROL")
                ).Elif((out_fifo.dout == CMD_READ) | (out_fifo.dout == CMD_WRITE),
                    NextState("RECV-LENGTH-1")
                ).Elif((out_fifo.dout == CMD_WAIT),
                    NextState("ONFI-SETUP")
                )
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
                NextValue(bus.doe, 0),
                NextValue(timer, wait_cyc),
                If(command == CMD_CONTROL,
                    NextValue(bus.ce, (control & BIT_CE) != 0),
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
                NextValue(bus.doe, 1),
                NextValue(bus.we, 1),
                NextState("ONFI-WRITE-HOLD")
            )
        )
        self.fsm.act("ONFI-WRITE-HOLD",
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
            If(timer != 0,
                NextValue(timer, timer - 1),
                NextValue(in_fifo.din, bus.di),
            ).Else(
                NextValue(bus.re, 0),
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
        self._log("write data=<%s>", data.hex())
        await self._write(data)

    async def _do_read(self, command, address=[], wait=False, length=0):
        await self._do(command, address, wait)
        await self._read(length)
        data = await self.lower.read(length)
        self._log("read data=<%s>", data.hex())
        return data

    async def reset(self):
        self._log("reset")
        await self._do(command=0xff)
        await self.lower.flush()
        await asyncio.sleep(0.001) # tRST=1000us

    async def _read_id(self, address, length):
        self._log("read ID addr=%#04x", address)
        return await self._do_read(command=0x90, address=[address], length=length)

    async def read_signature(self):
        return await self._read_id(address=0x20, length=4)

    async def read_jedec_id(self):
        manufacturer_id, device_id = await self._read_id(address=0x00, length=2)
        return manufacturer_id, device_id

    async def read_status(self):
        self._log("read status")
        status, = await self._do_read(command=0x70, length=1)
        return status

    async def is_write_protected(self):
        return (await self.read_status() & BIT_STATUS_WRITE_PROT) == 0

    async def read_parameter_page(self):
        self._log("read parameter page")
        return await self._do_read(command=0xEC, address=[0x00], wait=True, length=512)

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
            self._log("column=%#06x data=<%s>", column, data.hex())
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


class NANDFlashApplet(GlasgowApplet, name="nand-flash"):
    preview = True
    logger = logging.getLogger(__name__)
    help = "read and write ONFI-like NAND Flash memories"
    description = """
    Identify, read and write various NAND Flash memories. The applet roughly follows the ONFI 1.0
    specification, but tolerates the very common non-ONFI-compliant memories by gracefully
    degrading autodetection of memory functionality.

    Only the asynchronous NAND interface is supported. An external pullup is necessary on
    the R/B# pin.

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
    pin_sets = ("io",)
    pins = ("ce", "cle", "ale", "re", "we", "r_b")

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_build_arguments(parser)
        access.add_pin_set_argument(parser, "io", 8, default=True)
        for pin in cls.pins:
            access.add_pin_argument(parser, pin, default=True)

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        iface.add_subtarget(ONFISubtarget(
            pads=iface.get_pads(args, pin_sets=self.pin_sets, pins=self.pins),
            in_fifo=iface.get_in_fifo(),
            out_fifo=iface.get_out_fifo(),
        ))

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        return ONFIInterface(iface, self.logger)

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

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION")

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
            help="write bytes from data area to DATA-FILE")
        p_read.add_argument(
            "spare_file", metavar="SPARE-FILE", type=argparse.FileType("wb"),
            help="write bytes from spare area to SPARE-FILE")

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

        p_operation.add_parser(
            "repl", help="drop into Python shell; use `nand_iface` to communicate")

    async def interact(self, device, args, nand_iface):
        manufacturer_id, device_id = await nand_iface.read_jedec_id()
        if manufacturer_id in (0x00, 0xff):
            self.logger.error("JEDEC identification not present")
            return

        manufacturer_name = jedec_manufacturer_name([manufacturer_id]) or "unknown"
        self.logger.info("JEDEC manufacturer %#04x (%s) device %#04x",
                         manufacturer_id, manufacturer_name, device_id)

        page_size  = args.page_size
        spare_size = args.spare_size
        block_size = args.block_size
        if await nand_iface.read_signature() == b"ONFI":
            parameter_page = await nand_iface.read_parameter_page()
            if parameter_page[0:4] == b"ONFI":
                # I don't actually have any *actually valid* ONFI flashes yet,
                # so this isn't implemented or tested. Sigh. Cursed.
                pass
            else:
                self.logger.warning("ONFI signature present, but parameter page missing")
        else:
            self.logger.warning("ONFI signature not present")

        if None in (args.page_size, args.block_size, args.spare_size):
            self.logger.error("your cursed device doesn't support ONFI properly")
            self.logger.error("in the future, avoid angering witches")
            self.logger.error("meanwhile, configure the Flash array parameters explicitly via "
                              "--page-size, --spare-size and --block-size")
            return

        if args.operation in ("program", "erase"):
            if await nand_iface.is_write_protected():
                self.logger.error("device is write-protected")
                return

        if args.operation == "read":
            row   = args.start_page
            count = args.count
            while count > 0:
                self.logger.info("reading page (row) %d", row)
                chunk = await nand_iface.read(column=0, row=row, length=page_size + spare_size)

                args.data_file.write(chunk[:page_size])
                args.data_file.flush()
                args.spare_file.write(chunk[-spare_size:])
                args.spare_file.flush()

                row   += 1
                count -= 1

        if args.operation == "program":
            row   = args.start_page
            count = args.count
            while count > 0:
                data  = args.data_file.read(page_size)
                spare = args.spare_file.read(spare_size)

                self.logger.info("programming page (row) %d", row)
                if not await nand_iface.program(row=row, chunks=[(0, data), (page_size, spare)]):
                    self.logger.error("failed to program page (row) %d", row)

                row   += 1
                count -= 1

        if args.operation == "erase":
            row   = args.start_page
            count = args.count
            while count > 0:
                self.logger.info("erasing block %d (row %d)", row // block_size, row)
                if not await nand_iface.erase(row=row):
                    self.logger.error("failed to erase block %d (row %d)", row // block_size, row)

                row   += block_size
                count -= block_size

        if args.operation == "repl":
            await AsyncInteractiveConsole(locals={"nand_iface":nand_iface}).interact()

# -------------------------------------------------------------------------------------------------

class NANDFlashAppletTestCase(GlasgowAppletTestCase, applet=NANDFlashApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--port", "AB"])
