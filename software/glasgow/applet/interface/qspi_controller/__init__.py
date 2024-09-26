import contextlib
import logging
import struct
from amaranth import *
from amaranth.lib import enum, data, wiring, stream, io
from amaranth.lib.wiring import In, Out, connect, flipped

from ....support.logging import *
from ....gateware.iostream import IOStreamer
from ....gateware.qspi import QSPIMode, QSPIController
from ... import *


class _QSPICommand(enum.Enum, shape=4):
    Select   = 0
    Transfer = 1
    Delay    = 2
    Sync     = 3


class QSPIControllerSubtarget(Elaboratable):
    def __init__(self, *, ports, out_fifo, in_fifo, divisor, us_cycles, sample_delay_half_clocks=0):
        self._ports    = ports
        self._out_fifo = out_fifo
        self._in_fifo  = in_fifo

        self._divisor   = divisor
        self._us_cycles = us_cycles
        self._sample_delay_half_clocks = sample_delay_half_clocks

    def elaborate(self, platform):
        m = Module()

        m.submodules.qspi = qspi = QSPIController(self._ports, use_ddr_buffers=True,
                                                  sample_delay_half_clocks = self._sample_delay_half_clocks)
        m.d.comb += qspi.divisor.eq(self._divisor)

        o_fifo  = self._out_fifo.stream
        i_fifo  = self._in_fifo.stream

        command = Signal(_QSPICommand)
        chip    = Signal(range(1 + len(self._ports.cs)))
        mode    = Signal(QSPIMode)
        is_put  = mode.as_value().matches(QSPIMode.PutX1, QSPIMode.PutX2, QSPIMode.PutX4,
                                          QSPIMode.Swap)
        is_get  = mode.as_value().matches(QSPIMode.GetX1, QSPIMode.GetX2, QSPIMode.GetX4,
                                          QSPIMode.Swap) # FIXME: amaranth-lang/amaranth#1462
        o_count = Signal(16)
        i_count = Signal(16)
        timer   = Signal(range(self._us_cycles))
        with m.FSM():
            with m.State("Read-Command"):
                m.d.comb += self._in_fifo.flush.eq(1)
                m.d.comb += o_fifo.ready.eq(1)
                with m.If(o_fifo.valid):
                    m.d.sync += command.eq(o_fifo.payload[4:])
                    with m.Switch(o_fifo.payload[4:]):
                        with m.Case(_QSPICommand.Select):
                            m.d.sync += chip.eq(o_fifo.payload[:4])
                            m.next = "Read-Command"
                        with m.Case(_QSPICommand.Transfer):
                            m.d.sync += mode.eq(o_fifo.payload[:4])
                            m.next = "Read-Count-0:8"
                        with m.Case(_QSPICommand.Delay):
                            m.next = "Read-Count-0:8"
                        with m.Case(_QSPICommand.Sync):
                            m.next = "Sync"

            with m.State("Read-Count-0:8"):
                m.d.comb += o_fifo.ready.eq(1)
                with m.If(o_fifo.valid):
                    m.d.sync += o_count[0:8].eq(o_fifo.payload)
                    m.d.sync += i_count[0:8].eq(o_fifo.payload)
                    m.next = "Read-Count-8:16"

            with m.State("Read-Count-8:16"):
                m.d.comb += o_fifo.ready.eq(1)
                with m.If(o_fifo.valid):
                    m.d.sync += o_count[8:16].eq(o_fifo.payload)
                    m.d.sync += i_count[8:16].eq(o_fifo.payload)
                    with m.Switch(command):
                        with m.Case(_QSPICommand.Transfer):
                            m.next = "Transfer"
                        with m.Case(_QSPICommand.Delay):
                            m.next = "Delay"

            with m.State("Transfer"):
                m.d.comb += [
                    qspi.o_octets.p.chip.eq(chip),
                    qspi.o_octets.p.mode.eq(mode),
                    qspi.o_octets.p.data.eq(o_fifo.payload),
                    i_fifo.payload.eq(qspi.i_octets.p.data),
                ]
                with m.If(o_count != 0):
                    with m.If(is_put):
                        m.d.comb += qspi.o_octets.valid.eq(o_fifo.valid)
                        m.d.comb += o_fifo.ready.eq(qspi.o_octets.ready)
                    with m.Else():
                        m.d.comb += qspi.o_octets.valid.eq(1)
                    with m.If(qspi.o_octets.valid & qspi.o_octets.ready):
                        m.d.sync += o_count.eq(o_count - 1)
                with m.If(i_count != 0):
                    with m.If(is_get):
                        m.d.comb += i_fifo.valid.eq(qspi.i_octets.valid)
                        m.d.comb += qspi.i_octets.ready.eq(i_fifo.ready)
                        with m.If(qspi.i_octets.valid & qspi.i_octets.ready):
                            m.d.sync += i_count.eq(i_count - 1)
                with m.If((o_count == 0) & ((i_count == 0) | ~is_get)):
                    m.next = "Read-Command"

            with m.State("Delay"):
                with m.If(i_count == 0):
                    m.next = "Read-Command"
                with m.Elif(timer == 0):
                    m.d.sync += i_count.eq(i_count - 1)
                    m.d.sync += timer.eq(self._us_cycles - 1)
                with m.Else():
                    m.d.sync += timer.eq(timer - 1)

            with m.State("Sync"):
                m.d.comb += i_fifo.valid.eq(1)
                with m.If(i_fifo.ready):
                    m.next = "Read-Command"

        return m


