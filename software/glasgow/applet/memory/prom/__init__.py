# Ref: Microchip 27C512A 512K (64K x 8) CMOS EPROM
# Accession: G00057

import re
import math
import enum
import random
import logging
import asyncio
import argparse
from nmigen import *
from nmigen.lib.cdc import FFSynchronizer

from ....support.logging import *
from ... import *


class MemoryPROMBus(Elaboratable):
    def __init__(self, pads, a_bits, sh_freq):
        self._pads    = pads
        self.a_bits   = a_bits
        self.dq_bits  = len(pads.dq_t.i)
        self._sh_freq = sh_freq

        self.ce  = Signal()
        self.oe  = Signal()
        self.we  = Signal()
        self.d   = Signal(self.dq_bits)
        self.q   = Signal(self.dq_bits)
        self.a   = Signal(self.a_bits)

        self.rdy = Signal()

    def elaborate(self, platform):
        m = Module()

        pads = self._pads

        if hasattr(pads, "ce_t"):
            m.d.comb += [
                pads.ce_t.oe.eq(1),
                pads.ce_t.o.eq(~self.ce),
            ]
        if hasattr(pads, "oe_t"):
            m.d.comb += [
                pads.oe_t.oe.eq(1),
                pads.oe_t.o.eq(~self.oe),
            ]
        if hasattr(pads, "we_t"):
            m.d.comb += [
                pads.we_t.oe.eq(1),
                pads.we_t.o.eq(~self.we),
            ]

        m.d.comb += [
            pads.dq_t.oe.eq(~self.oe),
            pads.dq_t.o.eq(self.d),
        ]
        m.submodules += FFSynchronizer(pads.dq_t.i, self.q)

        m.d.comb += [
            pads.a_t.oe.eq(1),
            pads.a_t.o.eq(self.a), # directly drive low bits
        ]

        if hasattr(pads, "a_clk_t") and hasattr(pads, "a_si_t"):
            a_clk = Signal(reset=1)
            a_si  = Signal()
            m.d.comb += [
                pads.a_clk_t.oe.eq(1),
                pads.a_clk_t.o.eq(a_clk),
                pads.a_si_t.oe.eq(1),
                pads.a_si_t.o.eq(a_si),
            ]

            sa_input = self.a[len(pads.a_t.o):]
            sa_latch = Signal(self.a_bits - len(pads.a_t.o))

            sh_cyc = math.ceil(platform.default_clk_frequency / self._sh_freq)
            timer = Signal(range(sh_cyc), reset=sh_cyc - 1)
            count = Signal(range(len(sa_latch) + 1))
            first = Signal(reset=1)

            with m.FSM():
                with m.State("READY"):
                    m.d.sync += first.eq(0)
                    with m.If((sa_latch == sa_input) & ~first):
                        m.d.comb += self.rdy.eq(1)
                    with m.Else():
                        m.d.sync += count.eq(len(sa_latch))
                        m.d.sync += sa_latch.eq(sa_input)
                        m.next = "SHIFT"

                with m.State("SHIFT"):
                    with m.If(timer == 0):
                        m.d.sync += timer.eq(timer.reset)
                        m.d.sync += a_clk.eq(~a_clk)
                        with m.If(a_clk):
                            m.d.sync += a_si.eq(sa_latch[-1])
                            m.d.sync += count.eq(count - 1)
                        with m.Else():
                            m.d.sync += sa_latch.eq(sa_latch.rotate_left(1))
                            with m.If(count == 0):
                                m.next = "READY"
                    with m.Else():
                        m.d.sync += timer.eq(timer - 1)

        else:
            m.d.comb += self.rdy.eq(1)

        return m


class _Command(enum.IntEnum):
    SEEK = 0x01
    INCR = 0x02
    READ = 0x03


