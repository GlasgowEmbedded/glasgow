import sys
import logging
import asyncio
import argparse
from amaranth import *
from amaranth.lib import enum, data, wiring, stream, io, cdc
from amaranth.lib.wiring import In, Out
from cobs.cobs import decode as cobs_decode

from glasgow.support.logging import dump_hex
from glasgow.gateware.cobs import Encoder as COBSEncoder
from glasgow.applet import GlasgowAppletError, GlasgowAppletV2


__all__ = ["SPIAnalyzerOverflow", "SPIAnalyzerComponent", "SPIAnalyzerApplet"]


class SPIAnalyzerOverflow(GlasgowAppletError):
    pass


class SPIChannelAnalyzer(wiring.Component):
    cs:   Out(io.Buffer.Signature("i", 1))
    clk:  Out(io.Buffer.Signature("i", 1))
    data: Out(io.Buffer.Signature("i", 1))

    stream: Out(stream.Signature(8))
    flush:  Out(1)

    overflow: Out(1)

    def __init__(self, fifo_depth):
        self._fifo_depth = fifo_depth

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        cs_sync   = Signal()
        clk_sync  = Signal()
        data_sync = Signal()
        m.submodules.cs_sync   = cdc.FFSynchronizer(self.cs.i, cs_sync)
        m.submodules.clk_sync  = cdc.FFSynchronizer(self.clk.i, clk_sync)
        m.submodules.data_sync = cdc.FFSynchronizer(self.data.i, data_sync)

        m.submodules.cobs_encoder = encoder = COBSEncoder(fifo_depth=self._fifo_depth)
        wiring.connect(m, wiring.flipped(self.stream), encoder.o)

        clk_past = Signal.like(clk_sync)
        clk_edge = Signal()
        m.d.sync += clk_past.eq(clk_sync)
        m.d.comb += clk_edge.eq(clk_sync & ~clk_past)

        idle  = Signal(20)
        count = Signal(range(8))
        shreg = Signal(8)
        with m.FSM():
            m.d.comb += encoder.i.p.data.eq(shreg)

            with m.State("Idle"):
                with m.If(cs_sync):
                    m.d.sync += count.eq(0)
                    m.next = "Capture"
                with m.Else():
                    with m.If(idle == 0):
                        m.d.comb += self.flush.eq(1)
                    with m.Else():
                        m.d.sync += idle.eq(idle - 1)

            with m.State("Capture"):
                with m.If(clk_edge):
                    m.d.sync += shreg.eq(Cat(data_sync, shreg))
                    m.d.sync += count.eq(count + 1)
                    with m.If(count == 7):
                        m.d.sync += count.eq(0)
                        m.next = "Submit Data"
                with m.If(~cs_sync):
                    m.next = "Submit End"

            with m.State("Submit Data"):
                m.d.comb += encoder.i.p.end.eq(0)
                m.d.comb += encoder.i.valid.eq(1)
                with m.If(encoder.i.ready):
                    m.next = "Capture"
                with m.If(clk_edge | ~cs_sync):
                    m.next = "Overflow"

            with m.State("Submit End"):
                m.d.comb += encoder.i.p.end.eq(1)
                m.d.comb += encoder.i.valid.eq(1)
                with m.If(encoder.i.ready):
                    m.d.sync += idle.eq(~0)
                    m.next = "Idle"
                with m.If(cs_sync):
                    m.next = "Overflow"

            with m.State("Overflow"):
                m.d.comb += self.flush.eq(1)
                m.d.comb += self.overflow.eq(1)

        return m


