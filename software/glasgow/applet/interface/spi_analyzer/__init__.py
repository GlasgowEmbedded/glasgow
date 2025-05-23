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
    def __init__(self, ports, *, word_width=8):
        self._ports = ports

        self._word_width = word_width

        super().__init__({
            "stream": Out(stream.Signature(data.StructLayout({
                "chip":  range(len(self._ports.cs)),
                "copi":  self._word_width,
                "cipo":  self._word_width,
                "start": 1
            }))),
            "complete": Out(1), # FIFO empty and CS# deasserted
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
        # only limited by the FPGA fabric performance (compared to an approach that uses
        # a sampling clock), but introduces timing hazards.
        m.domains.spi = cd_spi = ClockDomain(async_reset=True, local=True)
        m.submodules.spi_rst_sync = cdc.ResetSynchronizer(cs_buffer.i.all(), domain="spi")
        m.d.comb += cd_spi.clk.eq(sck_buffer.i)

        # The FIFO contents must not be reset even if the FIFO writer is reset. This creates
        # an unsynchronized CDC path between the FIFO writer and the FIFO, the practical effect
        # of which is that there is a (difficult to specify) hold time constraint between CS#
        # deassertion and preceding SCK edge. This timing hazard is an inherent feature of
        # the approach taken in this component.
        m.domains.fifo = cd_fifo = ClockDomain(reset_less=True, local=True)
        m.d.comb += cd_fifo.clk.eq(sck_buffer.i)

        m.submodules.fifo = fifo = StreamFIFO(
            shape=self.stream.p.shape(),
            depth=4, # CDC only, no buffering
            w_domain="fifo",
            r_domain="sync"
        )

        for index, chip in enumerate(cs_buffer.i):
            with m.If(~chip):
                m.d.comb += fifo.w.p.chip.eq(index)

        copi_shreg = Signal(self._word_width)
        cipo_shreg = Signal(self._word_width)
        m.d.fifo += copi_shreg.eq(Cat(copi_buffer.i, copi_shreg))
        m.d.fifo += cipo_shreg.eq(Cat(cipo_buffer.i, cipo_shreg))
        m.d.comb += fifo.w.p.copi.eq(Cat(copi_buffer.i, copi_shreg))
        m.d.comb += fifo.w.p.cipo.eq(Cat(cipo_buffer.i, cipo_shreg))

        start = Signal(init=1)
        count = Signal(range(self._word_width), init=2) # 2 is the ResetSynchronizer latency
        m.d.comb += fifo.w.p.start.eq(start)
        with m.If(count == self._word_width - 1):
            m.d.comb += fifo.w.valid.eq(1)
            m.d.spi += start.eq(0)
            m.d.spi += count.eq(0)
        with m.Else():
            m.d.spi += count.eq(count + 1)

        overflow_spi  = Signal()
        with m.If(fifo.w.valid & ~fifo.w.ready):
            m.d.spi += overflow_spi.eq(1)

        wiring.connect(m, wiring.flipped(self.stream), fifo.r)

        cs_sync = Signal()
        # Note that the async FIFO write-to-read latency, and the latency of this synchronizer,
        # are the same (2 cycles). This synchronizer isn't critical to the operation of
        # the frontend; it is only used to avoid the last transfer being stuck in the encoder
        # indefinitely because there is no end marker. Back-to-back transfers may not ever cause
        # the `complete` output to be asserted.
        m.submodules.cs_sync = cdc.FFSynchronizer(cs_buffer.i.all(), cs_sync)
        with m.If(cs_sync & ~fifo.r.valid):
            m.d.comb += self.complete.eq(1)

        overflow_sync = Signal()
        m.submodules.overflow_sync = cdc.FFSynchronizer(overflow_spi, overflow_sync)
        with m.If(overflow_sync):
            m.d.sync += self.overflow.eq(1)

        return m


class SPIAnalyzerComponent(wiring.Component):
    o_stream: Out(stream.Signature(8))
    o_flush:  Out(1)

    overflow: Out(1)

    def __init__(self, ports, buffer_size: int):
        self._ports = ports
        self._buffer_size = buffer_size

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.encoder  = encoder  = COBSEncoder(fifo_depth=self._buffer_size)
        wiring.connect(m, wiring.flipped(self.o_stream), encoder.o)

        m.submodules.frontend = frontend = SPIAnalyzerFrontend(self._ports)

        idle  = Signal(init=1)
        timer = Signal(20)
        with m.FSM():
            with m.State("Idle"):
                with m.If(frontend.stream.valid):
                    m.d.comb += encoder.i.p.data.eq(frontend.stream.p.chip)
                    m.d.comb += encoder.i.valid.eq(1)
                    with m.If(encoder.i.ready):
                        m.next = "COPI"
                # FIXME: this timeout should be a part of the common FX2 logic
                with m.Else():
                    with m.If(timer == 0):
                        m.d.comb += self.o_flush.eq(1)
                    with m.Else():
                        m.d.sync += timer.eq(timer - 1)

            with m.State("COPI"):
                with m.If(frontend.stream.valid):
                    with m.If(frontend.stream.p.start & ~idle):
                        m.next = "End"
                    with m.Else():
                        m.d.comb += encoder.i.p.data.eq(frontend.stream.p.copi)
                        m.d.comb += encoder.i.valid.eq(1)
                        with m.If(encoder.i.ready):
                            m.d.sync += idle.eq(0)
                            m.next = "CIPO"
                with m.Elif(frontend.complete):
                    m.next = "End"

            with m.State("CIPO"):
                m.d.comb += encoder.i.p.data.eq(frontend.stream.p.cipo)
                m.d.comb += encoder.i.valid.eq(1)
                with m.If(encoder.i.ready):
                    m.d.comb += frontend.stream.ready.eq(1)
                    m.next = "COPI"

            with m.State("End"):
                m.d.comb += encoder.i.p.end.eq(1)
                m.d.comb += encoder.i.valid.eq(1)
                with m.If(encoder.i.ready):
                    m.d.sync += idle.eq(1)
                    # FIXME: not the most elegant approach to make the timeout shorter
                    # during simulation
                    m.d.sync += timer.eq(1000 if platform is None else ~0)
                    m.next = "Idle"

        m.d.comb += self.overflow.eq(frontend.overflow)

        return m


class SPIAnalyzerInterface:
    def __init__(self, logger, assembly, *, cs, sck, copi, cipo, buffer_size=512):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        ports = assembly.add_port_group(cs=cs, sck=sck, copi=copi, cipo=cipo)
        component = assembly.add_submodule(SPIAnalyzerComponent(ports, buffer_size))
        # Use only a minimal interface FIFO; most of the buffering is done in the COBS encoder.
        self._pipe = assembly.add_in_pipe(
            component.o_stream, in_flush=component.o_flush, fifo_depth=4)
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
        chip, copi_data, cipo_data = packet[0], packet[1::2], packet[2::2]
        self._log("capture chip=%d copi=<%s> cipo=<%s>",
            chip, dump_hex(copi_data), dump_hex(cipo_data))
        return (chip, copi_data, cipo_data)


class SPIAnalyzerApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "analyze SPI transactions"
    description = """
    Capture transactions on the SPI bus.

    SPI data is captured in a clock domain driven by the SCK pin and reset by the CS# pin.
    This approach enables capturing data at very high SCK frequencies (up to 100 MHz), but
    requires a small delay between the last SCK rising edge and CS# rising edge, otherwise
    the last byte of a transaction will not be captured correctly. Typically, SPI controllers
    do provide this delay.

    Signal integrity is exceptionally important for this applet. When using flywires, twist
    every signal wire (at the very least, CS# and SCK wires) with a ground wire connected to
    ground at both ends, otherwise the captured data will likely be nonsense.

    The capture file format is Comma Separated Values, in one of the following line formats:

    * ``<COPI>,<CIPO>``, where <COPI> and <CIPO> are hexadecimal byte sequences with each eight
      bits corresponding to samples of COPI and CIPO, respectively (from MSB to LSB); this format
      is used if one CS# pin is provided.

    * ``<CS>,<COPI>,<CIPO>``, where <CS> is a 0-based CS# pin index and <COPI> and <CIPO> are
      the same as above; this format is used if multiple CS# pins are provided.

    If your DUT is a 25-series SPI Flash memory, use the `tool memory-25x` to extract data
    from capture files. If quad-IO commands are in use, use the `qspi-analyzer` applet to
    capture data.
    """
    # May work on revA/B with a looser clock constraint on SCK and less RAM.
    required_revision = "C0"

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "cs",   required=True, default=True, width=range(1, 257))
        access.add_pins_argument(parser, "sck",  required=True, default=True)
        access.add_pins_argument(parser, "copi", required=True, default=True)
        access.add_pins_argument(parser, "cipo", required=True, default=True)
        parser.add_argument(
            "--buffer-size", metavar="BYTES", type=int, default=16384,
            help="set FPGA trace buffer size to BYTES (must be power of 2, default: %(default)s)")

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.assembly.use_pulls({args.cs: "high"})
            self.spi_analyzer_iface = SPIAnalyzerInterface(self.logger, self.assembly,
                cs=args.cs, sck=args.sck, copi=args.copi, cipo=args.cipo,
                buffer_size=args.buffer_size)

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
            chip, copi_data, cipo_data = await self.spi_analyzer_iface.capture()
            if len(args.cs) == 1:
                args.file.write(f"{copi_data.hex()},{cipo_data.hex()}\n")
            else:
                args.file.write(f"{chip},{copi_data.hex()},{cipo_data.hex()}\n")
            args.file.flush()

    @classmethod
    def tests(cls):
        from . import test
        return test.SPIAnalyzerAppletTestCase