class MemoryPROMSubtarget(Elaboratable):
    def __init__(self, bus, in_fifo, out_fifo, rd_delay):
        self.bus      = bus
        self.in_fifo  = in_fifo
        self.out_fifo = out_fifo

        self._rd_delay = rd_delay

    def elaborate(self, platform):
        m = Module()
        m.submodules.bus = bus = self.bus

        in_fifo  = self.in_fifo
        out_fifo = self.out_fifo

        m.d.comb += bus.ce.eq(1)

        with m.FSM():
            a_bytes  = (bus.a_bits  + 7) // 8
            dq_bytes = (bus.dq_bits + 7) // 8
            a_index  = Signal(range(a_bytes  + 1))
            dq_index = Signal(range(dq_bytes + 1))
            a_latch  = Signal(bus.a_bits)
            dq_latch = Signal(bus.dq_bits)

            rd_cyc = (math.ceil(self._rd_delay * platform.default_clk_frequency)
                      + 2) # FFSynchronizer latency
            timer  = Signal(range(rd_cyc + 1))

            with m.State("COMMAND"):
                with m.If(out_fifo.r_rdy):
                    m.d.comb += out_fifo.r_en.eq(1)
                    with m.Switch(out_fifo.r_data):
                        with m.Case(_Command.SEEK):
                            m.d.sync += a_index.eq(0)
                            m.next = "SEEK-RECV"
                        with m.Case(_Command.INCR):
                            m.d.sync += bus.a.eq(bus.a + 1)
                            m.next = "SEEK-WAIT"
                        with m.Case(_Command.READ):
                            m.d.sync += dq_index.eq(0)
                            m.next = "READ-PULSE"
                with m.Else():
                    m.d.comb += in_fifo.flush.eq(1)

            with m.State("SEEK-RECV"):
                with m.If(a_index == a_bytes):
                    m.d.sync += bus.a.eq(a_latch)
                    m.next = "SEEK-WAIT"
                with m.Elif(self.out_fifo.r_rdy):
                    m.d.comb += self.out_fifo.r_en.eq(1)
                    m.d.sync += a_latch.word_select(a_index, 8).eq(self.out_fifo.r_data)
                    m.d.sync += a_index.eq(a_index + 1)

            with m.State("SEEK-WAIT"):
                with m.If(bus.rdy):
                    m.next = "COMMAND"

            with m.State("READ-PULSE"):
                m.d.sync += bus.oe.eq(1)
                m.d.sync += timer.eq(rd_cyc)
                m.next = "READ-WAIT"

            with m.State("READ-WAIT"):
                with m.If(timer == 0):
                    m.d.sync += bus.oe.eq(0)
                    m.d.sync += dq_latch.eq(bus.q)
                    m.next = "READ-SEND"
                with m.Else():
                    m.d.sync += timer.eq(timer - 1)

            with m.State("READ-SEND"):
                with m.If(dq_index == dq_bytes):
                    m.next = "COMMAND"
                with m.Elif(self.in_fifo.w_rdy):
                    m.d.comb += self.in_fifo.w_en.eq(1)
                    m.d.comb += self.in_fifo.w_data.eq(dq_latch.word_select(dq_index, 8))
                    m.d.sync += dq_index.eq(dq_index + 1)

        return m


