import math
import struct
import logging
import contextlib
from amaranth import *
from amaranth.lib import io
from amaranth.lib.cdc import FFSynchronizer

from ....support.logging import *
from ....gateware.clockgen import *
from ... import *


class SPIControllerBus(Elaboratable):
    def __init__(self, ports, sck_idle, sck_edge):
        self.ports = ports
        self.sck_idle = sck_idle
        self.sck_edge = sck_edge

        self.oe   = Signal(init=1)

        self.sck  = Signal(init=sck_idle)
        self.cs   = Signal()
        self.copi = Signal()
        self.cipo = Signal()

        self.setup = Signal()
        self.latch = Signal()

    def elaborate(self, platform):
        m = Module()

        m.submodules.sck_buffer = sck_buffer = io.Buffer("o", self.ports.sck)

        m.d.comb += [
            sck_buffer.oe.eq(self.oe),
            sck_buffer.o.eq(self.sck),
        ]

        if hasattr(self.ports, "cs"):
            if self.ports.cs is not None:
                m.submodules.cs_buffer = cs_buffer = io.Buffer("o", self.ports.cs)
                m.d.comb += cs_buffer.o.eq(~self.cs),

        if hasattr(self.ports, "copi"):
            if self.ports.copi is not None:
                m.submodules.copi_buffer = copi_buffer = io.Buffer("o", self.ports.copi)
                m.d.comb += [
                    copi_buffer.oe.eq(self.oe),
                    copi_buffer.o.eq(self.copi)
                ]

        if hasattr(self.ports, "cipo"):
            if self.ports.cipo is not None:
                m.submodules.cipo_buffer = cipo_buffer = io.Buffer("i", self.ports.cipo)
                m.submodules += FFSynchronizer(cipo_buffer.i, self.cipo)

        sck_r = Signal()
        m.d.sync += sck_r.eq(self.sck)

        if self.sck_edge in ("r", "rising"):
            m.d.comb += [
                self.setup.eq( sck_r & ~self.sck),
                self.latch.eq(~sck_r &  self.sck),
            ]
        elif self.sck_edge in ("f", "falling"):
            m.d.comb += [
                self.setup.eq(~sck_r &  self.sck),
                self.latch.eq( sck_r & ~self.sck),
            ]
        else:
            assert False

        return m


CMD_MASK     = 0b11110000
CMD_SELECT   = 0b00000000
CMD_SHIFT    = 0b00010000
CMD_DELAY    = 0b00100000
CMD_SYNC     = 0b00110000
# CMD_SHIFT
BIT_DATA_OUT =     0b0001
BIT_DATA_IN  =     0b0010


