import sys
import logging
import asyncio
import argparse
from amaranth import *
from amaranth.lib import enum, data, wiring, stream, io, cdc
from amaranth.lib.wiring import In, Out
from cobs.cobs import decode as cobs_decode

from glasgow.support.logging import dump_hex
from glasgow.gateware.stream import StreamFIFO
from glasgow.gateware.cobs import Encoder as COBSEncoder
from glasgow.applet import GlasgowAppletError, GlasgowAppletV2


__all__ = ["SPIAnalyzerOverflow", "SPIAnalyzerComponent", "SPIAnalyzerApplet"]


class SPIAnalyzerOverflow(GlasgowAppletError):
    pass


class SPIAnalyzerFrontend(wiring.Component):
    def __init__(self, ports, *, word_width=8, fifo_depth=16):
        self._ports = ports

        self._word_width = word_width
        self._fifo_depth = fifo_depth

        super().__init__({
            "stream": Out(stream.Signature(data.StructLayout({
                "copi":  self._word_width,
                "cipo":  self._word_width,
                "epoch": 1
            }))),
            "overflow": Out(1),
        })

    def elaborate(self, platform):
        m = Module()

        m.submodules.cs_buffer   = cs_buffer   = io.Buffer("i", self._ports.cs)
        m.submodules.sck_buffer  = sck_buffer  = io.Buffer("i", self._ports.sck)
        m.submodules.copi_buffer = copi_buffer = io.Buffer("i", self._ports.copi)
        m.submodules.cipo_buffer = cipo_buffer = io.Buffer("i", self._ports.cipo)

        if platform is not None:
            # Works on iCE40HX8K.
            platform.add_clock_constraint(sck_buffer.i, 100e6)

        # The analyzer frontend is clocked by SPI clock and resynchronized whenever CS# is
        # asserted by using CS# as an active-high reset. This means that frequency of SCK is
        # only limited by the FPGA fabric performance, but introduces several timing hazards
        # that may cause race conditions or metastability and corrupt captured data.
        m.domains.spi = cd_spi = ClockDomain(async_reset=True, local=True)
        m.d.comb += cd_spi.rst.eq(cs_buffer.i)
        m.d.comb += cd_spi.clk.eq(sck_buffer.i)

        # The FIFO contents must not be reset even if the FIFO writer is reset. This creates
        # an unsynchronized CDC path between the FIFO writer and the FIFO, the practical effect
        # of which is that there is a (difficult to specify) hold time constraint between CS#
        # deassertion and preceding SCK edge. This timing hazard is an inherent feature of
        # the approach taken in this component, unfortunately, and is the price to pay for
        # much higher Fmax compared to a fully synchronous approach sampling SCK from sync domain.
        m.domains.fifo = cd_fifo = ClockDomain(reset_less=True, local=True)
        m.d.comb += cd_fifo.clk.eq(sck_buffer.i)

        m.submodules.fifo = fifo = StreamFIFO(
            shape=data.StructLayout({
                "copi": self._word_width,
                "cipo": self._word_width,
                "epoch": 1
            }),
            depth=self._fifo_depth,
            w_domain="fifo",
            r_domain="sync"
        )

        copi_shreg = Signal(self._word_width)
        cipo_shreg = Signal(self._word_width)
        m.d.spi += copi_shreg.eq(Cat(copi_buffer.i, copi_shreg))
        m.d.spi += cipo_shreg.eq(Cat(cipo_buffer.i, cipo_shreg))
        m.d.comb += fifo.w.p.copi.eq(Cat(copi_buffer.i, copi_shreg))
        m.d.comb += fifo.w.p.cipo.eq(Cat(cipo_buffer.i, cipo_shreg))

        start = Signal(init=1)
        epoch = Signal(reset_less=True, init=1)
        count = Signal(range(self._word_width + 1))
        with m.If(count == self._word_width - 1):
            m.d.comb += fifo.w.valid.eq(1)
            with m.If(start):
                m.d.spi += start.eq(0)
                m.d.spi += epoch.eq(~epoch)
                m.d.comb += fifo.w.p.epoch.eq(~epoch)
            with m.Else():
                m.d.comb += fifo.w.p.epoch.eq(epoch)
            m.d.spi += count.eq(0)
        with m.Else():
            m.d.spi += count.eq(count + 1)

        overflow_spi  = Signal()
        with m.If(fifo.w.valid & ~fifo.w.ready):
            m.d.spi += overflow_spi.eq(1)

        wiring.connect(m, wiring.flipped(self.stream), fifo.r)

        overflow_sync = Signal()
        m.submodules.overflow_sync = cdc.FFSynchronizer(overflow_spi, overflow_sync)
        with m.If(overflow_sync):
            m.d.sync += self.overflow.eq(1)

        return m