class MemoryPROMInterface:
    class Data:
        def __init__(self, raw_data, dq_bytes):
            self.raw_data = raw_data
            self.dq_bytes = dq_bytes

        def __len__(self):
            return len(self.raw_data) // self.dq_bytes

        def __getitem__(self, index):
            if index not in range(len(self)):
                raise IndexError
            elem = self.raw_data[index * self.dq_bytes:(index + 1) * self.dq_bytes]
            return int.from_bytes(elem, byteorder="little")

        def __eq__(self, other):
            return isinstance(other, type(self)) and self.raw_data == other.raw_data

        def difference(self, other):
            assert isinstance(other, type(self)) and len(self) == len(other)
            raw_diff = ((int.from_bytes(self.raw_data, "little") ^
                         int.from_bytes(other.raw_data, "little"))
                        .to_bytes(len(self.raw_data), "little"))
            return set(m.start() // self.dq_bytes for m in re.finditer(rb"[^\x00]", raw_diff))

    def __init__(self, interface, logger, a_bits, dq_bits):
        self.lower    = interface
        self._logger  = logger
        self._level   = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self.a_bytes  = (a_bits  + 7) // 8
        self.dq_bytes = (dq_bits + 7) // 8

    def _log(self, message, *args):
        self._logger.log(self._level, "PROM: " + message, *args)

    async def read_linear(self, address, count):
        self._log("read linear a=%#x n=%d", address, count)
        await self.lower.write([
            _Command.SEEK,
            *address.to_bytes(self.a_bytes, byteorder="little"),
            *[
                _Command.READ,
                _Command.INCR,
            ] * count,
        ])

        data = self.Data(await self.lower.read(count * self.dq_bytes), self.dq_bytes)
        self._log("read linear q=<%s>",
                  dump_mapseq(" ", lambda q: f"{q:0{self.dq_bytes * 2}x}", data))
        return data

    async def read_shuffled(self, address, count):
        self._log("read shuffled a=%#x n=%d", address, count)
        order = [offset for offset in range(count)]
        random.shuffle(order)
        commands = []
        for offset in order:
            commands += [
                _Command.SEEK,
                *(address + offset).to_bytes(self.a_bytes, byteorder="little"),
                _Command.READ,
            ]
        await self.lower.write(commands)

        linear_raw_chunks = [None for _ in range(count)]
        shuffled_raw_data = await self.lower.read(count * self.dq_bytes)
        for shuffled_offset, linear_offset in enumerate(order):
            linear_raw_chunks[linear_offset] = \
                shuffled_raw_data[shuffled_offset * self.dq_bytes:
                                 (shuffled_offset + 1) * self.dq_bytes]
        data = self.Data(b"".join(linear_raw_chunks), self.dq_bytes)
        self._log("read shuffled q=<%s>",
                  dump_mapseq(" ", lambda q: f"{q:0{self.dq_bytes * 2}x}", data))
        return data


class MemoryPROMApplet(GlasgowApplet, name="memory-prom"):
    logger = logging.getLogger(__name__)
    help = "read parallel (E)EPROM memories"
    description = """
    Read parallel memories compatible with 27/28/29-series read-only memory, such as Microchip
    27C512, Atmel AT28C64B, Atmel AT29C010A, or hundreds of other memories that typically have
    "27X"/"28X"/"29X" where X is a letter in their part number. This applet can also read any other
    directly addressable memory.

    Floating gate based memories (27x EPROM, 28x EEPROM, 29x Flash) retain data for decades, but
    not indefinitely, since the stored charge slowly decays. This applet can identify memories at
    risk of data loss and estimate the level of decay. See `health --help` for details.

    To handle the large amount of address lines used by parallel memories, this applet supports
    two kinds of addressing: direct and indirect. The full address word (specified with
    the --a-bits option) is split into low and high parts. The low part is presented directly on
    the IO pins (specified with the --pins-a option). The high part is presented through
    a SIPO shift register (clock and data input specified with the --pin-a-clk and --pin-a-si
    options respectively), such as a chain of 74HC164 ICs of the appropriate length.
    """

    __pin_sets = ("dq", "a")
    __pins = ("a_clk", "a_si", "oe", "we", "ce")

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_set_argument(parser, "dq", width=range(1, 16), default=8)
        access.add_pin_set_argument(parser, "a",  width=range(0, 24), default=0)
        access.add_pin_argument(parser, "a-clk")
        access.add_pin_argument(parser, "a-si")
        access.add_pin_argument(parser, "oe")
        access.add_pin_argument(parser, "we")
        access.add_pin_argument(parser, "ce")

        parser.add_argument(
            "--a-bits", metavar="COUNT", type=int,
            help="set total amount of address lines to COUNT "
                 "(includes direct and indirect lines)")
        parser.add_argument(
            "--shift-freq", metavar="FREQ", type=float, default=12,
            help="set indirect address shift frequency to FREQ MHz (default: %(default)s)")
        parser.add_argument(
            "--read-latency", metavar="LATENCY", type=float, default=500,
            help="set read latency to LATENCY ns "
                 "(use greater of A→Q and OE→Q, default: %(default)s)")

    def build(self, target, args):
        if args.a_bits is None:
            args.a_bits = len(args.pin_set_a)

        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        bus = MemoryPROMBus(
            pads=iface.get_pads(args, pins=self.__pins, pin_sets=self.__pin_sets),
            a_bits=args.a_bits,
            sh_freq=args.shift_freq * 1e6,
        )
        iface.add_subtarget(MemoryPROMSubtarget(
            bus=bus,
            in_fifo=iface.get_in_fifo(auto_flush=False),
            out_fifo=iface.get_out_fifo(),
            rd_delay=1e-9 * args.read_latency,
        ))

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        return MemoryPROMInterface(iface, self.logger, args.a_bits, len(args.pin_set_dq))

    @classmethod
    def add_interact_arguments(cls, parser):
        def address(arg):
            return int(arg, 0)
        def length(arg):
            return int(arg, 0)

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

        p_read = p_operation.add_parser(
            "read", help="read memory")
        p_read.add_argument(
            "address", metavar="ADDRESS", type=address,
            help="read memory starting at address ADDRESS, with wraparound")
        p_read.add_argument(
            "length", metavar="LENGTH", type=length,
            help="read LENGTH bytes from memory")
        p_read.add_argument(
            "-f", "--file", metavar="FILENAME", type=argparse.FileType("wb"),
            help="write memory contents to FILENAME")
        p_read.add_argument(
            "-e", "--endian", choices=("little", "big"), default="little",
            help="write to file using given endianness")

        p_verify = p_operation.add_parser(
            "verify", help="verify memory")
        p_verify.add_argument(
            "address", metavar="ADDRESS", type=address,
            help="verify memory starting at address ADDRESS")
        p_verify.add_argument(
            "-f", "--file", metavar="FILENAME", type=argparse.FileType("rb"), required=True,
            help="compare memory with contents of FILENAME")
        p_verify.add_argument(
            "-e", "--endian", choices=("little", "big"), default="little",
            help="read from file using given endianness")

        p_health = p_operation.add_parser(
            "health", help="estimate floating gate charge decay")

        p_health_mode = p_health.add_subparsers(dest="mode", metavar="MODE", required=True)

        p_health_check = p_health_mode.add_parser(
            "check", help="rapidly triage a memory")
        p_health_check.add_argument(
            "--passes", metavar="COUNT", type=int, default=5,
            help="read entire memory COUNT times (default: %(default)s)")

        p_health_scan = p_health_mode.add_parser(
            "scan", help="detect decayed words in a memory")
        p_health_scan.add_argument(
            "--confirmations", metavar="COUNT", type=int, default=10,
            help="read entire memory repeatedly until COUNT consecutive passes "
                 "detect no new decayed words (default: %(default)s)")
        p_health_scan.add_argument(
            "-f", "--file", metavar="FILENAME", type=argparse.FileType("wt"),
            help="write hex addresses of decayed cells to FILENAME")

    async def interact(self, device, args, prom_iface):
        a_bits  = args.a_bits
        dq_bits = len(args.pin_set_dq)
        depth   = 1 << a_bits

        if args.operation == "read":
            data = await prom_iface.read_linear(args.address, args.length)
            for word in data:
                if args.file:
                    args.file.write(word.to_bytes(prom_iface.dq_bytes, args.endian))
                else:
                    print("{:0{}x}".format(word, (dq_bits + 3) // 4))

        if args.operation == "verify":
            golden_data = prom_iface.Data(args.file.read(), prom_iface.dq_bytes)
            actual_data = await prom_iface.read_linear(args.address, len(golden_data))
            if actual_data == golden_data:
                self.logger.info("verify PASS")
            else:
                raise GlasgowAppletError("verify FAIL")

        if args.operation == "health" and args.mode == "check":
            decayed = set()
            initial_data = await prom_iface.read_linear(0, depth)

            for pass_num in range(args.passes):
                self.logger.info("pass %d", pass_num)

                current_data = await prom_iface.read_shuffled(0, depth)
                current_decayed = initial_data.difference(current_data)
                for index in sorted(current_decayed - decayed):
                    self.logger.warning("word %#x decayed", index)
                decayed.update(current_decayed)

                if decayed:
                    raise GlasgowAppletError("health check FAIL")

            self.logger.info("health %s PASS", args.mode)

        if args.operation == "health" and args.mode == "scan":
            decayed = set()
            initial_data = await prom_iface.read_linear(0, depth)

            pass_num = 0
            consecutive = 0
            while consecutive < args.confirmations:
                self.logger.info("pass %d", pass_num)
                pass_num += 1
                consecutive += 1

                current_data = await prom_iface.read_shuffled(0, depth)
                current_decayed = initial_data.difference(current_data)
                for index in sorted(current_decayed - decayed):
                    self.logger.warning("word %#x decayed", index)
                    consecutive = 0
                decayed.update(current_decayed)

            if args.file:
                for index in sorted(decayed):
                    args.file.write(f"{index:x}\n")

            if not decayed:
                self.logger.info("health %s PASS", args.mode)
            else:
                raise GlasgowAppletError("health scan FAIL ({} words decayed)"
                                         .format(len(decayed)))

# -------------------------------------------------------------------------------------------------

class MemoryPROMAppletTestCase(GlasgowAppletTestCase, applet=MemoryPROMApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