class SPIControllerSubtarget(Elaboratable):
    def __init__(self, ports, out_fifo, in_fifo, period_cyc, delay_cyc,
                 sck_idle, sck_edge):
        self.ports = ports
        self.out_fifo = out_fifo
        self.in_fifo = in_fifo
        self.period_cyc = period_cyc
        self.delay_cyc = delay_cyc

        self.bus = SPIControllerBus(ports, sck_idle, sck_edge)

    def elaborate(self, platform):
        m = Module()

        m.submodules.bus = self.bus

        ###

        clkgen_reset = Signal()
        m.submodules.clkgen = clkgen = ResetInserter(clkgen_reset)(ClockGen(self.period_cyc))

        timer    = Signal(range(self.delay_cyc))
        timer_en = Signal()

        with m.If(timer != 0):
            m.d.sync += timer.eq(timer - 1)
        with m.Elif(timer_en):
            m.d.sync += timer.eq(self.delay_cyc - 1)

        shreg_o = Signal(8)
        shreg_i = Signal(8)
        m.d.comb += [
            self.bus.sck.eq(clkgen.clk),
            self.bus.copi.eq(shreg_o[-1]),
        ]

        with m.If(self.bus.setup):
            m.d.sync += shreg_o.eq(Cat(C(0, 1), shreg_o))
        with m.Elif(self.bus.latch):
            m.d.sync += shreg_i.eq(Cat(self.bus.cipo, shreg_i))

        cmd   = Signal(8)
        count = Signal(16)
        bitno = Signal(range(8 + 1))

        with m.FSM() as fsm:
            with m.State("RECV-COMMAND"):
                m.d.comb += self.in_fifo.flush.eq(1)
                with m.If(self.out_fifo.r_rdy):
                    m.d.comb += self.out_fifo.r_en.eq(1)
                    m.d.sync += cmd.eq(self.out_fifo.r_data)
                    with m.If((self.out_fifo.r_data & CMD_MASK) == CMD_SELECT):
                        m.d.sync += self.bus.cs.eq(self.out_fifo.r_data[0])
                    with m.Elif((self.out_fifo.r_data & CMD_MASK) == CMD_SYNC):
                        m.next = "SYNC"
                    with m.Else():
                        m.next = "RECV-COUNT-1"

            with m.State("SYNC"):
                with m.If(self.in_fifo.w_rdy):
                    m.d.comb += [
                        self.in_fifo.w_en.eq(1),
                        self.in_fifo.w_data.eq(0),
                    ]
                    m.next = "RECV-COMMAND"

            with m.State("RECV-COUNT-1"):
                with m.If(self.out_fifo.r_rdy):
                    m.d.comb += self.out_fifo.r_en.eq(1)
                    m.d.sync += count[0:8].eq(self.out_fifo.r_data)
                    m.next = "RECV-COUNT-2"

            with m.State("RECV-COUNT-2"):
                with m.If(self.out_fifo.r_rdy):
                    m.d.comb += self.out_fifo.r_en.eq(1)
                    m.d.sync += count[8:16].eq(self.out_fifo.r_data)
                    with m.If((cmd & CMD_MASK) == CMD_DELAY):
                        m.next = "DELAY"
                    with m.Else():
                        m.next = "COUNT-CHECK"

            with m.State("DELAY"):
                with m.If(timer == 0):
                    with m.If(count == 0):
                        m.next = "RECV-COMMAND"
                    with m.Else():
                        m.d.sync += count.eq(count - 1)
                        m.d.comb += timer_en.eq(1)

            with m.State("COUNT-CHECK"):
                with m.If(count == 0):
                    m.next = "RECV-COMMAND"
                with m.Else():
                    m.next = "RECV-DATA"

            with m.State("RECV-DATA"):
                with m.If((cmd & BIT_DATA_OUT) != 0):
                    m.d.comb += self.out_fifo.r_en.eq(1)
                    m.d.sync += shreg_o.eq(self.out_fifo.r_data)
                with m.Else():
                    m.d.sync += shreg_o.eq(0)

                with m.If(((cmd & BIT_DATA_IN) != 0) | self.out_fifo.r_rdy):
                    m.d.sync += [
                        count.eq(count - 1),
                        bitno.eq(8),
                    ]
                    m.next = "TRANSFER"

            m.d.comb += clkgen_reset.eq(~fsm.ongoing("TRANSFER"))
            with m.State("TRANSFER"):
                with m.If(clkgen.stb_r):
                    m.d.sync += bitno.eq(bitno - 1)
                with m.Elif(clkgen.stb_f):
                    with m.If(bitno == 0):
                        m.next = "SEND-DATA"

            with m.State("SEND-DATA"):
                with m.If((cmd & BIT_DATA_IN) != 0):
                    m.d.comb += [
                        self.in_fifo.w_data.eq(shreg_i),
                        self.in_fifo.w_en.eq(1),
                    ]

                with m.If(((cmd & BIT_DATA_OUT) != 0) | self.in_fifo.w_rdy):
                    with m.If(count == 0):
                        m.next = "RECV-COMMAND"
                    with m.Else():
                        m.next = "RECV-DATA"

        return m


