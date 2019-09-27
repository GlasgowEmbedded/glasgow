import logging
import asyncio
import struct
import array
import time
import statistics
import enum
from nmigen import *

from ....gateware.lfsr import *
from ... import *


class Mode(enum.Enum):
    SOURCE   = 1
    SINK     = 2
    LOOPBACK = 3


class BenchmarkSubtarget(Elaboratable):
    def __init__(self, reg_mode, reg_error, reg_count, in_fifo, out_fifo):
        self.reg_mode  = reg_mode
        self.reg_error = reg_error
        self.reg_count = reg_count

        self.in_fifo  = in_fifo
        self.out_fifo = out_fifo

        self.lfsr = LinearFeedbackShiftRegister(degree=16, taps=(16, 15, 13, 4))

    def elaborate(self, platform):
        m = Module()

        lfsr_en   = Signal()
        lfsr_word = Signal(8)
        m.submodules.lfsr = lfsr = EnableInserter(lfsr_en)(self.lfsr)
        m.d.comb += lfsr_word.eq(self.lfsr.value.word_select(self.reg_count & 1, width=8))

        with m.FSM():
            with m.State("MODE"):
                m.d.sync += self.reg_count.eq(0)
                with m.Switch(self.reg_mode):
                    with m.Case(Mode.SOURCE):
                        m.next = "SOURCE"
                    with m.Case(Mode.SINK):
                        m.next = "SINK"
                    with m.Case(Mode.LOOPBACK):
                        m.next = "LOOPBACK"

            with m.State("SOURCE"):
                with m.If(self.in_fifo.w_rdy):
                    m.d.comb += [
                        self.in_fifo.w_data.eq(lfsr_word),
                        self.in_fifo.w_en.eq(1),
                        lfsr_en.eq(self.reg_count & 1),
                    ]
                    m.d.sync += self.reg_count.eq(self.reg_count + 1)

            with m.State("SINK"):
                with m.If(self.out_fifo.r_rdy):
                    with m.If(self.out_fifo.dout != lfsr_word):
                        m.d.sync += self.reg_error.eq(1)
                    m.d.comb += [
                        self.out_fifo.r_en.eq(1),
                        lfsr_en.eq(self.reg_count & 1),
                    ]
                    m.d.sync += self.reg_count.eq(self.reg_count + 1)

            with m.State("LOOPBACK"):
                m.d.comb += self.in_fifo.din.eq(self.out_fifo.dout)
                with m.If(self.in_fifo.w_rdy & self.out_fifo.r_rdy):
                    m.d.comb += [
                        self.in_fifo.w_en.eq(1),
                        self.out_fifo.r_en.eq(1),
                    ]
                    m.d.sync += self.reg_count.eq(self.reg_count + 1)
                with m.Else():
                    m.d.comb += [
                        self.in_fifo.flush.eq(1),
                    ]

        return m


class BenchmarkApplet(GlasgowApplet, name="benchmark"):
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
          host validates
          (simulates an SPI protocol subtarget)
        * latency: host sends one packet, device sends it back, time until the packet is received back
          on the host is measured
          (simulates cases where a transaction with the DUT relies on feedback from the host;
          also useful for comparing different usb stacks or usb data paths like hubs or network bridges)
    """

    __all_modes = ["source", "sink", "loopback", "latency"]

    def build(self, target, args):
        self.mux_interface = iface = \
            target.multiplexer.claim_interface(self, args=None, throttle="none")
        mode,  self.__addr_mode  = target.registers.add_rw(2)
        error, self.__addr_error = target.registers.add_ro(1)
        count, self.__addr_count = target.registers.add_ro(32)
        subtarget = iface.add_subtarget(BenchmarkSubtarget(
            reg_mode=mode, reg_error=error, reg_count=count,
            in_fifo=iface.get_in_fifo(auto_flush=False),
            out_fifo=iface.get_out_fifo(),
        ))

        sequence = array.array("H")
        sequence.extend(subtarget.lfsr.generate())
        if struct.pack("H", 0x1234) != struct.pack("<H", 0x1234):
            sequence.byteswap()
        self._sequence = sequence.tobytes()

    @classmethod
    def add_run_arguments(cls, parser, access):
        parser.add_argument(
            "-c", "--count", metavar="COUNT", type=int, default=1 << 23,
            help="transfer COUNT bytes (default: %(default)s)")

        parser.add_argument(
            dest="modes", metavar="MODE", type=str, nargs="*", choices=[[]] + cls.__all_modes,
            help="run benchmark mode MODE (default: {})".format(" ".join(cls.__all_modes)))

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args=None)

        golden = bytearray()
        while len(golden) < args.count:
            golden += self._sequence[:args.count - len(golden)]

        # These requests are essentially free, as the data and control requests are independent,
        # both on the FX2 and on the USB bus.
        async def counter():
            while True:
                await asyncio.sleep(0.1)
                count = await device.read_register(self.__addr_count, width=4)
                self.logger.debug("transferred %#x/%#x", count, args.count)

        for mode in args.modes or self.__all_modes:
            self.logger.info("running benchmark mode %s for %.3f MiB",
                             mode, len(golden) / (1 << 20))

            if mode == "source":
                await device.write_register(self.__addr_mode, Mode.SOURCE.value)
                await iface.reset()

                counter_fut = asyncio.ensure_future(counter())
                begin  = time.time()
                actual = await iface.read(len(golden))
                end    = time.time()
                length = len(golden)
                counter_fut.cancel()

                error = (actual != golden)
                count = None

            if mode == "sink":
                await device.write_register(self.__addr_mode, Mode.SINK.value)
                await iface.reset()

                counter_fut = asyncio.ensure_future(counter())
                begin  = time.time()
                await iface.write(golden)
                await iface.flush()
                end    = time.time()
                length = len(golden)
                counter_fut.cancel()

                error = bool(await device.read_register(self.__addr_error))
                count = await device.read_register(self.__addr_count, width=4)

            if mode == "loopback":
                await device.write_register(self.__addr_mode, Mode.LOOPBACK.value)
                await iface.reset()
                counter_fut = asyncio.ensure_future(counter())

                begin  = time.time()
                await iface.write(golden)
                actual = await iface.read(len(golden))
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

                await device.write_register(self.__addr_mode, Mode.LOOPBACK.value)
                await iface.reset()
                counter_fut = asyncio.ensure_future(counter())

                while count < args.count:
                    begin = time.perf_counter()
                    await iface.write(packetmax)
                    actual = await iface.read(len(packetmax))
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

# -------------------------------------------------------------------------------------------------

class BenchmarkAppletTestCase(GlasgowAppletTestCase, applet=BenchmarkApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
