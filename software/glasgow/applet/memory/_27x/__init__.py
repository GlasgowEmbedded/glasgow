# Ref: Microchip 27C512A 512K (64K x 8) CMOS EPROM
# Accession: G00057

import logging
import asyncio
import argparse
import operator
from nmigen import *

from ... import *


class Memory27xSubtarget(Elaboratable):
    def __init__(self, pads, in_fifo, out_fifo, read_delay):
        self.pads     = pads
        self.in_fifo  = in_fifo
        self.out_fifo = out_fifo

        self.read_delay = read_delay

    def elaborate(self, platform):
        m = Module()

        m.d.comb += self.pads.a_t.oe.eq(1)

        a = Signal.like(self.pads.a_t.o)
        d = Signal.like(self.pads.d_t.i)

        with m.FSM():
            a_bytes = (len(a) + 7) // 8
            d_bytes = (len(d) + 7) // 8
            a_index = Signal(range(a_bytes + 1))
            d_index = Signal(range(d_bytes + 1))

            read_cyc = int(round(self.read_delay * platform.default_clk_frequency))
            timer    = Signal(range(read_cyc + 1))

            with m.State("IDLE"):
                m.d.sync += [
                    a_index.eq(0),
                    d_index.eq(0),
                ]
                m.next = "RECV-ADDRESS"

            with m.State("RECV-ADDRESS"):
                with m.If(a_index == a_bytes):
                    m.d.sync += timer.eq(read_cyc)
                    m.next = "ADDRESS"
                with m.Elif(self.out_fifo.r_rdy):
                    m.d.sync += a_index.eq(a_index + 1)
                    m.d.comb += self.out_fifo.r_en.eq(1)
                    m.d.sync += a.word_select(a_index, 8).eq(self.out_fifo.r_data)

            with m.State("ADDRESS"):
                m.d.sync += self.pads.a_t.o.eq(a)
                with m.If(timer == 0):
                    m.next = "DATA"
                with m.Else():
                    m.d.sync += timer.eq(timer - 1)

            with m.State("DATA"):
                m.d.sync += d.eq(self.pads.d_t.i)
                m.next = "SEND-DATA"

            with m.State("SEND-DATA"):
                with m.If(d_index == d_bytes):
                    m.next = "IDLE"
                with m.Elif(self.in_fifo.w_rdy):
                    m.d.sync += d_index.eq(d_index + 1)
                    m.d.comb += self.in_fifo.w_en.eq(1)
                    m.d.comb += self.in_fifo.w_data.eq(d.word_select(d_index, 8))

        return m


class Memory27xInterface:
    def __init__(self, interface, logger, a_bits, d_bits):
        self.lower    = interface
        self._logger  = logger
        self._level   = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._a_bytes = (a_bits + 7) // 8
        self._d_bytes = (d_bits + 7) // 8

    def _log(self, message, *args):
        self._logger.log(self._level, "27x: " + message, *args)

    async def read(self, address):
        await self.lower.write(operator.index(address).to_bytes(self._a_bytes, byteorder="little"))
        data = int.from_bytes(await self.lower.read(self._d_bytes), byteorder="little")
        self._log("a=%#x d=%#x", address, data)
        return data


class Memory27xApplet(GlasgowApplet, name="memory-27x"):
    logger = logging.getLogger(__name__)
    help = "read 27/28-series parallel (E)EPROM memories"
    preview = True
    description = """
    Read memories compatible with 27-series erasable read-only memory, such as Microchip 27C512,
    Intel 27C256, or hundreds of other memories that typically have "27X" where X is a letter
    in their part number. This applet can also read 28-series electrically erasable read-only
    memory, or any other directly addressable parallel memory.
    """

    __pin_sets = ("a", "d")

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_set_argument(parser, "a", width=range(1, 32), default=8)
        access.add_pin_set_argument(parser, "d", width=range(1, 16), default=8)

        parser.add_argument(
            "--read-latency", metavar="LATENCY", type=int, default=500,
            help="set read latency to LATENCY ns (default: %(default)s)")

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        iface.add_subtarget(Memory27xSubtarget(
            pads=iface.get_pads(args, pin_sets=self.__pin_sets),
            in_fifo=iface.get_in_fifo(),
            out_fifo=iface.get_out_fifo(),
            read_delay=1e-9 * args.read_latency,
        ))

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        return Memory27xInterface(iface, self.logger, len(args.pin_set_a), len(args.pin_set_d))

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

    async def interact(self, device, args, m27x_iface):
        a_bits = len(args.pin_set_a)
        d_bits = len(args.pin_set_d)

        if args.operation == "read":
            for address in range(args.address, args.address + args.length):
                data = await m27x_iface.read(address)
                if args.file:
                    args.file.write(data.to_bytes((d_bits + 7) // 8, byteorder=args.endian))
                else:
                    print("{:x}".format(data))

# -------------------------------------------------------------------------------------------------

class Memory27xAppletTestCase(GlasgowAppletTestCase, applet=Memory27xApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
