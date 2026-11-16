import asyncio
import logging

from amaranth import *
from amaranth.utils import exact_log2
from amaranth.lib import enum, data, wiring, stream
from amaranth.lib.wiring import In, Out

from glasgow.gateware import octoram
from glasgow.abstract import AbstractAssembly
from glasgow.applet import GlasgowAppletV2


__all__ = []


class Pattern(enum.Enum, shape=4):
    Const0 = 0
    Const1 = 1
    ConstA = 2
    Const5 = 3
    Alt01  = 4
    Alt10  = 5
    PRBS   = 6


class PatternGenerator(wiring.Component):
    mode:  In(Pattern)
    addr:  In(32)

    start: In(1)
    data:  Out(stream.Signature(data.ArrayLayout(8, 2), always_valid=True))

    def elaborate(self, platform):
        m = Module()

        seed = Signal(16)
        m.d.comb += seed.eq(self.addr[:16] ^ self.addr[16:])

        lfsr = Signal(16)
        with m.If(self.start):
            m.d.sync += lfsr.eq(Mux(seed != 0, seed, 1))
        with m.Elif(self.data.ready):
            m.d.sync += lfsr.eq(Cat(lfsr[15] ^ lfsr[14] ^ lfsr[12] ^ lfsr[3], lfsr))

        with m.Switch(self.mode):
            with m.Case(Pattern.Const0):
                m.d.comb += self.data.payload.eq( 0)
            with m.Case(Pattern.Const1):
                m.d.comb += self.data.payload.eq(~0)
            with m.Case(Pattern.ConstA):
                m.d.comb += self.data.payload[0].eq(0xAA)
                m.d.comb += self.data.payload[1].eq(0xAA)
            with m.Case(Pattern.Const5):
                m.d.comb += self.data.payload[0].eq(0x55)
                m.d.comb += self.data.payload[1].eq(0x55)
            with m.Case(Pattern.Alt01):
                m.d.comb += self.data.payload[0].eq( 0)
                m.d.comb += self.data.payload[1].eq(~0)
            with m.Case(Pattern.Alt10):
                m.d.comb += self.data.payload[0].eq(~0)
                m.d.comb += self.data.payload[1].eq( 0)
            with m.Case(Pattern.PRBS):
                m.d.comb += self.data.payload.eq(lfsr)

        return m


