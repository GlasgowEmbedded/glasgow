import contextlib
import logging
import struct

from amaranth import *
from amaranth.lib import enum, data, wiring, stream, io
from amaranth.lib.wiring import In, Out, connect, flipped

from glasgow.support.logging import dump_hex
from glasgow.gateware import spi
from glasgow.abstract import AbstractAssembly, ClockDivisor
from glasgow.applet import GlasgowAppletV2


__all__ = ["SPIControllerComponent", "SPIControllerInterface"]


class SPICommand(enum.Enum, shape=4):
    Select   = 0
    Transfer = 1
    Delay    = 2
    Sync     = 3


class SPIControllerComponent(wiring.Component):
    i_stream: In(stream.Signature(8))
    o_stream: Out(stream.Signature(8))
    o_flush:  Out(1)

    divisor:  In(16)

    def __init__(self, ports, *, offset=None, us_cycles):
        self._ports     = ports
        self._offset    = offset
        self._us_cycles = us_cycles

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.ctrl = ctrl = spi.Controller(self._ports,
            # Offset sampling by ~10 ns to compensate for 10..15 ns of roundtrip delay caused by
            # the level shifters (5 ns each) and FPGA clock-to-out (5 ns).
            offset=1 if self._offset is None else self._offset)
        m.d.comb += ctrl.divisor.eq(self.divisor)

        command = Signal(SPICommand)
        chip    = Signal(range(1 + len(self._ports.cs)))
        mode    = Signal(spi.Mode)
        is_put  = mode.as_value().matches(spi.Mode.Put, spi.Mode.Swap)
        is_get  = mode.as_value().matches(spi.Mode.Get, spi.Mode.Swap) # FIXME: amaranth-lang/amaranth#1462
        o_count = Signal(16)
        i_count = Signal(16)
        timer   = Signal(range(self._us_cycles))
        with m.FSM():
            with m.State("Read-Command"):
                m.d.comb += self.o_flush.eq(1)
                m.d.comb += self.i_stream.ready.eq(1)
                with m.If(self.i_stream.valid):
                    m.d.sync += command.eq(self.i_stream.payload[4:])
                    with m.Switch(self.i_stream.payload[4:]):
                        with m.Case(SPICommand.Select):
                            m.d.sync += chip.eq(self.i_stream.payload[:4])
                            m.next = "Read-Command"
                        with m.Case(SPICommand.Transfer):
                            m.d.sync += mode.eq(self.i_stream.payload[:4])
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
                    ctrl.i_stream.p.chip.eq(chip),
                    ctrl.i_stream.p.mode.eq(mode),
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
    def __init__(self, logger, assembly: AbstractAssembly, *, cs, sck, copi, cipo):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        ports = assembly.add_port_group(cs=cs, sck=sck, copi=copi, cipo=cipo)
        component = assembly.add_submodule(SPIControllerComponent(ports,
            us_cycles=int(1 / (assembly.sys_clk_period * 1_000_000))))
        self._pipe = assembly.add_inout_pipe(
            component.o_stream, component.i_stream, in_flush=component.o_flush)
        self._clock = assembly.add_clock_divisor(component.divisor,
            ref_period=assembly.sys_clk_period, name="sck")

        self._active = None

    def _log(self, message, *args):
        self._logger.log(self._level, "SPI: " + message, *args)

    @property
    def clock(self) -> ClockDivisor:
        return self._clock

    @staticmethod
    def _chunked(items, *, count=0xffff):
        while items:
            yield items[:count]
            items = items[count:]

    @contextlib.asynccontextmanager
    async def select(self, index=0):
        assert self._active is None, "chip already selected"
        assert index in range(8)
        try:
            self._log("select chip=%d", index)
            await self._pipe.send(struct.pack("<B",
                (SPICommand.Select.value << 4) | (1 + index)))
            self._active = index
            yield
        finally:
            self._log("deselect")
            await self._pipe.send(struct.pack("<BBH",
                (SPICommand.Select.value << 4) | 0,
                (SPICommand.Transfer.value << 4) | spi.Mode.Dummy.value, 1))
            await self._pipe.flush()
            self._active = None

    async def exchange(self, octets: bytes | bytearray | memoryview) -> memoryview:
        assert self._active is not None, "no chip selected"
        self._log("xchg-o=<%s>", dump_hex(octets))
        for chunk in self._chunked(octets):
            await self._pipe.send(struct.pack("<BH",
                (SPICommand.Transfer.value << 4) | spi.Mode.Swap.value, len(chunk)))
            await self._pipe.send(chunk)
        await self._pipe.flush()
        octets = await self._pipe.recv(len(octets))
        self._log("xchg-i=<%s>", dump_hex(octets))
        return octets

    async def write(self, octets: bytes | bytearray | memoryview):
        assert self._active is not None, "no chip selected"
        self._log("write=<%s>", dump_hex(octets))
        for chunk in self._chunked(octets):
            await self._pipe.send(struct.pack("<BH",
                (SPICommand.Transfer.value << 4) | spi.Mode.Put.value, len(chunk)))
            await self._pipe.send(chunk)

    async def read(self, count: int) -> memoryview:
        assert self._active is not None, "no chip selected"
        for chunk in self._chunked(range(count)):
            await self._pipe.send(struct.pack("<BH",
                (SPICommand.Transfer.value << 4) | spi.Mode.Get.value, len(chunk)))
        await self._pipe.flush()
        octets = await self._pipe.recv(count)
        self._log("read=<%s>", dump_hex(octets))
        return octets

    async def dummy(self, count: int):
        # We intentionally allow sending dummy cycles with no chip selected.
        self._log("dummy=%d", count)
        for chunk in self._chunked(range(count)):
            await self._pipe.send(struct.pack("<BH",
                (SPICommand.Transfer.value << 4) | spi.Mode.Dummy.value, len(chunk)))

    async def delay_us(self, duration: int):
        self._log("delay us=%d", duration)
        for chunk in self._chunked(range(duration)):
            await self._pipe.send(struct.pack("<BH",
                (SPICommand.Delay.value << 4), len(chunk)))

    async def delay_ms(self, duration: int):
        self._log("delay ms=%d", duration)
        for chunk in self._chunked(range(duration * 1000)):
            await self._pipe.send(struct.pack("<BH",
                (SPICommand.Delay.value << 4), len(chunk)))

    async def synchronize(self):
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
    Initiate transactions on the SPI bus.

    Currently, only SPI mode 3 (CPOL=1, CPHA=1) is supported.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "sck",  default=True, required=True)
        access.add_pins_argument(parser, "copi", default=True, required=True)
        access.add_pins_argument(parser, "cipo", default=True, required=True)
        access.add_pins_argument(parser, "cs",   default=True, required=True)

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.spi_iface = SPIControllerInterface(self.logger, self.assembly,
                cs=args.cs, sck=args.sck, copi=args.copi, cipo=args.cipo)

    @classmethod
    def add_setup_arguments(cls, parser):
        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=100,
            help="set SCK frequency to FREQ kHz (default: %(default)s)")

    async def setup(self, args):
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
