import logging
import asyncio
import struct
import array
import time
import statistics
import enum

from amaranth import *
from amaranth.lib import wiring, stream
from amaranth.lib.wiring import In, Out

from glasgow.gateware.lfsr import LinearFeedbackShiftRegister
from glasgow.applet import GlasgowAppletV2


class Mode(enum.Enum):
    SOURCE   = 1
    SINK     = 2
    LOOPBACK = 3


class BenchmarkComponent(wiring.Component):
    i_stream: In(stream.Signature(8))
    o_stream: Out(stream.Signature(8))
    o_flush:  Out(1)
    mode:     In(Mode)
    error:    Out(1)
    count:    Out(32)

    def __init__(self):
        self.lfsr = LinearFeedbackShiftRegister(degree=16, taps=(16, 15, 13, 4))

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        lfsr_en   = Signal()
        lfsr_word = Signal(8)
        m.submodules.lfsr = lfsr = EnableInserter(lfsr_en)(self.lfsr)
        m.d.comb += lfsr_word.eq(self.lfsr.value.word_select(self.count & 1, width=8))

        with m.FSM():
            with m.State("MODE"):
                m.d.sync += self.count.eq(0)
                with m.Switch(self.mode):
                    with m.Case(Mode.SOURCE):
                        m.next = "SOURCE"
                    with m.Case(Mode.SINK):
                        m.next = "SINK"
                    with m.Case(Mode.LOOPBACK):
                        m.next = "LOOPBACK"

            with m.State("SOURCE"):
                m.d.comb += [
                    self.o_stream.payload.eq(lfsr_word),
                    self.o_stream.valid.eq(1),
                ]
                with m.If(self.o_stream.ready):
                    m.d.comb += [
                        lfsr_en.eq(self.count & 1),
                    ]
                    m.d.sync += self.count.eq(self.count + 1)

            with m.State("SINK"):
                with m.If(self.i_stream.valid):
                    with m.If(self.i_stream.payload != lfsr_word):
                        m.d.sync += self.error.eq(1)
                    m.d.comb += [
                        self.i_stream.ready.eq(1),
                        lfsr_en.eq(self.count & 1),
                    ]
                    m.d.sync += self.count.eq(self.count + 1)

            with m.State("LOOPBACK"):
                m.d.comb += [
                    self.o_stream.payload.eq(self.i_stream.payload),
                    self.o_stream.valid.eq(self.i_stream.valid),
                    self.i_stream.ready.eq(self.o_stream.ready),
                ]
                with m.If(self.o_stream.ready & self.o_stream.valid):
                    m.d.sync += self.count.eq(self.count + 1)
                with m.Else():
                    m.d.comb += [
                        self.o_flush.eq(1),
                    ]

        return m


class BenchmarkApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "evaluate communication performance"
    description = """
    Evaluate performance of the host communication link.

    Benchmark modes:

    * source: device emits an endless stream of data via one FIFO, host validates
      (simulates a logic analyzer subtarget)
    * sink: host emits an endless stream of data via one FIFO, device validates
      (simulates an I2S protocol subtarget)
    * loopback: host emits an endless stream of data via one FIFOs, device mirrors it all back,
      host validates (simulates an SPI protocol subtarget)
    * latency: host sends one packet, device sends it back, time until the packet is received back
      on the host is measured (simulates cases where a transaction with the DUT relies on feedback
      from the host; also useful for comparing different usb stacks or usb data paths like hubs or
      network bridges)
    """

    __all_modes = ["source", "sink", "loopback", "latency"]

    @classmethod
    def add_build_arguments(cls, parser, access):
        pass

    def build(self, args):
        with self.assembly.add_applet(self):
            component = self.assembly.add_submodule(BenchmarkComponent())
            self._pipe = self.assembly.add_inout_pipe(
                component.o_stream, component.i_stream, in_flush=component.o_flush)
            self._mode = self.assembly.add_rw_register(component.mode)
            self._error = self.assembly.add_ro_register(component.error)
            self._count = self.assembly.add_ro_register(component.count)

        sequence = array.array("H")
        sequence.extend(component.lfsr.generate())
        if struct.pack("H", 0x1234) != struct.pack("<H", 0x1234):
            sequence.byteswap()
        self._sequence = sequence.tobytes()

    @classmethod
    def add_run_arguments(cls, parser):
        parser.add_argument(
            "-c", "--count", metavar="COUNT", type=int, default=1 << 23,
            help="transfer COUNT bytes (default: %(default)s)")

        parser.add_argument(
            dest="modes", metavar="MODE", type=str, nargs="*", choices=[[]] + cls.__all_modes,
            help="run benchmark mode MODE (default: {})".format(" ".join(cls.__all_modes)))

    async def run(self, args):
        golden = bytearray()
        while len(golden) < args.count:
            golden += self._sequence[:args.count - len(golden)]

        # These requests are essentially free, as the data and control requests are independent,
        # both on the FX2 and on the USB bus.
        async def counter():
            while True:
                await asyncio.sleep(0.1)
                count = await self._count
                self.logger.debug("transferred %#x/%#x", count, args.count)

        for mode in args.modes or self.__all_modes:
            self.logger.info("running benchmark mode %s for %.3f MiB",
                             mode, len(golden) / (1 << 20))

            if mode == "source":
                await self._mode.set(Mode.SOURCE.value)
                await self._pipe.reset()

                counter_fut = asyncio.ensure_future(counter())
                begin  = time.time()
                actual = await self._pipe.recv(len(golden))
                end    = time.time()
                length = len(golden)
                counter_fut.cancel()

                error = (actual != golden)
                count = None

            if mode == "sink":
                await self._mode.set(Mode.SINK.value)
                await self._pipe.reset()

                counter_fut = asyncio.ensure_future(counter())
                begin  = time.time()
                await self._pipe.send(golden)
                await self._pipe.flush()
                end    = time.time()
                length = len(golden)
                counter_fut.cancel()

                error = bool(await self._error)
                count = await self._count

            if mode == "loopback":
                await self._mode.set(Mode.LOOPBACK.value)
                await self._pipe.reset()
                counter_fut = asyncio.ensure_future(counter())

                begin  = time.time()
                await self._pipe.send(golden)
                await self._pipe.flush()
                actual = await self._pipe.recv(len(golden))
                end    = time.time()
                length = len(golden) * 2
                counter_fut.cancel()

                error = (actual != golden)
                count = None

            if mode == "latency":
                packetmax = golden[:512]
                count = 0
                error = False
                roundtriptime = []

                await self._mode.set(Mode.LOOPBACK.value)
                await self._pipe.reset()
                counter_fut = asyncio.ensure_future(counter())

                while count < args.count:
                    begin = time.perf_counter()
                    await self._pipe.send(packetmax)
                    await self._pipe.flush()
                    actual = await self._pipe.recv(len(packetmax))
                    end = time.perf_counter()

                    # calculate roundtrip time in µs
                    roundtriptime.append((end - begin) * 1000000)
                    if actual != packetmax:
                        error = True
                        break
                    count += len(packetmax) * 2

                counter_fut.cancel()

            if error:
                if count is None:
                    self.logger.error("mode %s failed!", mode)
                else:
                    self.logger.error("mode %s failed at %#x!", mode, count)
            else:
                if mode == "latency":
                    self.logger.info("mode %s: mean: %.2f µs stddev: %.2f µs worst: %.2f µs",
                                 mode,
                                 statistics.mean(roundtriptime),
                                 statistics.pstdev(roundtriptime),
                                 max(roundtriptime))
                else:
                    self.logger.info("mode %s: %.2f MiB/s (%.2f Mb/s)",
                                 mode,
                                 (length / (end - begin)) / (1 << 20),
                                 (length / (end - begin)) / (1 << 17))

    @classmethod
    def tests(cls):
        from . import test
        return test.BenchmarkAppletTestCase