class MemoryTestComponent(wiring.Component):
    pattern:    In(Pattern)
    start_addr: In(32)
    stop_addr:  In(32)
    block_size: In(12)
    repeat:     In(1)
    curr_addr:  Out(32)

    error_addr: Out(32)
    error_gold: Out(16)
    error_data: Out(16)

    active:     In(1)
    cycles:     Out(16)
    errors:     Out(16)

    def __init__(self, bus, *, sys_clk_period):
        self._bus = bus
        self._sys_clk_period = sys_clk_period

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        curr_addr = Signal(32)
        curr_size = Signal.like(self.block_size)
        m.d.comb += self.curr_addr.eq(curr_addr)

        m.d.comb += self._bus.commands.p.addr.eq(curr_addr)
        m.d.comb += self._bus.commands.p.size.eq(self.block_size >> 1)

        m.submodules.pat_gen = pat_gen = PatternGenerator()
        m.d.comb += pat_gen.mode.eq(self.pattern)

        bit_errors = Signal(range(17))
        m.d.comb += bit_errors.eq(sum(self._bus.r_data.p[0].data ^ pat_gen.data.p[0]) +
                                  sum(self._bus.r_data.p[1].data ^ pat_gen.data.p[1]))

        reset_cycles = int(5e-6 / self._sys_clk_period) # tRST=2us (APS51208N-OBRx)
        reset_timer  = Signal(range(reset_cycles), init=reset_cycles - 1)

        with m.FSM():
            with m.State("Test Start"):
                with m.If(self.active):
                    m.d.sync += self.errors.eq(0)
                    m.d.sync += curr_addr.eq(self.start_addr)
                    m.next = "Interface Reset"

            with m.State("Interface Reset"):
                m.d.comb += self._bus.commands.p.type.eq(octoram.Command.GlobalReset)
                m.d.comb += self._bus.commands.valid.eq(1)
                with m.If(self._bus.commands.valid & self._bus.commands.ready):
                    m.d.sync += reset_timer.eq(reset_timer.init)
                    m.next = "Interface Reset Wait"

            with m.State("Interface Reset Wait"):
                with m.If(reset_timer != 0):
                    m.d.sync += reset_timer.eq(reset_timer - 1)
                with m.Else():
                    m.next = "Block Write Command"

            with m.State("Block Write Command"):
                m.d.comb += self._bus.commands.p.type.eq(octoram.Command.WriteMemRow)
                m.d.comb += self._bus.commands.valid.eq(1)
                with m.If(self._bus.commands.valid & self._bus.commands.ready):
                    m.d.comb += pat_gen.start.eq(1)
                    m.d.sync += curr_size.eq(0)
                    m.next = "Block Write Data"

            with m.State("Block Write Data"):
                with m.If(curr_size == self.block_size):
                    m.next = "Block Read Command"
                with m.Else():
                    m.d.comb += [
                        self._bus.w_data.p[0].data.eq(pat_gen.data.p[0]),
                        self._bus.w_data.p[1].data.eq(pat_gen.data.p[1]),
                        self._bus.w_data.valid.eq(pat_gen.data.valid),
                        pat_gen.data.ready.eq(self._bus.w_data.ready),
                    ]
                    with m.If(self._bus.w_data.valid & self._bus.w_data.ready):
                        m.d.sync += curr_size.eq(curr_size + 2)

            with m.State("Block Read Command"):
                m.d.comb += self._bus.commands.p.type.eq(octoram.Command.ReadMemRow)
                m.d.comb += self._bus.commands.valid.eq(1)
                with m.If(self._bus.commands.valid & self._bus.commands.ready):
                    m.d.comb += pat_gen.start.eq(1)
                    m.d.sync += curr_size.eq(0)
                    m.next = "Block Read Data"

            with m.State("Block Read Data"):
                with m.If(curr_size == self.block_size):
                    with m.If(curr_addr == self.stop_addr):
                        m.next = "Cycle End"
                    with m.Else():
                        m.next = "Block Write Command"
                with m.Else():
                    m.d.comb += self._bus.r_data.ready.eq(1)
                    with m.If(self._bus.r_data.valid & self._bus.r_data.ready):
                        m.d.comb += pat_gen.data.ready.eq(1)
                        with m.If(self.errors == 0):
                            m.d.sync += self.error_addr.eq(curr_addr)
                            m.d.sync += self.error_gold.eq(pat_gen.data.payload)
                            m.d.sync += self.error_data.eq(self._bus.r_data.payload)
                        with m.If(self.errors + bit_errors < (1 << len(bit_errors))):
                            m.d.sync += self.errors.eq(self.errors + bit_errors)
                        with m.Else():
                            m.d.sync += self.errors.eq(~0) # saturate
                        m.d.sync += curr_size.eq(curr_size + 2)
                        m.d.sync += curr_addr.eq(curr_addr + 2)

            with m.State("Cycle End"):
                m.d.sync += self.cycles.eq(self.cycles + 1)
                with m.If(self.repeat):
                    m.next = "Test Start"
                with m.Else():
                    m.next = "Test End"

            with m.State("Test End"):
                with m.If(~self.active):
                    m.d.sync += self.cycles.eq(0)
                    m.next = "Test Start"

        return m