class SPIAnalyzerComponent(wiring.Component):
    o_stream: Out(stream.Signature(8))
    o_flush:  Out(1)

    overflow: Out(1)

    def __init__(self, ports):
        self.ports = ports

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.frontend = frontend = SPIAnalyzerFrontend(self.ports, fifo_depth=256)
        m.submodules.encoder  = encoder  = COBSEncoder(fifo_depth=512)

        wiring.connect(m, wiring.flipped(self.o_stream), encoder.o)

        epoch = Signal()
        idle  = Signal(20)
        with m.FSM():
            with m.State("COPI"):
                with m.If(frontend.stream.valid):
                    with m.If(frontend.stream.p.epoch != epoch):
                        m.d.comb += encoder.i.p.end.eq(1)
                        m.d.comb += encoder.i.valid.eq(1)
                        with m.If(encoder.i.ready):
                            m.d.sync += epoch.eq(frontend.stream.p.epoch)
                    with m.Else():
                        m.d.comb += encoder.i.p.data.eq(frontend.stream.p.copi)
                        m.d.comb += encoder.i.valid.eq(1)
                        with m.If(encoder.i.ready):
                            m.d.sync += idle.eq(~0)
                            m.next = "CIPO"

                # FIXME: this should be done as a part of the common FX2 logic
                with m.Else():
                    with m.If(idle == 0):
                        m.d.comb += self.o_flush.eq(1)
                    with m.Else():
                        m.d.sync += idle.eq(idle - 1)

            with m.State("CIPO"):
                m.d.comb += encoder.i.p.data.eq(frontend.stream.p.cipo)
                m.d.comb += encoder.i.valid.eq(1)
                with m.If(encoder.i.ready):
                    m.d.comb += frontend.stream.ready.eq(1)
                    m.next = "COPI"

        m.d.comb += self.overflow.eq(frontend.overflow)

        return m


class SPIAnalyzerInterface:
    def __init__(self, logger, assembly, *, cs, sck, copi, cipo):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        ports = assembly.add_port_group(cs=cs, sck=sck, copi=copi, cipo=cipo)
        component = assembly.add_submodule(SPIAnalyzerComponent(ports))
        # Use the smallest host interface FIFO, since the COBS encoder includes its own, which
        # is more efficient resource-wise as it is combined with the lookahead buffer.
        self._pipe = assembly.add_in_pipe(
            component.o_stream, in_flush=component.o_flush, fifo_depth=2)
        self._overflow = assembly.add_ro_register(component.overflow)

        self._buffer  = bytearray()
        self._packets = []

    def _log(self, message, *args):
        self._logger.log(self._level, "SPI analyzer: " + message, *args)

    async def _recv_packet(self) -> bytes:
        while not self._packets:
            if self._pipe.readable == 0 and await self._overflow:
                raise SPIAnalyzerOverflow("overflow")

            self._buffer += await self._pipe.recv(self._pipe.readable or 1)
            if b"\x00" in self._buffer:
                *self._packets, self._buffer = self._buffer.split(b"\x00")

        packet = self._packets[0]
        del self._packets[0]
        return cobs_decode(packet)

    async def capture(self) -> tuple[bytes, bytes]:
        packet = await self._recv_packet()
        copi_data, cipo_data = packet[0::2], packet[1::2]
        self._log("capture copi=<%s> cipo=<%s>", dump_hex(copi_data), dump_hex(cipo_data))
        return (copi_data, cipo_data)


class SPIAnalyzerApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "analyze SPI transactions"
    description = """
    Capture transactions on the SPI bus.

    SPI data is captured in a clock domain driven by the SCK pin and reset by the CS# pin.
    This approach enables capturing data at very high SCK frequencies (up to ~100 MHz), but
    requires a small delay between the last SCK rising edge and CS# rising edge, otherwise
    the last byte of a transaction will not be captured correctly.

    Note that a transaction is reported only after the first byte of the next transaction
    is captured.
    """
    # May work on revA/B with a looser clock constraint on SCK.
    required_revision = "C0"

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "cs",   required=True, default=True)
        access.add_pins_argument(parser, "sck",  required=True, default=True)
        access.add_pins_argument(parser, "copi", required=True, default=True)
        access.add_pins_argument(parser, "cipo", required=True, default=True)

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.assembly.use_pulls({
                args.cs:   "high", args.sck:  "low",
                args.copi: "high", args.cipo: "high"
            })
            self.spi_analyzer_iface = SPIAnalyzerInterface(self.logger, self.assembly,
                cs=args.cs, sck=args.sck, copi=args.copi, cipo=args.cipo)

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
