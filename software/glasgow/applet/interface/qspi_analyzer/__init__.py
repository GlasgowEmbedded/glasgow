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


__all__ = ["QSPIAnalyzerOverflow", "QSPIAnalyzerComponent", "QSPIAnalyzerApplet"]


class QSPIAnalyzerOverflow(GlasgowAppletError):
    pass


class QSPIAnalyzerFrontend(wiring.Component):
    def __init__(self, ports):
        self._ports = ports

        super().__init__({
            "stream": Out(stream.Signature(data.StructLayout({
                "data":  8,
                "epoch": 1
            }))),
            "complete": Out(1), # FIFO empty and CS# deasserted
            "overflow": Out(1),
        })

    def elaborate(self, platform):
        m = Module()

        m.submodules.cs_buffer  = cs_buffer  = io.Buffer("i", self._ports.cs)
        m.submodules.sck_buffer = sck_buffer = io.Buffer("i", self._ports.sck)
        m.submodules.io_buffer  = io_buffer  = io.Buffer("i", self._ports.io)

        if platform is not None:
            # Above 96 MHz, the CDC FIFO can't be read out quickly enough to transfer the data
            # to the USB FIFO. Although the CDC FIFO depth could be increased, the amount of
            # memory on an iCE40HX8K is very limited, so in a practical QSPI application this
            # would only allow for a few more transactions to be read before an inevitable
            # overflow. Also, adding more logic (widening the FIFO counters) in the SCK domain
            # will make any potential timing hazards worse.
            platform.add_clock_constraint(sck_buffer.i, 96e6)

        # The analyzer frontend is clocked by QSPI clock and resynchronized whenever CS# is
        # asserted by using CS# as an active-high reset. This means that frequency of SCK is
        # only limited by the FPGA fabric performance (compared to an approach that uses
        # a sampling clock), but introduces timing hazards.
        m.domains.qspi = cd_qspi = ClockDomain(async_reset=True, local=True)
        m.d.comb += cd_qspi.rst.eq(cs_buffer.i)
        m.d.comb += cd_qspi.clk.eq(sck_buffer.i)

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

        shreg = Signal(8)
        match len(io_buffer.i):
            case 4:
                m.d.fifo += shreg.eq(Cat(io_buffer.i, shreg))
                m.d.comb += fifo.w.p.data.eq(Cat(io_buffer.i, shreg))
            case 2:
                m.d.fifo += shreg.eq(Cat(io_buffer.i, C(0, 2), shreg))
                m.d.comb += fifo.w.p.data.eq(Cat(io_buffer.i, C(0, 2), shreg))

        start = Signal(init=1)
        epoch = Signal(reset_less=True, init=1)
        count = Signal(range(2))
        with m.If(count == 1):
            m.d.comb += fifo.w.valid.eq(1)
            with m.If(start):
                m.d.qspi += start.eq(0)
                m.d.qspi += epoch.eq(~epoch)
                m.d.comb += fifo.w.p.epoch.eq(~epoch)
            with m.Else():
                m.d.comb += fifo.w.p.epoch.eq(epoch)
            m.d.qspi += count.eq(0)
        with m.Else():
            m.d.qspi += count.eq(count + 1)

        overflow_qspi  = Signal()
        with m.If(fifo.w.valid & ~fifo.w.ready):
            m.d.qspi += overflow_qspi.eq(1)

        wiring.connect(m, wiring.flipped(self.stream), fifo.r)

        cs_sync = Signal()
        # Note that the async FIFO write-to-read latency, and the latency of this synchronizer,
        # are the same (2 cycles). This synchronizer isn't critical to the operation of
        # the frontend; it is only used to avoid the last transfer being stuck in the encoder
        # indefinitely because there is no end marker. Back-to-back transfers may not ever cause
        # the `complete` output to be asserted.
        m.submodules.cs_sync = cdc.FFSynchronizer(cs_buffer.i, cs_sync)
        with m.If(cs_sync & ~fifo.r.valid):
            m.d.comb += self.complete.eq(1)

        overflow_sync = Signal()
        m.submodules.overflow_sync = cdc.FFSynchronizer(overflow_qspi, overflow_sync)
        with m.If(overflow_sync):
            m.d.sync += self.overflow.eq(1)

        return m