class QSPIControllerInterface:
    def __init__(self, interface, logger):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

    def _log(self, message, *args):
        self._logger.log(self._level, "QSPI: " + message, *args)

    async def reset(self):
        self._log("reset")
        await self.lower.reset()

    @staticmethod
    def _chunked(items, *, count=0xffff):
        while items:
            yield items[:count]
            items = items[count:]

    @contextlib.asynccontextmanager
    async def select(self, index=0):
        assert index in range(8)
        try:
            self._log("select chip=%d", index)
            await self.lower.write(struct.pack("<B",
                (_QSPICommand.Select.value << 4) | (1 + index)))
            yield
        finally:
            self._log("deselect")
            await self.lower.write(struct.pack("<BBH",
                (_QSPICommand.Select.value << 4) | 0,
                (_QSPICommand.Transfer.value << 4) | QSPIMode.Dummy.value, 1))
            await self.lower.flush()

    async def exchange(self, octets):
        self._log("xchg-o=<%s>", dump_hex(octets))
        for chunk in self._chunked(octets):
            await self.lower.write(struct.pack("<BH",
                (_QSPICommand.Transfer.value << 4) | QSPIMode.Swap.value, len(chunk)))
            await self.lower.write(chunk)
        octets = await self.lower.read(len(octets))
        self._log("xchg-i=<%s>", dump_hex(octets))
        return octets

    async def write(self, octets, *, x=1):
        mode = {1: QSPIMode.PutX1, 2: QSPIMode.PutX2, 4: QSPIMode.PutX4}[x]
        self._log("write=<%s>", dump_hex(octets))
        for chunk in self._chunked(octets):
            await self.lower.write(struct.pack("<BH",
                (_QSPICommand.Transfer.value << 4) | mode.value, len(chunk)))
            await self.lower.write(chunk)

    async def read(self, count, *, x=1):
        mode = {1: QSPIMode.GetX1, 2: QSPIMode.GetX2, 4: QSPIMode.GetX4}[x]
        for chunk in self._chunked(range(count)):
            await self.lower.write(struct.pack("<BH",
                (_QSPICommand.Transfer.value << 4) | mode.value, len(chunk)))
        octets = await self.lower.read(count)
        self._log("read=<%s>", dump_hex(octets))
        return octets

    async def dummy(self, count):
        self._log("dummy=%d", count)
        for chunk in self._chunked(range(count)):
            await self.lower.write(struct.pack("<BH",
                (_QSPICommand.Transfer.value << 4) | QSPIMode.Dummy.value, len(chunk)))

    async def delay_us(self, duration):
        self._log("delay us=%d", duration)
        for chunk in self._chunked(range(duration)):
            await self.lower.write(struct.pack("<BH",
                (_QSPICommand.Delay.value << 4), len(chunk)))

    async def delay_ms(self, duration):
        self._log("delay ms=%d", duration)
        for chunk in self._chunked(range(duration * 1000)):
            await self.lower.write(struct.pack("<BH",
                (_QSPICommand.Delay.value << 4), len(chunk)))

    async def synchronize(self):
        self._log("sync-o")
        await self.lower.write(struct.pack("<B",
            (_QSPICommand.Sync.value << 4)))
        await self.lower.read(1)
        self._log("sync-i")