class SPIAnalyzerComponent(wiring.Component):
    copi_stream: Out(stream.Signature(8))
    copi_flush:  Out(1)
    cipo_stream: Out(stream.Signature(8))
    cipo_flush:  Out(1)

    overflow: Out(1)

    def __init__(self, ports, *, copi_fifo_depth, cipo_fifo_depth):
        self.ports = ports

        self._copi_fifo_depth = copi_fifo_depth
        self._cipo_fifo_depth = cipo_fifo_depth

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.cs_buffer  = cs_buffer  = io.Buffer("i", ~self.ports.cs)
        m.submodules.sck_buffer = sck_buffer = io.Buffer("i", self.ports.sck)

        if self.ports.copi:
            m.submodules.copi_buffer = copi_buffer = io.Buffer("i", self.ports.copi)
            m.submodules.copi_channel = copi_channel = \
                SPIChannelAnalyzer(fifo_depth=self._copi_fifo_depth)
            wiring.connect(m, copi_channel.cs,   cs_buffer)
            wiring.connect(m, copi_channel.clk,  sck_buffer)
            wiring.connect(m, copi_channel.data, copi_buffer)
            wiring.connect(m, wiring.flipped(self.copi_stream), copi_channel.stream)
            m.d.comb += self.copi_flush.eq(copi_channel.flush)
            with m.If(copi_channel.overflow):
                m.d.comb += self.overflow.eq(1)

        if self.ports.cipo:
            m.submodules.cipo_buffer = cipo_buffer = io.Buffer("i", self.ports.cipo)
            m.submodules.cipo_channel = cipo_channel = \
                SPIChannelAnalyzer(fifo_depth=self._cipo_fifo_depth)
            wiring.connect(m, cipo_channel.cs,   cs_buffer)
            wiring.connect(m, cipo_channel.clk,  sck_buffer)
            wiring.connect(m, cipo_channel.data, cipo_buffer)
            wiring.connect(m, wiring.flipped(self.cipo_stream), cipo_channel.stream)
            m.d.comb += self.cipo_flush.eq(cipo_channel.flush)
            with m.If(cipo_channel.overflow):
                m.d.comb += self.overflow.eq(1)

        return m


class SPIAnalyzerInterface:
    def __init__(self, logger, assembly, *, cs, sck, copi=None, cipo=None, fifo_depth=512):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        ports = assembly.add_port_group(cs=cs, sck=sck, copi=copi, cipo=cipo)
        component = assembly.add_submodule(
            SPIAnalyzerComponent(ports, copi_fifo_depth=fifo_depth, cipo_fifo_depth=fifo_depth))
        # Use the smallest host interface FIFO, since the COBS encoder includes its own, which
        # is more efficient resource-wise as it is combined with the lookahead buffer.
        self._copi_pipe = assembly.add_in_pipe(
            component.copi_stream, in_flush=component.copi_flush, fifo_depth=2)
        self._cipo_pipe = assembly.add_in_pipe(
            component.cipo_stream, in_flush=component.cipo_flush, fifo_depth=2)
        self._overflow = assembly.add_ro_register(component.overflow)

    def _log(self, message, *args):
        self._logger.log(self._level, "SPI analyzer: " + message, *args)

    @staticmethod
    async def _recv_cobs_packet(pipe) -> bytes:
        buffer = bytearray()
        while byte := await pipe.recv(1):
            if byte == b"\x00":
                return cobs_decode(buffer)
            else:
                buffer += byte

    async def capture(self) -> tuple[bytes, bytes]:
        if await self._overflow:
            raise SPIAnalyzerOverflow("overflow")
        copi_data, cipo_data = await asyncio.gather(
            self._recv_cobs_packet(self._copi_pipe),
            self._recv_cobs_packet(self._cipo_pipe))
        self._log("capture copi=<%s> cipo=<%s>", dump_hex(copi_data), dump_hex(cipo_data))
        return (copi_data, cipo_data)


class SPIAnalyzerApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "analyze SPI transactions"
    preview = True
    description = """
    Capture transactions on the SPI bus.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "cs",   required=True, default=True)
        access.add_pins_argument(parser, "sck",  required=True, default=True)
        access.add_pins_argument(parser, "copi", required=True, default=True)
        access.add_pins_argument(parser, "cipo", required=True, default=True)

        parser.add_argument("--fifo-depth", metavar="BYTES", type=int, default=512,
            help="use a hardware FIFO that is BYTES deep (default: %(default)s, up to: 8192)")

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.spi_analyzer_iface = SPIAnalyzerInterface(self.logger, self.assembly,
                cs=args.cs, sck=args.sck, copi=args.copi, cipo=args.cipo,
                fifo_depth=args.fifo_depth)

    @classmethod
    def add_run_arguments(cls, parser):
        parser.add_argument("file", metavar="FILE",
            type=argparse.FileType("w"), nargs="?", default=sys.stdout,
            help="save communications to FILE as pairs of hex sequences")

    async def run(self, args):
        try:
            args.file.truncate()
        except OSError:
            pass # pipe, tty/pty, etc

        while True:
            copi_data, cipo_data = await self.spi_analyzer_iface.capture()
            args.file.write(f"{copi_data.hex()},{cipo_data.hex()}\n")
            args.file.flush()

    @classmethod
    def tests(cls):
        from . import test
        return test.SPIAnalyzerAppletTestCase
