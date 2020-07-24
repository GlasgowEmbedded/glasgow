# Ref: Microchip 27C512A 512K (64K x 8) CMOS EPROM
# Accession: G00057

import math
import enum
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
    def __init__(self, interface, logger, a_bits, dq_bits):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        self._a_bytes  = (a_bits  + 7) // 8
        self._dq_bytes = (dq_bits + 7) // 8

    def _log(self, message, *args):
        self._logger.log(self._level, "PROM: " + message, *args)

    async def seek(self, address):
        self._log("seek a=%#x", address)
        await self.lower.write([
            _Command.SEEK,
            *address.to_bytes(self._a_bytes, byteorder="little")
        ])

    async def _read_cmd(self, count, *, incr):
        if incr:
            self._log("read-incr count=%d", count)
            await self.lower.write([_Command.READ, _Command.INCR] * count)
        else:
            self._log("read count=%d", count)
            await self.lower.write([_Command.READ] * count)

    async def read_bytes(self, count, *, incr=False):
        await self._read_cmd(count, incr=incr)

        data = await self.lower.read(count * self._dq_bytes)
        self._log("read q=<%s>", dump_hex(data))
        return data

    async def read_words(self, count, *, incr=False):
        await self._read_cmd(count, incr=incr)

        data = []
        for _ in range(count):
            data.append(int.from_bytes(await self.lower.read(self._dq_bytes), byteorder="little"))
        self._log("read q=<%s>", " ".join(f"{q:x}" for q in data))
        return data


class MemoryPROMApplet(GlasgowApplet, name="memory-prom"):
    logger = logging.getLogger(__name__)
    help = "read parallel (E)EPROM memories"
    description = """
    Read parallel memories compatible with 27/28/29-series read-only memory, such as  Microchip
    27C512, Atmel AT28C64B, Atmel AT29C010A, or hundreds of other memories that typically have
    "27X"/"28X"/"29X" where X is a letter in their part number. This applet can also read any other
    directly addressable memory.

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
            in_fifo=iface.get_in_fifo(),
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

    async def interact(self, device, args, prom_iface):
        a_bits  = args.a_bits
        dq_bits = len(args.pin_set_dq)

        if args.operation == "read":
            await prom_iface.seek(args.address)
            if args.file:
                args.file.write(await prom_iface.read_bytes(args.length, incr=True))
            else:
                for word in await prom_iface.read_words(args.length, incr=True):
                    print("{:0{}x}".format(word, (dq_bits + 3) // 4))

# -------------------------------------------------------------------------------------------------

class MemoryPROMAppletTestCase(GlasgowAppletTestCase, applet=MemoryPROMApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