class QSPIControllerApplet(GlasgowApplet):
    logger = logging.getLogger(__name__)
    help = "initiate SPI/dual-SPI/quad-SPI/QPI transactions"
    description = """
    Initiate transactions on the extended variant of the SPI bus with four I/O channels.

    This applet can control a wide range of devices, primarily memories, that use multi-bit variants
    of the SPI bus. Electrically, they are all compatible, with the names indicating differences in
    protocol logic:

        * "SPI" uses COPI/CIPO for both commands and data;
        * "dual-SPI" uses COPI/CIPO for commands and IO0/IO1 for data;
        * "quad-SPI" uses COPI/CIPO for commands and IO0/IO1/IO2/IO3 for data;
        * "QPI" uses IO0/IO1/IO2/IO3 for both commands and data.

    In this list, COPI and CIPO refer to IO0 and IO1 respectively used as fixed direction I/O.
    Note that vendors often make further distinction between modes, e.g. between "dual output SPI"
    and "dual I/O SPI"; refer to the vendor documentation for details.

    The command line interface only initiates SPI mode transfers. Use the REPL for other modes.
    """
    # The FPGA on revA/revB is (marginally) too slow for the QSPI contrller core.
    required_revision = "C0"

    @classmethod
    def add_build_arguments(cls, parser, access, *, include_pins=True):
        super().add_build_arguments(parser, access)

        if include_pins:
            access.add_pin_argument(parser, "sck", default=True)
            access.add_pin_set_argument(parser, "io", width=4, default=True)
            access.add_pin_set_argument(parser, "cs", width=1, default=True)

        # Most devices that advertise QSPI support should work at 1 MHz.
        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=1000,
            help="set SCK frequency to FREQ kHz (default: %(default)s)")

        parser.add_argument(
            "-d", "--sample-delay", metavar="SAMPLE_DELAY", type=int, required=False,
            help="Specify sample delay in units of half clock-cycles. (Default: frequency-dependent)")

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        divisor=int(target.sys_clk_freq // (args.frequency * 2000))
        if divisor != 0:
            actual_frequency = target.sys_clk_freq / divisor / 2
        else:
            actual_frequency = target.sys_clk_freq
        if args.sample_delay is None:
            if actual_frequency <= 24_000_000.1:
                sample_delay = 0
            elif actual_frequency <= 60_000_000.1:
                sample_delay = 1
            else:
                sample_delay = 2
        else:
            sample_delay = args.sample_delay
        return iface.add_subtarget(QSPIControllerSubtarget(
            ports=iface.get_port_group(
                sck=args.pin_sck,
                io=args.pin_set_io,
                cs=args.pin_set_cs,
            ),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(auto_flush=False),
            divisor=divisor,
            us_cycles=int(target.sys_clk_freq // 1_000_000),
            sample_delay_half_clocks = sample_delay,
        ))

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args,
            # Pull IO2 and IO3 high, since on QSPI flashes these correspond to WP# and HOLD#,
            # and will interfere with operation in SPI mode. For other devices this is benign.
            pull_high={args.pin_set_io[2], args.pin_set_io[3]})
        qspi_iface = QSPIControllerInterface(iface, self.logger)
        return qspi_iface

    @classmethod
    def add_interact_arguments(cls, parser):
        def hex(arg): return bytes.fromhex(arg)

        parser.add_argument(
            "data", metavar="DATA", type=hex, nargs="+",
            help="hex bytes to exchange with the device in SPI mode")

    async def interact(self, device, args, qspi_iface):
        for octets in args.data:
            async with qspi_iface.select():
                octets = await qspi_iface.exchange(octets)
            print(octets.hex())

    @classmethod
    def tests(cls):
        from . import test
        return test.QSPIControllerAppletTestCase
