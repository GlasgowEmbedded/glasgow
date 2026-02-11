from typing import Literal
import contextlib
import logging
import struct

from amaranth import *
from amaranth.lib import enum, wiring, stream, io
from amaranth.lib.wiring import In, Out

from glasgow.support.logging import dump_hex
from glasgow.gateware import spi
from glasgow.abstract import AbstractAssembly, GlasgowPin, ClockDivisor
from glasgow.applet import GlasgowAppletV2


__all__ = ["SPIControllerComponent", "SPIControllerInterface"]


class SPICommand(enum.Enum, shape=4):
    SetMode  = 0
    Select   = 1
    Transfer = 2
    Delay    = 3
    Sync     = 4


class SPIControllerComponent(wiring.Component):
    i_stream: In(stream.Signature(8))
    o_stream: Out(stream.Signature(8))

    divisor:  In(16)

    def __init__(self, ports, *, offset=None, us_cycles):
        self._ports     = ports
        self._offset    = offset
        self._us_cycles = us_cycles

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        if self._ports.cs is None:
            self._ports.cs = io.SimulationPort("o", 1)
        if self._ports.copi is None:
            self._ports.copi = io.SimulationPort("o", 1)
        if self._ports.cipo is None:
            self._ports.cipo = io.SimulationPort("i", 1)

        m.submodules.ctrl = ctrl = spi.Controller(self._ports,
            # Offset sampling by ~10 ns to compensate for 10..15 ns of roundtrip delay caused by
            # the level shifters (5 ns each) and FPGA clock-to-out (5 ns).
            offset=1 if self._offset is None else self._offset)
        m.d.comb += ctrl.divisor.eq(self.divisor)

        command = Signal(SPICommand)
        mode    = Signal(spi.Mode)
        chip    = Signal(range(1 + len(self._ports.cs)))
        oper    = Signal(spi.Operation)
        # FIXME: amaranth-lang/amaranth#1462
        is_put  = oper.as_value().matches(spi.Operation.Put, spi.Operation.Swap)
        is_get  = oper.as_value().matches(spi.Operation.Get, spi.Operation.Swap)
        o_count = Signal(16)
        i_count = Signal(16)
        timer   = Signal(range(self._us_cycles))
        with m.FSM():
            with m.State("Read-Command"):
                m.d.comb += self.i_stream.ready.eq(1)
                with m.If(self.i_stream.valid):
                    m.d.sync += command.eq(self.i_stream.payload[4:])
                    with m.Switch(self.i_stream.payload[4:]):
                        with m.Case(SPICommand.SetMode):
                            m.d.sync += mode.eq(self.i_stream.payload[:4])
                            m.d.sync += oper.eq(spi.Operation.Idle)
                            m.d.sync += o_count.eq(1)
                            m.d.sync += i_count.eq(1)
                            m.next = "Transfer"
                        with m.Case(SPICommand.Select):
                            m.d.sync += chip.eq(self.i_stream.payload[:4])
                            with m.If(self.i_stream.payload[:4] == 0):
                                m.d.sync += oper.eq(spi.Operation.Idle)
                                m.d.sync += o_count.eq(1)
                                m.d.sync += i_count.eq(1)
                                m.next = "Transfer"
                        with m.Case(SPICommand.Transfer):
                            m.d.sync += oper.eq(self.i_stream.payload[:4])
                            m.next = "Read-Count-0:8"
                        with m.Case(SPICommand.Delay):
                            m.next = "Read-Count-0:8"
                        with m.Case(SPICommand.Sync):
                            m.next = "Sync"

            with m.State("Read-Count-0:8"):
                m.d.comb += self.i_stream.ready.eq(1)
                with m.If(self.i_stream.valid):
                    m.d.sync += o_count[0:8].eq(self.i_stream.payload)
                    m.d.sync += i_count[0:8].eq(self.i_stream.payload)
                    m.next = "Read-Count-8:16"

            with m.State("Read-Count-8:16"):
                m.d.comb += self.i_stream.ready.eq(1)
                with m.If(self.i_stream.valid):
                    m.d.sync += o_count[8:16].eq(self.i_stream.payload)
                    m.d.sync += i_count[8:16].eq(self.i_stream.payload)
                    with m.Switch(command):
                        with m.Case(SPICommand.Transfer):
                            m.next = "Transfer"
                        with m.Case(SPICommand.Delay):
                            m.next = "Delay"

            with m.State("Transfer"):
                m.d.comb += [
                    ctrl.i_stream.p.mode.eq(mode),
                    ctrl.i_stream.p.chip.eq(chip),
                    ctrl.i_stream.p.oper.eq(oper),
                    ctrl.i_stream.p.data.eq(self.i_stream.payload),
                    self.o_stream.payload.eq(ctrl.o_stream.p.data),
                ]
                with m.If(o_count != 0):
                    with m.If(is_put):
                        m.d.comb += ctrl.i_stream.valid.eq(self.i_stream.valid)
                        m.d.comb += self.i_stream.ready.eq(ctrl.i_stream.ready)
                    with m.Else():
                        m.d.comb += ctrl.i_stream.valid.eq(1)
                    with m.If(ctrl.i_stream.valid & ctrl.i_stream.ready):
                        m.d.sync += o_count.eq(o_count - 1)
                with m.If(i_count != 0):
                    with m.If(is_get):
                        m.d.comb += self.o_stream.valid.eq(ctrl.o_stream.valid)
                        m.d.comb += ctrl.o_stream.ready.eq(self.o_stream.ready)
                        with m.If(ctrl.o_stream.valid & ctrl.o_stream.ready):
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
                m.d.comb += self.o_stream.valid.eq(1)
                with m.If(self.o_stream.ready):
                    m.next = "Read-Command"

        return m


