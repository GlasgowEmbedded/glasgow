import logging
import asyncio
import struct
import array
import time
from migen import *

from ....gateware.lfsr import *
from ... import *


MODE_SOURCE   = 1
MODE_SINK     = 2
MODE_LOOPBACK = 3


class BenchmarkSubtarget(Module):
    def __init__(self, mode, error, count, in_fifo, out_fifo):
        self.submodules.lfsr = CEInserter()(
            LinearFeedbackShiftRegister(degree=16, taps=(16, 15, 13, 4))
        )

        ###

        self.submodules.fsm = FSM(reset_state="MODE")
        self.fsm.act("MODE",
            NextValue(count, 0),
            If(mode == MODE_SOURCE,
                NextState("SOURCE-1")
            ).Elif(mode == MODE_SINK,
                NextState("SINK-1")
            ).Elif(mode == MODE_LOOPBACK,
                NextState("LOOPBACK")
            )
        )
        self.fsm.act("SOURCE-1",
            If(in_fifo.writable,
                in_fifo.din.eq(self.lfsr.value[0:8]),
                in_fifo.we.eq(1),
                NextValue(count, count + 1),
                NextState("SOURCE-2")
            )
        )
        self.fsm.act("SOURCE-2",
            If(in_fifo.writable,
                in_fifo.din.eq(self.lfsr.value[8:16]),
                in_fifo.we.eq(1),
                self.lfsr.ce.eq(1),
                NextValue(count, count + 1),
                NextState("SOURCE-1")
            )
        )
        self.fsm.act("SINK-1",
            If(out_fifo.readable,
                If(out_fifo.dout != self.lfsr.value[0:8],
                    NextValue(error, 1)
                ),
                out_fifo.re.eq(1),
                NextValue(count, count + 1),
                NextState("SINK-2")
            )
        )
        self.fsm.act("SINK-2",
            If(out_fifo.readable,
                If(out_fifo.dout != self.lfsr.value[8:16],
                    NextValue(error, 1)
                ),
                out_fifo.re.eq(1),
                self.lfsr.ce.eq(1),
                NextValue(count, count + 1),
                NextState("SINK-1")
            )
        )
        self.fsm.act("LOOPBACK",
            in_fifo.din.eq(out_fifo.dout),
            If(in_fifo.writable & out_fifo.readable,
                in_fifo.we.eq(1),
                out_fifo.re.eq(1),
                NextValue(count, count + 1),
            ).Else(
                in_fifo.flush.eq(1)
            )
        )


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
    """

    __all_modes = ["source", "sink", "loopback"]

    def build(self, target, args):
        self.mux_interface = iface = \
            target.multiplexer.claim_interface(self, args=None, throttle="none")
        mode,  self.__addr_mode  = target.registers.add_rw(2)
        error, self.__addr_error = target.registers.add_ro(1)
        count, self.__addr_count = target.registers.add_rw(32)
        subtarget = iface.add_subtarget(BenchmarkSubtarget(
            mode=mode, error=error, count=count,
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
                await device.write_register(self.__addr_mode, MODE_SOURCE)
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
                await device.write_register(self.__addr_mode, MODE_SINK)
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
                await device.write_register(self.__addr_mode, MODE_LOOPBACK)
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

            if error:
                if count is None:
                    self.logger.error("mode %s failed!", mode)
                else:
                    self.logger.error("mode %s failed at %#x!", mode, count)
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
