import logging
import asyncio
import struct
import time
from migen import *

from ....gateware.lfsr import *
from ... import *


MODE_SOURCE   = 1
MODE_SINK     = 2
MODE_LOOPBACK = 3


class BenchmarkSubtarget(Module):
    def __init__(self, mode, error, in_fifo, out_fifo):
        self.submodules.lfsr = CEInserter()(
            LinearFeedbackShiftRegister(degree=16, taps=(16, 15, 13, 4))
        )

        ###

        self.submodules.fsm = FSM(reset_state="MODE")
        self.fsm.act("MODE",
            If(mode == MODE_SOURCE,
                NextState("SOURCE-1")
            ).Elif(mode == MODE_SINK,
                NextState("SINK-1")
            ).Elif(mode == MODE_LOOPBACK,
                in_fifo.din.eq(out_fifo.dout),
                If(in_fifo.writable & out_fifo.readable,
                    in_fifo.we.eq(1),
                    out_fifo.re.eq(1)
                ).Else(
                    in_fifo.flush.eq(1)
                )
            )
        )
        self.fsm.act("SOURCE-1",
            If(in_fifo.writable,
                in_fifo.din.eq(self.lfsr.value[0:8]),
                in_fifo.we.eq(1),
                NextState("SOURCE-2")
            )
        )
        self.fsm.act("SOURCE-2",
            If(in_fifo.writable,
                in_fifo.din.eq(self.lfsr.value[8:16]),
                in_fifo.we.eq(1),
                self.lfsr.ce.eq(1),
                NextState("SOURCE-1")
            )
        )
        self.fsm.act("SINK-1",
            If(out_fifo.readable,
                If(out_fifo.dout != self.lfsr.value[0:8],
                    NextValue(error, 1)
                ),
                out_fifo.re.eq(1),
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
                NextState("SINK-1")
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
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args, throttle="none")
        mode,  self.__addr_mode  = target.registers.add_rw(2)
        error, self.__addr_error = target.registers.add_ro(1)
        subtarget = iface.add_subtarget(BenchmarkSubtarget(
            mode=mode,
            error=error,
            in_fifo=iface.get_in_fifo(auto_flush=False),
            out_fifo=iface.get_out_fifo(),
        ))

        self.__sequence = list(subtarget.lfsr.generate())

    @classmethod
    def add_run_arguments(cls, parser, access):
        parser.add_argument(
            "-c", "--count", metavar="COUNT", type=int, default=1 << 21,
            help="transfer COUNT pseudorandom values (default: %(default)s)")

        parser.add_argument(
            dest="modes", metavar="MODE", type=str, nargs="*", choices=[[]] + cls.__all_modes,
            help="run benchmark mode MODE (default: {})".format(" ".join(cls.__all_modes)))

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)

        golden = bytearray().join([struct.pack("<H", self.__sequence[n % len(self.__sequence)])
                                   for n in range(args.count)])

        for mode in args.modes or self.__all_modes:
            self.logger.info("running benchmark mode %s for %.3f MiB",
                             mode, len(golden) / (1 << 20))

            if mode == "source":
                await device.write_register(self.__addr_mode, MODE_SOURCE)
                await iface.reset()

                begin  = time.time()
                actual = await iface.read(len(golden))
                end    = time.time()

                error = (actual != golden)

            if mode == "sink":
                await device.write_register(self.__addr_mode, MODE_SINK)
                await iface.reset()

                begin  = time.time()
                await iface.write(golden)
                await iface.flush()
                end    = time.time()

                error = bool(await device.read_register(self.__addr_error))

            if mode == "loopback":
                await device.write_register(self.__addr_mode, MODE_LOOPBACK)
                await iface.reset()

                begin  = time.time()
                write_fut = asyncio.ensure_future(iface.write(golden))
                read_fut  = asyncio.ensure_future(iface.read(len(golden)))
                await asyncio.wait([write_fut, read_fut], return_when=asyncio.FIRST_EXCEPTION)
                actual = read_fut.result()
                end    = time.time()

                error = (actual != golden)

            if error:
                self.logger.error("mode %s failed!", mode)
            else:
                self.logger.info("mode %s: %.3f MiB/s",
                                 mode, (len(golden) / (end - begin)) / (1 << 20))

# -------------------------------------------------------------------------------------------------

class BenchmarkAppletTestCase(GlasgowAppletTestCase, applet=BenchmarkApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
