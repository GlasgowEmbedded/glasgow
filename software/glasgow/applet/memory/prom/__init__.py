# Ref: Microchip 27C512A 512K (64K x 8) CMOS EPROM
# Accession: G00057

import re
import enum
import math
import json
import random
import logging
import asyncio
import argparse
import statistics
from nmigen import *
from nmigen.lib.cdc import FFSynchronizer
from nmigen.lib.fifo import SyncFIFOBuffered

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
            a_lat = Signal(reset=0) if hasattr(pads, "a_lat_t") else None
            m.d.comb += [
                pads.a_clk_t.oe.eq(1),
                pads.a_clk_t.o.eq(a_clk),
                pads.a_si_t.oe.eq(1),
                pads.a_si_t.o.eq(a_si),
            ]
            if a_lat is not None:
                m.d.comb += [
                    pads.a_lat_t.oe.eq(1),
                    pads.a_lat_t.o.eq(a_lat)
                ]

            # "sa" is the sliced|shifted address, refering to the top-most bits
            sa_input = self.a[len(pads.a_t.o):]
            # This represents a buffer of those high address bits,
            # not to be confused with the latch pin.
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
                                if a_lat is None:
                                    m.next = "READY"
                                else:
                                    m.next = "LATCH-1"
                    with m.Else():
                        m.d.sync += timer.eq(timer - 1)

                if a_lat is not None:
                    with m.State("LATCH-1"):
                        m.d.sync += a_lat.eq(1)
                        with m.If(timer == 0):
                            m.d.sync += timer.eq(timer.reset)
                            m.next = "LATCH-2"
                        with m.Else():
                            m.d.sync += timer.eq(timer - 1)

                    with m.State("LATCH-2"):
                        with m.If(timer == 0):
                            m.d.sync += timer.eq(timer.reset)
                            m.d.sync += a_lat.eq(0)
                            m.next = "READY"
                        with m.Else():
                            m.d.sync += timer.eq(timer - 1)

        else:
            m.d.comb += self.rdy.eq(1)

        return m


class _Command(enum.IntEnum):
    QUEUE = 0x00
    RUN   = 0x01
    SEEK  = 0x02
    INCR  = 0x03
    READ  = 0x04
    WRITE = 0x05
    POLL  = 0x06


_COMMAND_BUFFER_SIZE = 1024