class SPIControllerInterface:
    def __init__(self, interface, logger):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._active = None

    def _log(self, message, *args):
        self._logger.log(self._level, "SPI: " + message, *args)

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
        assert self._active is None, "chip already selected"
        assert index == 0, "only one chip is supported"
        try:
            self._log("select chip=%d", index)
            await self.lower.write(struct.pack("<B",
                CMD_SELECT|(1 + index)))
            self._active = index
            yield
        finally:
            self._log("deselect")
            await self.lower.write(struct.pack("<B",
                CMD_SELECT|0))
            await self.lower.flush()
            self._active = None

    async def exchange(self, octets):
        assert self._active is not None, "no chip selected"
        self._log("xchg-o=<%s>", dump_hex(octets))
        for chunk in self._chunked(octets):
            await self.lower.write(struct.pack("<BH",
                CMD_SHIFT|BIT_DATA_IN|BIT_DATA_OUT, len(chunk)))
            await self.lower.write(chunk)
        octets = await self.lower.read(len(octets))
        self._log("xchg-i=<%s>", dump_hex(octets))
        return octets

    async def write(self, octets, *, x=1):
        assert self._active is not None, "no chip selected"
        assert x == 1, "only x1 mode is supported"
        self._log("write=<%s>", dump_hex(octets))
        for chunk in self._chunked(octets):
            await self.lower.write(struct.pack("<BH",
                CMD_SHIFT|BIT_DATA_OUT, len(chunk)))
            await self.lower.write(chunk)

    async def read(self, count, *, x=1):
        assert self._active is not None, "no chip selected"
        assert x == 1, "only x1 mode is supported"
        for chunk in self._chunked(range(count)):
            await self.lower.write(struct.pack("<BH",
                CMD_SHIFT|BIT_DATA_IN, len(chunk)))
        octets = await self.lower.read(count)
        self._log("read=<%s>", dump_hex(octets))
        return octets

    async def dummy(self, count):
        # We intentionally allow sending dummy cycles with no chip selected.
        self._log("dummy=%d", count)
        for chunk in self._chunked(range(count)):
            assert count % 8 == 0, "only multiples of 8 dummy cycles are supported"
            await self.lower.write(struct.pack("<BH",
                CMD_SHIFT, len(chunk) // 8))

    async def delay_us(self, duration):
        self._log("delay us=%d", duration)
        for chunk in self._chunked(range(duration)):
            await self.lower.write(struct.pack("<BH",
                CMD_DELAY, len(chunk)))

    async def delay_ms(self, duration):
        self._log("delay ms=%d", duration)
        for chunk in self._chunked(range(duration * 1000)):
            await self.lower.write(struct.pack("<BH",
                CMD_DELAY, len(chunk)))

    async def synchronize(self):
        self._log("sync-o")
        await self.lower.write([CMD_SYNC])
        await self.lower.read(1)
        self._log("sync-i")


class SPIControllerApplet(GlasgowApplet):
    logger = logging.getLogger(__name__)
    help = "initiate SPI transactions"
    description = """
    Initiate transactions on the SPI bus.
    """

    @classmethod
    def add_build_arguments(cls, parser, access, omit_pins=False):
        super().add_build_arguments(parser, access)

        if not omit_pins:
            access.add_pins_argument(parser, "sck", required=True)
            access.add_pins_argument(parser, "cs")
            access.add_pins_argument(parser, "copi")
            access.add_pins_argument(parser, "cipo")

        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=100,
            help="set SPI clock frequency to FREQ kHz (default: %(default)s)")
        parser.add_argument(
            "--sck-idle", metavar="LEVEL", type=int, choices=[0, 1], default=0,
            help="set idle clock level to LEVEL (default: %(default)s)")
        parser.add_argument(
            "--sck-edge", metavar="EDGE", type=str, choices=["r", "rising", "f", "falling"],
            default="rising",
            help="latch data at clock edge EDGE (default: %(default)s)")

    def build_subtarget(self, target, args):
        iface = self.mux_interface
        return SPIControllerSubtarget(
            ports=iface.get_port_group(
                sck  = args.sck,
                cs   = args.cs if hasattr(args, "cs") else None,
                copi = args.copi if hasattr(args, "copi") else None,
                cipo = args.cipo if hasattr(args, "cipo") else None
            ),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(auto_flush=False),
            period_cyc=self.derive_clock(input_hz=target.sys_clk_freq,
                                         output_hz=args.frequency * 1000,
                                         clock_name="sck",
                                         # 2 cyc MultiReg delay from SCK to CIPO requires a 4 cyc
                                         # period with current implementation of SERDES
                                         min_cyc=4),
            delay_cyc=self.derive_clock(input_hz=target.sys_clk_freq,
                                        output_hz=1e6,
                                        clock_name="delay"),
            sck_idle=args.sck_idle,
            sck_edge=args.sck_edge,
        )

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        controller = self.build_subtarget(target, args)
        return iface.add_subtarget(controller)

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        spi_iface = SPIControllerInterface(iface, self.logger)
        return spi_iface

    @classmethod
    def add_interact_arguments(cls, parser):
        def hex(arg): return bytes.fromhex(arg)

        parser.add_argument(
            "data", metavar="DATA", type=hex, nargs="+",
            help="hex bytes to exchange with the device")

    async def interact(self, device, args, spi_iface):
        for octets in args.data:
            async with spi_iface.select():
                octets = await spi_iface.exchange(octets)
            print(octets.hex())

    @classmethod
    def tests(cls):
        from . import test
        return test.SPIControllerAppletTestCase