class MemoryTestInterface:
    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        mem_bus, _mem_range = assembly.add_dynamic_memory()
        component = assembly.add_submodule(MemoryTestComponent(mem_bus,
            sys_clk_period=assembly.sys_clk_period))

        self._pattern    = assembly.add_rw_register(component.pattern)
        self._start_addr = assembly.add_rw_register(component.start_addr)
        self._stop_addr  = assembly.add_rw_register(component.stop_addr)
        self._block_size = assembly.add_rw_register(component.block_size)
        self._repeat     = assembly.add_rw_register(component.repeat)
        self._curr_addr  = assembly.add_ro_register(component.curr_addr)

        self._error_addr = assembly.add_ro_register(component.error_addr)
        self._error_gold = assembly.add_ro_register(component.error_gold)
        self._error_data = assembly.add_ro_register(component.error_data)

        self._active     = assembly.add_rw_register(component.active)
        self._cycles     = assembly.add_ro_register(component.cycles)
        self._errors     = assembly.add_ro_register(component.errors)

    def _log(self, message: str, *args):
        self._logger.log(self._level, "memtest: " + message, *args)

    async def run(self, region: range, *, patterns: tuple[Pattern] = Pattern) -> int:
        """Test memory within :py:`region`.

        Returns the number of bit errors, saturating to 65535; zero means the test succeeded.
        """
        assert 1 <= exact_log2(region.step) <= 12
        assert region.start % 2 == 0 and region.stop % 2 == 0
        assert (region.stop - region.start) % region.step == 0

        await self._start_addr.set(region.start)
        await self._stop_addr.set(region.stop)
        await self._block_size.set(region.step)
        for pattern in patterns:
            try:
                await self._pattern.set(pattern)
                await self._active.set(1)
                while (await self._cycles.get()) < 1:
                    await asyncio.sleep(0.1)
                errors = await self._errors.get()
                if errors > 0:
                    self._logger.warning("address %08x: expected %04x, actual %04x (%s)",
                        await self._error_addr.get(),
                        await self._error_gold.get(),
                        await self._error_data.get(),
                        pattern)
                    return errors
            finally:
                await self._active.set(0)
        return 0


class MemoryTestApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "diagnose issues with onboard RAM"
    description = """
    Run a simple memory test procedure to diagnose memory issues. Our patented memtest67™ algorithm
    works as follows:

    * For each pattern in (``Const0``, ``Const1``, ``Alt01``, ``Alt10``, ``PRBS``) do:
        * For each sequential block of specified size in the specified region, do:
            * Write pattern sequence to memory block
            * Read memory block and compare with pattern sequence
    """
    required_revision = "D0"

    @classmethod
    def add_build_arguments(cls, parser, access):
        pass

    def build(self, args):
        with self.assembly.add_applet(self):
            self.memtest_ifaces = [
                MemoryTestInterface(self.logger, self.assembly),
                MemoryTestInterface(self.logger, self.assembly),
            ]

    @classmethod
    def add_run_arguments(cls, parser):
        def address(arg):
            return int(arg, 16)

        parser.add_argument(
            "-c", "--channel", dest="channels", metavar="INDEX",
            choices=(0, 1), nargs="*", default=(0, 1),
            help="memory channel (one of: 0, 1)")
        parser.add_argument(
            "-a", "--start-addr", metavar="HEX-ADDR", type=address, default=0,
            help="start of region (default: zero)")
        parser.add_argument(
            "-b", "--stop-addr", metavar="HEX-ADDR", type=address, default=64 << 20,
            help="end of region, exclusive (default: 64 MB)")
        parser.add_argument(
            "-s", "--block-size", metavar="SIZE", type=int,
            choices=tuple(1<<n for n in range(1, 12)), default=1024,
            help="block size (power of two, 2..2048, default: %(default)s)")
        parser.add_argument(
            "-n", "--cycles", metavar="COUNT", type=int, default=1,
            help="repeat memory test COUNT times")

    async def run(self, args):
        region = range(args.start_addr, args.stop_addr, args.block_size)
        failed = False
        for cycle in range(args.cycles):
            for channel in set(args.channels):
                bit_errors = await self.memtest_ifaces[channel].run(region)
                if bit_errors == 0:
                    self.logger.info("channel %d: cycle %3d/%3d PASS",
                        channel, 1 + cycle, args.cycles)
                else:
                    self.logger.error("channel %d: cycle %3d/%3d FAIL (%d bit errors)",
                        channel, 1 + cycle, args.cycles, bit_errors)
                    failed = True
        if not failed:
            self.logger.info("test PASS")
        else:
            self.logger.error("test FAIL")

    @classmethod
    def tests(cls):
        from . import test
        return test.MemoryTestAppletTestCase
