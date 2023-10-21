import struct
import logging
import math
from amaranth import *
from amaranth.lib.cdc import FFSynchronizer

from ....support.logging import *
from ....gateware.clockgen import *
from ... import *


class SPIControllerBus(Elaboratable):
    def __init__(self, pads, sck_idle, sck_edge, cs_active):
        self.pads = pads
        self.sck_idle = sck_idle
        self.sck_edge = sck_edge
        self.cs_active = cs_active

        self.oe   = Signal(reset=1)

        self.sck  = Signal(reset=sck_idle)
        self.cs   = Signal(reset=not cs_active)
        self.copi = Signal()
        self.cipo = Signal()

        self.setup = Signal()
        self.latch = Signal()

    def elaborate(self, platform):
        m = Module()

        m.d.comb += [
            self.pads.sck_t.oe.eq(self.oe),
            self.pads.sck_t.o.eq(self.sck),
        ]
        if hasattr(self.pads, "cs_t"):
            m.d.comb += [
                self.pads.cs_t.oe.eq(1),
                self.pads.cs_t.o.eq(self.cs),
            ]
        if hasattr(self.pads, "copi_t"):
            m.d.comb += [
                self.pads.copi_t.oe.eq(self.oe),
                self.pads.copi_t.o.eq(self.copi)
            ]
        if hasattr(self.pads, "cipo_t"):
            m.submodules += FFSynchronizer(self.pads.cipo_t.i, self.cipo)

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
CMD_SHIFT    = 0b00000000
CMD_DELAY    = 0b00010000
CMD_SYNC     = 0b00100000
# CMD_SHIFT
BIT_DATA_OUT =     0b0001
BIT_DATA_IN  =     0b0010
BIT_HOLD_SS  =     0b0100


class SPIControllerSubtarget(Elaboratable):
    def __init__(self, pads, out_fifo, in_fifo, period_cyc, delay_cyc,
                 sck_idle, sck_edge, cs_active):
        self.pads = pads
        self.out_fifo = out_fifo
        self.in_fifo = in_fifo
        self.period_cyc = period_cyc
        self.delay_cyc = delay_cyc
        self.cs_active = cs_active

        self.bus = SPIControllerBus(pads, sck_idle, sck_edge, cs_active)

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
                    with m.If((self.out_fifo.r_data & CMD_MASK) == CMD_SYNC):
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
                    with m.If((cmd & BIT_HOLD_SS) != 0):
                        m.d.sync += self.bus.cs.eq(self.cs_active)
                with m.Else():
                    m.d.sync += self.bus.cs.eq(self.cs_active)
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
                        with m.If((cmd & BIT_HOLD_SS) == 0):
                            m.d.sync += self.bus.cs.eq(not self.cs_active)
                        m.next = "RECV-COMMAND"
                    with m.Else():
                        m.next = "RECV-DATA"

        return m


class SPIControllerInterface:
    def __init__(self, interface, logger):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

    def _log(self, message, *args):
        self._logger.log(self._level, "SPI: " + message, *args)

    async def reset(self):
        self._log("reset")
        await self.lower.reset()

    @staticmethod
    def _chunk_count(count, hold_ss, chunk_size=0xffff):
        while count > chunk_size:
            yield chunk_size, True
            count -= chunk_size
        yield count, hold_ss

    @staticmethod
    def _chunk_bytes(bytes, hold_ss, chunk_size=0xffff):
        offset = 0
        while len(bytes) - offset > chunk_size:
            yield bytes[offset:offset + chunk_size], True
            offset += chunk_size
        yield bytes[offset:], hold_ss

    async def transfer(self, data, hold_ss=False):
        try:
            out_data = memoryview(data)
        except TypeError:
            out_data = memoryview(bytes(data))
        self._log("xfer-out=<%s>", dump_hex(out_data))
        in_data = []
        for out_data, hold_ss in self._chunk_bytes(out_data, hold_ss):
            await self.lower.write(struct.pack("<BH",
                CMD_SHIFT|BIT_DATA_IN|BIT_DATA_OUT|(BIT_HOLD_SS if hold_ss else 0),
                len(out_data)))
            await self.lower.write(out_data)
            in_data.append(await self.lower.read(len(out_data)))
        in_data = b"".join(in_data)
        self._log("xfer-in=<%s>", dump_hex(in_data))
        return in_data

    async def read(self, count, hold_ss=False):
        in_data = []
        for count, hold_ss in self._chunk_count(count, hold_ss):
            await self.lower.write(struct.pack("<BH",
                CMD_SHIFT|BIT_DATA_IN|(BIT_HOLD_SS if hold_ss else 0),
                count))
            in_data.append(await self.lower.read(count))
        in_data = b"".join(in_data)
        self._log("read-in=<%s>", dump_hex(in_data))
        return in_data

    async def write(self, data, hold_ss=False):
        try:
            out_data = memoryview(data)
        except TypeError:
            out_data = memoryview(bytes(data))
        self._log("write-out=<%s>", dump_hex(out_data))
        for out_data, hold_ss in self._chunk_bytes(out_data, hold_ss):
            await self.lower.write(struct.pack("<BH",
                CMD_SHIFT|BIT_DATA_OUT|(BIT_HOLD_SS if hold_ss else 0),
                len(out_data)))
            await self.lower.write(out_data)

    async def delay_us(self, delay):
        self._log("delay=%d us", delay)
        while delay > 0xffff:
            await self.lower.write(struct.pack("<BH", CMD_DELAY, 0xffff))
            delay -= 0xffff
        await self.lower.write(struct.pack("<BH", CMD_DELAY, delay))

    async def delay_ms(self, delay):
        await self.delay_us(delay * 1000)

    async def synchronize(self):
        self._log("sync")
        await self.lower.write([CMD_SYNC])
        await self.lower.read(1)


class SPIControllerApplet(GlasgowApplet):
    logger = logging.getLogger(__name__)
    help = "initiate SPI transactions"
    description = """
    Initiate transactions on the SPI bus.
    """

    __pins = ("sck", "cs", "copi", "cipo")

    @classmethod
    def add_build_arguments(cls, parser, access, omit_pins=False):
        super().add_build_arguments(parser, access)

        if not omit_pins:
            access.add_pin_argument(parser, "sck", required=True)
            access.add_pin_argument(parser, "cs")
            access.add_pin_argument(parser, "copi")
            access.add_pin_argument(parser, "cipo")

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
        parser.add_argument(
            "--cs-active", metavar="LEVEL", type=int, choices=[0, 1], default=0,
            help="set active chip select level to LEVEL (default: %(default)s)")

    def build_subtarget(self, target, args, pins=__pins):
        iface = self.mux_interface
        return SPIControllerSubtarget(
            pads=iface.get_pads(args, pins=pins),
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
            cs_active=args.cs_active,
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
            "data", metavar="DATA", type=hex,
            help="hex bytes to transfer to the device")

    async def interact(self, device, args, spi_iface):
        data = await spi_iface.transfer(args.data)
        print(data.hex())

    @classmethod
    def tests(cls):
        from . import test
        return test.SPIControllerAppletTestCase
