from typing import Literal
import contextlib
import logging
import struct

from amaranth import *
from amaranth.lib import enum, wiring, stream
from amaranth.lib.wiring import In, Out

from glasgow.support.logging import dump_hex
from glasgow.gateware import qspi
from glasgow.abstract import AbstractAssembly, ClockDivisor
from glasgow.applet import GlasgowAppletV2


__all__ = ["QSPIControllerComponent", "QSPIControllerInterface"]


class QSPICommand(enum.Enum, shape=4):
    Select   = 0
    Transfer = 1
    Delay    = 2
    Sync     = 3


class QSPIControllerComponent(wiring.Component):
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

        m.submodules.ctrl = ctrl = qspi.Controller(self._ports,
            # Offset sampling by ~10 ns to compensate for 10..15 ns of roundtrip delay caused by
            # the level shifters (5 ns each) and FPGA clock-to-out (5 ns).
            offset=1 if self._offset is None else self._offset)
        m.d.comb += ctrl.divisor.eq(self.divisor)

        command = Signal(QSPICommand)
        chip    = Signal(range(1 + len(self._ports.cs)))
        mode    = Signal(qspi.Mode)
        is_put  = mode.as_value().matches(qspi.Mode.PutX1, qspi.Mode.PutX2, qspi.Mode.PutX4,
                                          qspi.Mode.Swap)
        is_get  = mode.as_value().matches(qspi.Mode.GetX1, qspi.Mode.GetX2, qspi.Mode.GetX4,
                                          qspi.Mode.Swap) # FIXME: amaranth-lang/amaranth#1462
        o_count = Signal(16)
        i_count = Signal(16)
        timer   = Signal(range(self._us_cycles))
        with m.FSM():
            with m.State("Read-Command"):
                m.d.comb += self.i_stream.ready.eq(1)
                with m.If(self.i_stream.valid):
                    m.d.sync += command.eq(self.i_stream.payload[4:])
                    with m.Switch(self.i_stream.payload[4:]):
                        with m.Case(QSPICommand.Select):
                            m.d.sync += chip.eq(self.i_stream.payload[:4])
                            m.next = "Read-Command"
                        with m.Case(QSPICommand.Transfer):
                            m.d.sync += mode.eq(self.i_stream.payload[:4])
                            m.next = "Read-Count-0:8"
                        with m.Case(QSPICommand.Delay):
                            m.next = "Read-Count-0:8"
                        with m.Case(QSPICommand.Sync):
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
                        with m.Case(QSPICommand.Transfer):
                            m.next = "Transfer"
                        with m.Case(QSPICommand.Delay):
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