class MemoryPROMSubtarget(Elaboratable):
    def __init__(self, bus, in_fifo, out_fifo,
                 read_cycle_delay, write_cycle_delay, write_hold_delay):
        self.bus      = bus
        self.in_fifo  = in_fifo
        self.out_fifo = out_fifo

        self._read_cycle_delay  = read_cycle_delay
        self._write_cycle_delay = write_cycle_delay
        self._write_hold_delay  = write_hold_delay

    def elaborate(self, platform):
        m = Module()
        m.submodules.bus = bus = self.bus

        in_fifo  = self.in_fifo
        out_fifo = self.out_fifo
        buf_fifo = m.submodules.buf_fifo = SyncFIFOBuffered(width=8, depth=_COMMAND_BUFFER_SIZE)

        m.d.comb += bus.ce.eq(1)

        with m.FSM():
            # Page writes in parallel EEPROMs do not tolerate delays, so the entire page needs
            # to be buffered before programming starts. After receiving the QUEUE command, all
            # subsequent commands except for RUN are placed into the buffer. The RUN command
            # restarts command processing. Until the buffer is empty, only buffered commands are
            # processed.
            cmd_fifo = Array([out_fifo, buf_fifo])[buf_fifo.r_rdy]

            a_bytes  = (bus.a_bits  + 7) // 8
            dq_bytes = (bus.dq_bits + 7) // 8
            a_index  = Signal(range(a_bytes  + 1))
            dq_index = Signal(range(dq_bytes + 1))
            a_latch  = Signal(bus.a_bits)
            dq_latch = Signal(bus.dq_bits)

            read_cycle_cyc  = (math.ceil(self._read_cycle_delay * platform.default_clk_frequency)
                               + 2) # FFSynchronizer latency
            write_cycle_cyc = math.ceil(self._write_cycle_delay * platform.default_clk_frequency)
            write_hold_cyc  = math.ceil(self._write_hold_delay  * platform.default_clk_frequency)
            timer = Signal(range(max(read_cycle_cyc, write_cycle_cyc, write_hold_cyc) + 1))

            with m.State("COMMAND"):
                with m.If(cmd_fifo.r_rdy):
                    m.d.comb += cmd_fifo.r_en.eq(1)
                    with m.Switch(cmd_fifo.r_data):
                        with m.Case(_Command.QUEUE):
                            m.next = "QUEUE-RECV"
                        with m.Case(_Command.SEEK):
                            m.d.sync += a_index.eq(0)
                            m.next = "SEEK-RECV"
                        with m.Case(_Command.INCR):
                            m.d.sync += bus.a.eq(bus.a + 1)
                            m.next = "SEEK-WAIT"
                        with m.Case(_Command.READ):
                            m.d.sync += dq_index.eq(0)
                            m.next = "READ-PULSE"
                        with m.Case(_Command.WRITE):
                            m.d.sync += dq_index.eq(0)
                            m.next = "WRITE-RECV"
                        with m.Case(_Command.POLL):
                            m.next = "POLL-PULSE"
                with m.Else():
                    m.d.comb += in_fifo.flush.eq(1)

            with m.State("QUEUE-RECV"):
                with m.If(out_fifo.r_rdy):
                    escaped = Signal()
                    with m.If(~escaped & (out_fifo.r_data == _Command.QUEUE)):
                        m.d.comb += out_fifo.r_en.eq(1)
                        m.d.sync += escaped.eq(1)
                    with m.Elif(escaped & (out_fifo.r_data == _Command.RUN)):
                        m.d.comb += out_fifo.r_en.eq(1)
                        m.next = "COMMAND"
                    with m.Else():
                        m.d.sync += escaped.eq(0)
                        m.d.comb += out_fifo.r_en.eq(buf_fifo.w_rdy)
                        m.d.comb += buf_fifo.w_data.eq(out_fifo.r_data)
                        m.d.comb += buf_fifo.w_en.eq(1)

            with m.State("SEEK-RECV"):
                with m.If(a_index == a_bytes):
                    m.d.sync += bus.a.eq(a_latch)
                    m.next = "SEEK-WAIT"
                with m.Elif(cmd_fifo.r_rdy):
                    m.d.comb += cmd_fifo.r_en.eq(1)
                    m.d.sync += a_latch.word_select(a_index, 8).eq(cmd_fifo.r_data)
                    m.d.sync += a_index.eq(a_index + 1)

            with m.State("SEEK-WAIT"):
                with m.If(bus.rdy):
                    m.next = "COMMAND"

            with m.State("READ-PULSE"):
                m.d.sync += bus.oe.eq(1)
                m.d.sync += timer.eq(read_cycle_cyc)
                m.next = "READ-CYCLE"

            with m.State("READ-CYCLE"):
                with m.If(timer == 0):
                    # Normally, this would be the place to deassert OE. However, this would reduce
                    # metastability (during burst reads) in the output buffers of a memory that is
                    # reading bits close to the buffer threshold. Wait, isn't metastability bad?
                    # Normally yes, but this is a special case! Metastability causes unstable
                    # bits, and unstable bits reduce the chance that corrupt data will slip
                    # through undetected.
                    m.d.sync += dq_latch.eq(bus.q)
                    m.next = "READ-SEND"
                with m.Else():
                    m.d.sync += timer.eq(timer - 1)

            with m.State("READ-SEND"):
                with m.If(dq_index == dq_bytes):
                    m.next = "COMMAND"
                with m.Elif(in_fifo.w_rdy):
                    m.d.comb += in_fifo.w_en.eq(1)
                    m.d.comb += in_fifo.w_data.eq(dq_latch.word_select(dq_index, 8))
                    m.d.sync += dq_index.eq(dq_index + 1)

            with m.State("WRITE-RECV"):
                with m.If(dq_index == dq_bytes):
                    m.d.sync += bus.d.eq(dq_latch)
                    m.d.sync += bus.oe.eq(0) # see comment in READ-CYCLE
                    m.d.sync += bus.we.eq(1)
                    m.d.sync += timer.eq(write_cycle_cyc)
                    m.next = "WRITE-CYCLE"
                with m.Elif(cmd_fifo.r_rdy):
                    m.d.comb += cmd_fifo.r_en.eq(1)
                    m.d.sync += dq_latch.word_select(dq_index, 8).eq(cmd_fifo.r_data)
                    m.d.sync += dq_index.eq(dq_index + 1)

            with m.State("WRITE-CYCLE"):
                with m.If(timer == 0):
                    m.d.sync += bus.we.eq(0)
                    m.d.sync += timer.eq(write_hold_cyc)
                    m.next = "WRITE-HOLD"
                with m.Else():
                    m.d.sync += timer.eq(timer - 1)

            with m.State("WRITE-HOLD"):
                with m.If(timer == 0):
                    m.next = "COMMAND"
                with m.Else():
                    m.d.sync += timer.eq(timer - 1)

            with m.State("POLL-PULSE"):
                m.d.sync += bus.oe.eq(1)
                m.d.sync += timer.eq(read_cycle_cyc)
                m.next = "POLL-CYCLE"

            with m.State("POLL-CYCLE"):
                with m.If(timer == 0):
                    # There are many different ways EEPROMs can signal readiness, but if they do it
                    # on data lines, they are common in that they all present something else other
                    # than the last written byte on DQ lines.
                    with m.If(bus.q == dq_latch):
                        with m.If(in_fifo.w_rdy):
                            m.d.comb += in_fifo.w_en.eq(1)
                            m.d.sync += bus.oe.eq(0)
                            m.next = "COMMAND"
                with m.Else():
                    m.d.sync += timer.eq(timer - 1)

        return m