class SPIControllerInterface:
    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
                 cs: GlasgowPin | None = None, sck: GlasgowPin,
                 copi: GlasgowPin | None = None, cipo: GlasgowPin | None = None,
                 mode: spi.Mode | Literal[0, 1, 2, 3] = spi.Mode.IdleLow_SampleRising):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        ports = assembly.add_port_group(cs=cs, sck=sck, copi=copi, cipo=cipo)
        component = assembly.add_submodule(SPIControllerComponent(ports,
            us_cycles=int(1 / (assembly.sys_clk_period * 1_000_000))))
        self._pipe = assembly.add_inout_pipe(component.o_stream, component.i_stream)
        self._clock = assembly.add_clock_divisor(component.divisor,
            ref_period=assembly.sys_clk_period, name="sck")

        self._active = None
        self.mode = mode

    def _log(self, message, *args):
        self._logger.log(self._level, "SPI: " + message, *args)

    @property
    def mode(self) -> spi.Mode:
        """SPI mode.

        Cannot be changed while a transaction is active.
        """
        return self._mode

    @mode.setter
    def mode(self, mode: spi.Mode | Literal[0, 1, 2, 3]):
        assert self._active is None, "cannot switch mode during transaction"
        self._mode = spi.Mode(mode)

    @property
    def clock(self) -> ClockDivisor:
        """SCK clock divisor."""
        return self._clock

    @staticmethod
    def _chunked(items, *, count=0xffff):
        while items:
            yield items[:count]
            items = items[count:]

    @contextlib.asynccontextmanager
    async def select(self, index=0):
        """Perform a transaction.

        Starting a transaction asserts :py:`index`-th chip select signal and configures the mode;
        ending a transaction deasserts the chip select signal. Methods :meth:`write`, :meth:`read`,
        :meth:`exchange`, and :meth:`dummy` may be called while a transaction is active (only) to
        exchange data on the bus.

        For example, to read 4 bytes from an SPI flash, use the following code:

        .. code:: python

            iface.mode = 3
            async with iface.select():
                await iface.write([0x03, 0, 0, 0]) # READ = 0x03, address = 0x000000
                data = await iface.read(4)

        An empty transaction (where the body does not call :meth:`write`, :meth:`read`,
        :meth:`exchange`, or :meth:`dummy`) is allowed and causes chip select activity only,
        in addition to any clock edges required to switch the SPI bus mode with chip select
        inactive.
        """
        assert self._active is None, "chip already selected"
        assert index in range(8)
        try:
            self._log("select chip=%d", index)
            await self._pipe.send(struct.pack("<BB",
                (SPICommand.SetMode.value << 4) | self._mode,
                (SPICommand.Select.value << 4) | (1 + index)))
            self._active = index
            yield
        finally:
            self._log("deselect")
            await self._pipe.send(struct.pack("<B",
                (SPICommand.Select.value << 4) | 0))
            await self._pipe.flush()
            self._active = None

    async def exchange(self, data: bytes | bytearray | memoryview) -> memoryview:
        """Exchange data.

        Must be used within a transaction (see :meth:`select`). Shifts :py:`data` into
        the peripheral while shifting :py:`len(data)` bytes out of the peripheral.

        Returns the bytes shifted out.
        """
        assert self._active is not None, "no chip selected"
        self._log("xchg-o=<%s>", dump_hex(data))
        for chunk in self._chunked(data):
            await self._pipe.send(struct.pack("<BH",
                (SPICommand.Transfer.value << 4) | spi.Operation.Swap.value, len(chunk)))
            await self._pipe.send(chunk)
        await self._pipe.flush()
        data = await self._pipe.recv(len(data))
        self._log("xchg-i=<%s>", dump_hex(data))
        return data

    async def write(self, data: bytes | bytearray | memoryview):
        """Write data.

        Must be used within a transaction (see :meth:`select`). Shifts :py:`data` into
        the peripheral.
        """
        assert self._active is not None, "no chip selected"
        self._log("write=<%s>", dump_hex(data))
        for chunk in self._chunked(data):
            await self._pipe.send(struct.pack("<BH",
                (SPICommand.Transfer.value << 4) | spi.Operation.Put.value, len(chunk)))
            await self._pipe.send(chunk)

    async def read(self, count: int) -> memoryview:
        """Read data.

        Must be used within a transaction (see :meth:`select`). Shifts :py:`len(data)` bytes out of
        the peripheral.

        Returns the bytes shifted out.
        """
        assert self._active is not None, "no chip selected"
        for chunk in self._chunked(range(count)):
            await self._pipe.send(struct.pack("<BH",
                (SPICommand.Transfer.value << 4) | spi.Operation.Get.value, len(chunk)))
        await self._pipe.flush()
        octets = await self._pipe.recv(count)
        self._log("read=<%s>", dump_hex(octets))
        return octets

    async def dummy(self, count: int):
        # We intentionally allow sending dummy cycles with no chip selected.
        self._log("dummy=%d", count)
        for chunk in self._chunked(range(count)):
            await self._pipe.send(struct.pack("<BH",
                (SPICommand.Transfer.value << 4) | spi.Operation.Idle.value, len(chunk)))

    async def delay_us(self, duration: int):
        """Delay operations.

        Delays the following SPI bus operations by :py:`duration` microseconds.
        """
        self._log("delay us=%d", duration)
        for chunk in self._chunked(range(duration)):
            await self._pipe.send(struct.pack("<BH",
                (SPICommand.Delay.value << 4), len(chunk)))

    async def delay_ms(self, duration: int):
        """Delay operations.

        Delays the following SPI bus operations by :py:`duration` milliseconds. Equivalent to
        :py:`delay_us(duration * 1000)`.
        """
        self._log("delay ms=%d", duration)
        for chunk in self._chunked(range(duration * 1000)):
            await self._pipe.send(struct.pack("<BH",
                (SPICommand.Delay.value << 4), len(chunk)))

    async def synchronize(self):
        """Synchronization barrier.

        Ensures that once this method returns, all previously submitted operations have completed.
        """
        self._log("sync-o")
        await self._pipe.send(struct.pack("<B",
            (SPICommand.Sync.value << 4)))
        await self._pipe.flush()
        await self._pipe.recv(1)
        self._log("sync-i")


class SPIControllerApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "initiate SPI transactions"
    description = """
    Initiate transactions on the Motorola SPI bus.
    """
    required_revision = "C0"

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "cs",   default=True, required=True)
        access.add_pins_argument(parser, "sck",  default=True, required=True)
        access.add_pins_argument(parser, "copi", default=True)
        access.add_pins_argument(parser, "cipo", default=True)

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.spi_iface = SPIControllerInterface(self.logger, self.assembly,
                cs=args.cs, sck=args.sck, copi=args.copi, cipo=args.cipo)

    @classmethod
    def add_setup_arguments(cls, parser):
        parser.add_argument(
            "-m", "--mode", metavar="MODE", type=int, choices=(0, 1, 2, 3), default=0,
            help="configure active edge and idle state according to MODE (default: %(default)s)")
        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=100,
            help="set SCK frequency to FREQ kHz (default: %(default)s)")

    async def setup(self, args):
        self.spi_iface.mode = args.mode
        await self.spi_iface.clock.set_frequency(args.frequency * 1000)

    @classmethod
    def add_run_arguments(cls, parser):
        def hex(arg): return bytes.fromhex(arg)

        parser.add_argument(
            "data", metavar="DATA", type=hex, nargs="+",
            help="hex bytes to exchange with the device")

    async def run(self, args):
        for octets in args.data:
            async with self.spi_iface.select():
                octets = await self.spi_iface.exchange(octets)
            print(octets.hex())

    @classmethod
    def tests(cls):
        from . import test
        return test.SPIControllerAppletTestCase