class QSPIAnalyzerComponent(wiring.Component):
    o_stream: Out(stream.Signature(8))
    o_flush:  Out(1)

    overflow: Out(1)

    def __init__(self, ports, buffer_size: int):
        self._ports = ports
        self._buffer_size = buffer_size

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.encoder = encoder = COBSEncoder(fifo_depth=self._buffer_size)
        wiring.connect(m, wiring.flipped(self.o_stream), encoder.o)

        m.submodules.frontend = frontend = QSPIAnalyzerFrontend(self._ports)

        idle  = Signal(init=1)
        epoch = Signal()
        timer = Signal(20)
        with m.If(frontend.stream.valid):
            with m.If(frontend.stream.p.epoch != epoch):
                m.d.comb += encoder.i.p.end.eq(1)
                m.d.comb += encoder.i.valid.eq(1)
                with m.If(encoder.i.ready):
                    m.d.sync += idle.eq(1)
                    m.d.sync += epoch.eq(frontend.stream.p.epoch)
            with m.Else():
                m.d.comb += encoder.i.p.data.eq(frontend.stream.p.data)
                m.d.comb += encoder.i.valid.eq(1)
                m.d.comb += frontend.stream.ready.eq(encoder.i.ready)
                with m.If(encoder.i.ready):
                    m.d.sync += idle.eq(0)
                    # FIXME: not the most elegant approach to make the timeout shorter
                    # during simulation
                    m.d.sync += timer.eq(1000 if platform is None else ~0)
        with m.Elif(frontend.complete & ~idle):
            m.d.comb += encoder.i.p.end.eq(1)
            m.d.comb += encoder.i.valid.eq(1)
            with m.If(encoder.i.ready):
                m.d.sync += idle.eq(1)
                m.d.sync += epoch.eq(~epoch)

        # FIXME: this timeout should be a part of the common FX2 logic
        with m.Else():
            with m.If(timer == 0):
                m.d.comb += self.o_flush.eq(1)
            with m.Else():
                m.d.sync += timer.eq(timer - 1)

        m.d.comb += self.overflow.eq(frontend.overflow)

        return m


class QSPIAnalyzerInterface:
    def __init__(self, logger, assembly, *, cs, sck, io, buffer_size=512):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        ports = assembly.add_port_group(cs=cs, sck=sck, io=io)
        component = assembly.add_submodule(QSPIAnalyzerComponent(ports, buffer_size))
        # Use only a minimal interface FIFO; most of the buffering is done in the COBS encoder.
        self._pipe = assembly.add_in_pipe(
            component.o_stream, in_flush=component.o_flush, fifo_depth=4)
        self._overflow = assembly.add_ro_register(component.overflow)

        self._buffer  = bytearray()
        self._packets = []

    def _log(self, message, *args):
        self._logger.log(self._level, "QSPI analyzer: " + message, *args)

    async def _recv_packet(self) -> bytes:
        while not self._packets:
            if self._pipe.readable == 0 and await self._overflow:
                raise QSPIAnalyzerOverflow("overflow")

            self._buffer += await self._pipe.recv(self._pipe.readable or 1)
            if b"\x00" in self._buffer:
                *self._packets, self._buffer = self._buffer.split(b"\x00")

        packet = self._packets[0]
        del self._packets[0]
        return cobs_decode(packet)

    async def capture(self) -> tuple[bytes, bytes]:
        data = await self._recv_packet()
        self._log("capture data=<%s>", dump_hex(data))
        return data


class QSPIAnalyzerApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "analyze QSPI transactions"
    description = """
    Capture transactions on the extended variant of the SPI bus with four I/O channels.

    QSPI data is captured in a clock domain driven by the SCK pin and reset by the CS# pin.
    This approach enables capturing data at very high SCK frequencies (up to 96 MHz), but
    requires a small delay between the last SCK rising edge and CS# rising edge, otherwise
    the last byte of a transaction will not be captured correctly. Typically, QSPI controllers
    do provide this delay.

    Signal integrity is exceptionally important for this applet. When using flywires, twist
    every signal wire (at the very least, CS# and SCK wires) with a ground wire connected to
    ground at both ends, otherwise the captured data will likely be nonsense.

    Both quad-IO and dual-IO captures are supported. If only IO0 and IO1 pins are provided,
    the capture proceeds as if IO2 and IO3 were fixed at 0.

    The capture file format is Comma Separated Values, in the following line format:

    * ``<DATA>``, where <DATA> is a hexadecimal nibble sequence with each four bits corresponding
      to samples of HOLD#, WP#, CIPO, COPI (from MSB to LSB).

    If your DUT is a 25-series SPI Flash memory, use the `tool memory-25x` to extract data
    from capture files. If quad-IO commands are not in use, the `spi-analyzer` applet can
    reduce the likelihood of an overflow.
    """
    # May work on revA/B with a looser clock constraint on SCK and less RAM.
    required_revision = "C0"

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "cs",  required=True, default=True)
        access.add_pins_argument(parser, "sck", required=True, default=True)
        access.add_pins_argument(parser, "io",  required=True, width=range(2, 6, 2), default=4,
            help="bind the applet I/O lines 'copi', 'cipo', 'wp', 'hold' to PINS")
        parser.add_argument(
            "--buffer-size", metavar="BYTES", type=int, default=16384,
            help="set FPGA trace buffer size to BYTES (must be power of 2, default: %(default)s)")

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.assembly.use_pulls({args.cs: "high"})
            self.qspi_analyzer_iface = QSPIAnalyzerInterface(self.logger, self.assembly,
                cs=args.cs, sck=args.sck, io=args.io,
                buffer_size=args.buffer_size)

    @classmethod
    def add_run_arguments(cls, parser):
        parser.add_argument("file", metavar="FILE",
            type=argparse.FileType("w"), nargs="?", default=sys.stdout,
            help="save communications to FILE as hex sequences")

    async def run(self, args):
        try:
            args.file.truncate()
        except OSError:
            pass # pipe, tty/pty, etc

        while True:
            data = await self.qspi_analyzer_iface.capture()
            args.file.write(f"{data.hex()}\n")
            args.file.flush()

    @classmethod
    def tests(cls):
        from . import test
        return test.QSPIAnalyzerAppletTestCase