class MemoryPROMInterface:
    class Data:
        def __init__(self, raw_data, dq_bytes, endian="little"):
            assert isinstance(raw_data, (bytes, bytearray, memoryview))
            assert isinstance(dq_bytes, int)
            assert endian in ("little", "big")
            self.raw_data = raw_data
            self.dq_bytes = dq_bytes
            self.endian   = endian

        def __bytes__(self):
            return bytes(self.raw_data)

        def __len__(self):
            return len(self.raw_data) // self.dq_bytes

        def __getitem__(self, key):
            n = len(self)
            if isinstance(key, int):
                if key not in range(-n, n):
                    raise IndexError("Cannot index {} words into {}-word data".format(key, n))
                if key < 0:
                    key += n
                elem = self.raw_data[key * self.dq_bytes:(key + 1) * self.dq_bytes]
                return int.from_bytes(elem, byteorder=self.endian)
            elif isinstance(key, slice):
                start, stop, step = key.indices(n)
                return [self[index] for index in range(start, stop, step)]
            else:
                raise TypeError("Cannot index value with {}".format(repr(key)))

            if index not in range(len(self)):
                raise IndexError

        def __eq__(self, other):
            if not isinstance(other, type(self)):
                return False
            if self.endian != other.endian:
                return self == other.convert(self.endian)
            return self.raw_data == other.raw_data

        def convert(self, endian):
            if endian == self.endian:
                return self
            return type(self)(b"".join(elem.to_bytes(self.dq_bytes, byteorder=endian)
                                       for elem in self),
                              self.dq_bytes, endian)

        def difference(self, other):
            assert (isinstance(other, type(self)) and len(self) == len(other) and
                    self.endian == other.endian)
            raw_diff = ((int.from_bytes(self.raw_data,  "little") ^
                         int.from_bytes(other.raw_data, "little"))
                        .to_bytes(len(self.raw_data), "little"))
            diff = dict()
            for m in re.finditer(rb"[^\x00]", raw_diff):
                index = m.start() // self.dq_bytes
                diff[index] = (self[index], other[index])
            return diff

    def __init__(self, interface, logger, a_bits, dq_bits):
        self.lower    = interface
        self._logger  = logger
        self._level   = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self.a_bytes  = (a_bits  + 7) // 8
        self.dq_bytes = (dq_bits + 7) // 8

    def _log(self, message, *args):
        self._logger.log(self._level, "PROM: " + message, *args)

    async def read(self, address, count):
        self._log("read a=%#x n=%d", address, count)
        await self.lower.write([
            _Command.SEEK,
            *address.to_bytes(self.a_bytes, byteorder="little"),
            *[
                _Command.READ,
                _Command.INCR,
            ] * count,
        ])

        data = self.Data(await self.lower.read(count * self.dq_bytes), self.dq_bytes)
        self._log("read q=<%s>",
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

    async def write(self, address, data):
        self._log("write a=%#x d=<%s>",
                  address, dump_mapseq(" ", lambda q: f"{q:0{self.dq_bytes * 2}x}", data))
        commands = []
        for index, word in enumerate(data):
            if index > 0:
                commands += [_Command.INCR]
            commands += [
                _Command.WRITE,
                *word.to_bytes(self.dq_bytes, byteorder="little"),
            ]
        # Add escape sequences for our framing.
        for index in range(len(commands))[::-1]:
            if commands[index] == _Command.QUEUE.value:
                commands[index:index] = [_Command.QUEUE]

        # Some EEPROMs handle page writes by requiring every byte within a page to be written
        # within a fixed time interval from the previous byte. To ensure this, we queue all of
        # the writes first, and then perform them in a deterministic sequence with minimal delay.
        assert len(commands) <= _COMMAND_BUFFER_SIZE
        await self.lower.write([
            _Command.SEEK,
            *address.to_bytes(self.a_bytes, byteorder="little"),
            _Command.QUEUE,
            *commands,
            _Command.QUEUE,
            _Command.RUN,
        ])

    async def poll(self):
        self._log("poll")
        await self.lower.write([
            _Command.POLL,
        ])
        await self.lower.read(1)


class MemoryPROMApplet(GlasgowApplet, name="memory-prom"):
    logger = logging.getLogger(__name__)
    help = "read and rescue parallel EPROMs, EEPROMs, and Flash memories"
    description = """
    Read parallel memories compatible with 27/28/29-series read-only memory, such as Microchip
    27C512, Atmel AT28C64B, Atmel AT29C010A, or hundreds of other memories that typically have
    "27X"/"28X"/"29X" where X is a letter in their part number. This applet can also read any other
    directly addressable memory, such as a mask ROM or a fully combinatorial GAL/PAL.

    Floating gate based memories (27x EPROM, 28x EEPROM, 29x Flash) retain data for decades, but
    not indefinitely, since the stored charge slowly decays. This applet can identify memories at
    risk of data loss, estimate the level of decay, and suggest conditions under which the memory
    may still be read reliably. See `health --help` for details.

    To handle the large amount of address lines used by parallel memories, this applet supports
    two kinds of addressing: direct and indirect. The full address word (specified with
    the --a-bits option) is split into low and high parts. The low part is presented directly on
    the IO pins (specified with the --pins-a option). The high part is presented through
    a SIPO shift register (clock and data input specified with the --pin-a-clk and --pin-a-si
    options respectively), such as a chain of 74HC164 ICs of the appropriate length.
    Additionally, for shift registers with latches, specify --pin-a-lat to drive the latch pins.
    """

    __pin_sets = ("dq", "a")
    __pins = ("a_clk", "a_si", "a_lat", "oe", "we", "ce")

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_set_argument(parser, "dq", width=range(1, 16), default=8)
        access.add_pin_set_argument(parser, "a",  width=range(0, 24), default=0)
        access.add_pin_argument(parser, "a-clk")
        access.add_pin_argument(parser, "a-si")
        access.add_pin_argument(parser, "a-lat")
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
            "--read-cycle", metavar="DELAY", type=float, default=500,
            help="set read cycle time to DELAY ns (default: %(default)s)")
        parser.add_argument(
            "--write-cycle", metavar="DELAY", type=float, default=None,
            help="set write cycle time to DELAY ns (default: same as read cycle time)")
        parser.add_argument(
            "--write-hold", metavar="DELAY", type=float, default=500,
            help="set write hold time to DELAY ns (default: %(default)s)")

    def build(self, target, args):
        if args.a_bits is None:
            args.a_bits = len(args.pin_set_a)
        if args.write_cycle is None:
            args.write_cycle = args.read_cycle

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
            read_cycle_delay=1e-9 * args.read_cycle,
            write_cycle_delay=1e-9 * args.write_cycle,
            write_hold_delay=1e-9 * args.write_hold,
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
        def voltage_range(arg):
            m = re.match(r"^(\d+(?:\.\d*)?):(\d+(?:\.\d*)?)$", arg)
            if not m:
                raise argparse.ArgumentTypeError("'{}' is not a voltage range".format(arg))
            return float(m[1]), float(m[2])

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

        def add_endian_argument(parser):
            parser.add_argument(
                "-e", "--endian", choices=("little", "big"), default="little",
                help="operate on files with the specified endianness (default: %(default)s)")

        p_read = p_operation.add_parser(
            "read", help="read memory")
        p_read.add_argument(
            "address", metavar="ADDRESS", type=address, nargs="?", default=0,
            help="read memory starting at address ADDRESS, with wraparound")
        p_read.add_argument(
            "length", metavar="LENGTH", type=length, nargs="?",
            help="read LENGTH bytes from memory")
        p_read.add_argument(
            "-f", "--file", metavar="FILENAME", type=argparse.FileType("wb"),
            help="write memory contents to FILENAME")
        add_endian_argument(p_read)

        p_verify = p_operation.add_parser(
            "verify", help="verify memory")
        p_verify.add_argument(
            "address", metavar="ADDRESS", type=address, nargs="?", default=0,
            help="verify memory starting at address ADDRESS")
        p_verify.add_argument(
            "-f", "--file", metavar="FILENAME", type=argparse.FileType("rb"), required=True,
            help="compare memory with contents of FILENAME")
        add_endian_argument(p_verify)

        def add_write_arguments(parser):
            parser.add_argument(
                "address", metavar="ADDRESS", type=address, nargs="?", default=0,
                help="write memory starting at address ADDRESS")
            parser.add_argument(
                "-f", "--file", metavar="FILENAME", type=argparse.FileType("rb"), required=True,
                help="write contents of FILENAME to memory")
            add_endian_argument(parser)

        p_write = p_operation.add_parser(
            "write", help="write memory")
        add_write_arguments(p_write)

        p_atmel = p_operation.add_parser(
            "atmel", help="Atmel vendor-specific commands")

        p_atmel_operation = p_atmel.add_subparsers(dest="vendor_operation",
                                                   metavar="VENDOR-OPERATION", required=True)

        p_atmel_write = p_atmel_operation.add_parser(
            "write", help="write EEPROM or Flash sector-wise")
        p_atmel_write.add_argument(
            "-S", "--sector-size", metavar="WORDS", type=int, required=True,
            help="perform read-modify-write on WORDS-aligned blocks")
        add_write_arguments(p_atmel_write)

        p_health = p_operation.add_parser(
            "health", help="manage floating gate charge decay")

        p_health_mode = p_health.add_subparsers(dest="mode", metavar="MODE", required=True)

        p_health_check = p_health_mode.add_parser(
            "check", help="quickly probe for unstable words in a memory")
        p_health_check.add_argument(
            "--samples", metavar="COUNT", type=int, default=5,
            help="read entire memory COUNT times (default: %(default)s)")

        p_health_scan = p_health_mode.add_parser(
            "scan", help="exhaustively detect unstable words in a memory")
        p_health_scan.add_argument(
            "--confirmations", metavar="COUNT", type=int, default=10,
            help="read entire memory repeatedly until COUNT consecutive samples "
                 "detect no new unstable words (default: %(default)s)")
        p_health_scan.add_argument(
            "-f", "--file", metavar="FILENAME", type=argparse.FileType("wt"),
            help="write hex addresses of unstable cells to FILENAME")

        p_health_sweep = p_health_mode.add_parser(
            "sweep", help="determine undervolt offset that prevents instability")
        p_health_sweep.add_argument(
            "--samples", metavar="COUNT", type=int, default=5,
            help="read entire memory COUNT times (default: %(default)s)")
        p_health_sweep.add_argument(
            "--voltage-step", metavar="STEP", type=float, default=0.05,
            help="reduce supply voltage by STEP volts (default: %(default)s)")

        p_health_popcount = p_health_mode.add_parser(
            "popcount", help="sample population count for a voltage range")
        p_health_popcount.add_argument(
            "--samples", metavar="COUNT", type=int, default=5,
            help="average population count COUNT times (default: %(default)s)")
        p_health_popcount.add_argument(
            "--sweep", metavar="START:END", type=voltage_range, required=True,
            help="sweep supply voltage from START to END volts")
        p_health_popcount.add_argument(
            "--voltage-step", metavar="STEP", type=float, default=0.05,
            help="change supply voltage by STEP volts (default: %(default)s)")
        p_health_popcount.add_argument(
            "file", metavar="FILENAME", type=argparse.FileType("wt"),
            help="write aggregated data to FILENAME")

    async def interact(self, device, args, prom_iface):
        a_bits  = args.a_bits
        dq_bits = len(args.pin_set_dq)
        depth   = 1 << a_bits

        if args.operation == "read":
            if args.length is None:
                args.length = depth

            data = await prom_iface.read(args.address, args.length)
            if args.file:
                args.file.write(data.convert(args.endian).raw_data)
            else:
                for word in data:
                    print("{:0{}x}".format(word, (dq_bits + 3) // 4))

        if args.operation == "verify":
            golden_data = prom_iface.Data(args.file.read(), prom_iface.dq_bytes, args.endian)
            actual_data = await prom_iface.read(args.address, len(golden_data))
            if actual_data == golden_data:
                self.logger.info("verify PASS")
            else:
                differ = sum(a != b for a, b in zip(golden_data, actual_data))
                raise GlasgowAppletError("verify FAIL ({} words differ)"
                                         .format(differ))

        if args.operation == "write":
            data = prom_iface.Data(args.file.read(), prom_iface.dq_bytes, args.endian)
            self.logger.info("writing %#x+%#x", args.address, len(data))
            await prom_iface.write(args.address, data)

        if args.operation == "atmel" and args.vendor_operation == "write":
            data = prom_iface.Data(args.file.read(), prom_iface.dq_bytes, args.endian)
            offset = 0
            for address in range(args.address, args.address + len(data) + args.sector_size - 1,
                                 args.sector_size):
                length = min(args.address + len(data),
                             (address + args.sector_size) & ~(args.sector_size - 1)) - address
                if length <= 0:
                    break
                self.logger.info("writing %#x+%#x", address, length)
                await prom_iface.write(address, data[offset:offset + length])
                await prom_iface.poll()
                offset += length

        if args.operation == "health" and args.mode == "check":
            unstable = set()
            initial_data = await prom_iface.read(0, depth)

            for sample_num in range(args.samples):
                self.logger.info("sample %d", sample_num)

                current_data = await prom_iface.read_shuffled(0, depth)
                current_unstable = initial_data.difference(current_data)
                for index in sorted(set(current_unstable) - unstable):
                    self.logger.warning("word %#x unstable (%#x != %#x)",
                                        index, initial_data[index], current_data[index])
                unstable.update(current_unstable)

                if unstable:
                    raise GlasgowAppletError("health check FAIL")

            self.logger.info("health check PASS")

        if args.operation == "health" and args.mode == "scan":
            unstable = set()
            initial_data = await prom_iface.read(0, depth)

            sample_num = 0
            consecutive = 0
            while consecutive < args.confirmations:
                self.logger.info("sample %d", sample_num)
                sample_num += 1
                consecutive += 1

                current_data = await prom_iface.read_shuffled(0, depth)
                current_unstable = initial_data.difference(current_data)
                for index in sorted(set(current_unstable) - unstable):
                    self.logger.warning("word %#x unstable (%#x != %#x)",
                                        index, initial_data[index], current_data[index])
                    consecutive = 0
                unstable.update(current_unstable)

            if args.file:
                for index in sorted(unstable):
                    args.file.write(f"{index:x}\n")

            if not unstable:
                self.logger.info("health scan PASS")
            else:
                raise GlasgowAppletError("health scan FAIL ({} words unstable)"
                                         .format(len(unstable)))

        if args.operation == "health" and args.mode == "sweep":
            if args.voltage is None:
                raise GlasgowAppletError("health sweep requires --voltage to be specified")

            voltage  = args.voltage
            step_num = 0
            while True:
                self.logger.info("step %d (%.2f V)", step_num, voltage)
                await device.set_voltage(args.port_spec, voltage)

                initial_data = await prom_iface.read(0, depth)
                for sample_num in range(args.samples):
                    self.logger.info("  sample %d", sample_num)
                    current_data = await prom_iface.read_shuffled(0, depth)
                    unstable = initial_data.difference(current_data)
                    for index in sorted(unstable):
                        self.logger.warning("word %#x unstable (%#x != %#x)",
                                            index, initial_data[index], current_data[index])
                    if unstable:
                        self.logger.warning("step %d FAIL (%d words unstable)",
                                            step_num, len(unstable))
                        break
                else:
                    self.logger.info("step %d PASS", step_num)
                    break

                voltage  -= args.voltage_step
                step_num += 1

            self.logger.info("health %s PASS at %.2f V", args.mode, voltage)

        if args.operation == "health" and args.mode == "popcount":
            voltage_from, voltage_to = args.sweep
            popcount_lut = [format(n, "b").count("1") for n in range(1 << dq_bits)]

            series = []
            voltage = voltage_from
            step_num = 0
            while True:
                self.logger.info("step %d (%.2f V)", step_num, voltage)
                await device.set_voltage(args.port_spec, voltage)

                popcounts = []
                for sample_num in range(args.samples):
                    self.logger.info("  sample %d", sample_num)
                    data = await prom_iface.read_shuffled(0, depth)
                    popcounts.append(sum(popcount_lut[word] for word in data))

                series.append((voltage, popcounts))
                self.logger.info("population %d/%d",
                                 sum(popcounts) // len(popcounts),
                                 depth * dq_bits)

                if voltage_to > voltage_from:
                    voltage += args.voltage_step
                    if voltage > voltage_to: break
                else:
                    voltage -= args.voltage_step
                    if voltage < voltage_to: break
                step_num += 1

            json.dump({
                "density": depth * dq_bits,
                "series": [
                    {"voltage": voltage, "popcounts": popcounts}
                    for voltage, popcounts in series
                ]
            }, args.file)

# -------------------------------------------------------------------------------------------------

class MemoryPROMAppletTool(GlasgowAppletTool, applet=MemoryPROMApplet):
    help = "display statistics of parallel EPROMs, EEPROMs, and Flash memories"
    description = """
    Display statistics collected of parallel memories collected with the `health` subcommand.
    """

    @classmethod
    def add_arguments(cls, parser):
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

        p_popcount = p_operation.add_parser(
            "popcount", help="plot population count for a voltage range")
        p_popcount.add_argument(
            "file", metavar="FILENAME", type=argparse.FileType("rt"),
            help="read aggregated data from FILENAME")

    async def run(self, args):
        if args.operation == "popcount":
            data = json.load(args.file)
            density = data["density"]
            series = [
                (row["voltage"], row["popcounts"], statistics.mean(row["popcounts"]))
                for row in data["series"]
            ]

            min_popcount = min(mean_popcounts for _, _, mean_popcounts in series)
            max_popcount = max(mean_popcounts for _, _, mean_popcounts in series)
            histogram_size = 40
            resolution = max(1, (max_popcount - min_popcount) / histogram_size)
            print(f"Vcc   {str(math.floor(min_popcount)):<{1 + histogram_size // 2}s}"
                        f"{str(math.ceil (max_popcount)):>{1 + histogram_size // 2}s} popcount")
            for voltage, popcounts, mean_popcount in series:
                rectangle_size = math.floor((mean_popcount - min_popcount) / resolution)
                print(f"{voltage:.2f}: |{'1' * rectangle_size:{histogram_size}s}| "
                      f"({len(popcounts)}× {int(mean_popcount)}/{density}, "
                      f"sd {statistics.pstdev(popcounts):.2f})")

# -------------------------------------------------------------------------------------------------

class MemoryPROMAppletTestCase(GlasgowAppletTestCase, applet=MemoryPROMApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