class QSPIControllerInterface:
    def __init__(self, logger, assembly: AbstractAssembly, *, cs, sck, io):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        ports = assembly.add_port_group(cs=cs, sck=sck, io=io)
        assembly.use_pulls({io: "high"}) # pull WP#/HOLD# high
        component = assembly.add_submodule(QSPIControllerComponent(ports,
            us_cycles=int(1 / (assembly.sys_clk_period * 1_000_000))))
        self._pipe = assembly.add_inout_pipe(component.o_stream, component.i_stream)
        self._clock = assembly.add_clock_divisor(component.divisor,
            ref_period=assembly.sys_clk_period, name="sck")

        self._active = None

    def _log(self, message, *args):
        self._logger.log(self._level, "QSPI: " + message, *args)

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
                (QSPICommand.Select.value << 4) | (1 + index)))
            self._active = index
            yield
        finally:
            self._log("deselect")
            await self._pipe.send(struct.pack("<BBH",
                (QSPICommand.Select.value << 4) | 0,
                (QSPICommand.Transfer.value << 4) | qspi.Mode.Dummy.value, 1))
            await self._pipe.flush()
            self._active = None

    async def exchange(self, octets: bytes | bytearray | memoryview) -> memoryview:
        assert self._active is not None, "no chip selected"
        self._log("xchg-o=<%s>", dump_hex(octets))
        for chunk in self._chunked(octets):
            await self._pipe.send(struct.pack("<BH",
                (QSPICommand.Transfer.value << 4) | qspi.Mode.Swap.value, len(chunk)))
            await self._pipe.send(chunk)
        await self._pipe.flush()
        octets = await self._pipe.recv(len(octets))
        self._log("xchg-i=<%s>", dump_hex(octets))
        return octets

    async def write(self, octets: bytes | bytearray | memoryview, *, x: Literal[1, 2, 4] = 1):
        assert self._active is not None, "no chip selected"
        mode = {1: qspi.Mode.PutX1, 2: qspi.Mode.PutX2, 4: qspi.Mode.PutX4}[x]
        self._log("write=<%s>", dump_hex(octets))
        for chunk in self._chunked(octets):
            await self._pipe.send(struct.pack("<BH",
                (QSPICommand.Transfer.value << 4) | mode.value, len(chunk)))
            await self._pipe.send(chunk)

    async def read(self, count: int, *, x: Literal[1, 2, 4] = 1) -> memoryview:
        assert self._active is not None, "no chip selected"
        mode = {1: qspi.Mode.GetX1, 2: qspi.Mode.GetX2, 4: qspi.Mode.GetX4}[x]
        for chunk in self._chunked(range(count)):
            await self._pipe.send(struct.pack("<BH",
                (QSPICommand.Transfer.value << 4) | mode.value, len(chunk)))
        await self._pipe.flush()
        octets = await self._pipe.recv(count)
        self._log("read=<%s>", dump_hex(octets))
        return octets

    async def dummy(self, count: int):
        # We intentionally allow sending dummy cycles with no chip selected.
        self._log("dummy=%d", count)
        for chunk in self._chunked(range(count)):
            await self._pipe.send(struct.pack("<BH",
                (QSPICommand.Transfer.value << 4) | qspi.Mode.Dummy.value, len(chunk)))

    async def delay_us(self, duration: int):
        self._log("delay us=%d", duration)
        for chunk in self._chunked(range(duration)):
            await self._pipe.send(struct.pack("<BH",
                (QSPICommand.Delay.value << 4), len(chunk)))

    async def delay_ms(self, duration: int):
        self._log("delay ms=%d", duration)
        for chunk in self._chunked(range(duration * 1000)):
            await self._pipe.send(struct.pack("<BH",
                (QSPICommand.Delay.value << 4), len(chunk)))

    async def synchronize(self):
        self._log("sync-o")
        await self._pipe.send(struct.pack("<B",
            (QSPICommand.Sync.value << 4)))
        await self._pipe.flush()
        await self._pipe.recv(1)
        self._log("sync-i")


class QSPIControllerApplet(GlasgowAppletV2):
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
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "sck", default=True, required=True)
        access.add_pins_argument(parser, "io",  default=True, required=True, width=4,
            help="bind the applet I/O lines 'copi', 'cipo', 'io2', 'io3' to PINS")
        access.add_pins_argument(parser, "cs",  default=True, required=True)

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.qspi_iface = QSPIControllerInterface(self.logger, self.assembly,
                cs=args.cs, sck=args.sck, io=args.io)

    @classmethod
    def add_setup_arguments(cls, parser):
        # Most devices that advertise QSPI support should work at 1 MHz.
        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=1000,
            help="set SCK frequency to FREQ kHz (default: %(default)s)")

    async def setup(self, args):
        await self.qspi_iface.clock.set_frequency(args.frequency * 1000)

    @classmethod
    def add_run_arguments(cls, parser):
        def hex(arg): return bytes.fromhex(arg)

        parser.add_argument(
            "data", metavar="DATA", type=hex, nargs="+",
            help="hex bytes to exchange with the device in SPI mode")

    async def run(self, args):
        for octets in args.data:
            async with self.qspi_iface.select():
                octets = await self.qspi_iface.exchange(octets)
            print(octets.hex())

    @classmethod
    def tests(cls):
        from . import test
        return test.QSPIControllerAppletTestCase
