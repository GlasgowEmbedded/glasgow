import struct
import logging
import asyncio
import math
from nmigen.compat import *
from nmigen.compat.genlib.cdc import *

from ....support.logging import *
from ....gateware.clockgen import *
from ... import *


class SPIControllerBus(Module):
    def __init__(self, pads, sck_idle, sck_edge, cs_active):
        self.oe   = Signal(reset=1)

        self.sck  = Signal(reset=sck_idle)
        self.cs   = Signal(reset=not cs_active)
        self.copi = Signal()
        self.cipo = Signal()

        self.comb += [
            pads.sck_t.oe.eq(self.oe),
            pads.sck_t.o.eq(self.sck),
        ]
        if hasattr(pads, "cs_t"):
            self.comb += [
                pads.cs_t.oe.eq(1),
                pads.cs_t.o.eq(self.cs),
            ]
        if hasattr(pads, "copi_t"):
            self.comb += [
                pads.copi_t.oe.eq(self.oe),
                pads.copi_t.o.eq(self.copi)
            ]
        if hasattr(pads, "cipo_t"):
            self.specials += \
                MultiReg(pads.cipo_t.i, self.cipo)

        sck_r = Signal()
        self.sync += sck_r.eq(self.sck)

        self.setup = Signal()
        self.latch = Signal()
        if sck_edge in ("r", "rising"):
            self.comb += [
                self.setup.eq( sck_r & ~self.sck),
                self.latch.eq(~sck_r &  self.sck),
            ]
        elif sck_edge in ("f", "falling"):
            self.comb += [
                self.setup.eq(~sck_r &  self.sck),
                self.latch.eq( sck_r & ~self.sck),
            ]
        else:
            assert False


CMD_MASK     = 0b11110000
CMD_SHIFT    = 0b00000000
CMD_DELAY    = 0b00010000
CMD_SYNC     = 0b00100000
# CMD_SHIFT
BIT_DATA_OUT =     0b0001
BIT_DATA_IN  =     0b0010
BIT_HOLD_SS  =     0b0100


class SPIControllerSubtarget(Module):
    def __init__(self, pads, out_fifo, in_fifo, period_cyc, delay_cyc,
                 sck_idle, sck_edge, cs_active):
        self.submodules.bus = SPIControllerBus(pads, sck_idle, sck_edge, cs_active)

        ###

        self.submodules.clkgen = ResetInserter()(ClockGen(period_cyc))

        timer    = Signal(max=delay_cyc)
        timer_en = Signal()
        self.sync += [
            If(timer != 0,
                timer.eq(timer - 1)
            ).Elif(timer_en,
                timer.eq(delay_cyc - 1)
            )
        ]

        shreg_o = Signal(8)
        shreg_i = Signal(8)
        self.comb += [
            self.bus.sck.eq(self.clkgen.clk),
            self.bus.copi.eq(shreg_o[-1]),
        ]
        self.sync += [
            If(self.bus.setup,
                shreg_o.eq(Cat(C(0, 1), shreg_o))
            ).Elif(self.bus.latch,
                shreg_i.eq(Cat(self.bus.cipo, shreg_i))
            )
        ]

        cmd   = Signal(8)
        count = Signal(16)
        bitno = Signal(max=8 + 1)

        self.submodules.fsm = FSM(reset_state="RECV-COMMAND")
        self.fsm.act("RECV-COMMAND",
            in_fifo.flush.eq(1),
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(cmd, out_fifo.dout),
                If((out_fifo.dout & CMD_MASK) == CMD_SYNC,
                    NextState("SYNC")
                ).Else(
                    NextState("RECV-COUNT-1")
                )
            )
        )
        self.fsm.act("SYNC",
            If(in_fifo.writable,
                in_fifo.we.eq(1),
                in_fifo.din.eq(0),
                NextState("RECV-COMMAND")
            )
        )
        self.fsm.act("RECV-COUNT-1",
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(count[0:8], out_fifo.dout),
                NextState("RECV-COUNT-2")
            )
        )
        self.fsm.act("RECV-COUNT-2",
             If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(count[8:16], out_fifo.dout),
                If((cmd & CMD_MASK) == CMD_DELAY,
                    NextState("DELAY")
                ).Else(
                    NextState("COUNT-CHECK")
                )
             )
        )
        self.fsm.act("DELAY",
            If(timer == 0,
                If(count == 0,
                    NextState("RECV-COMMAND")
                ).Else(
                    NextValue(count, count - 1),
                    timer_en.eq(1)
                )
            )
        )
        self.fsm.act("COUNT-CHECK",
            If(count == 0,
                NextState("RECV-COMMAND"),
                If((cmd & BIT_HOLD_SS) != 0,
                    NextValue(self.bus.cs, cs_active),
                ),
            ).Else(
                NextValue(self.bus.cs, cs_active),
                NextState("RECV-DATA")
            )
        )
        self.fsm.act("RECV-DATA",
            If((cmd & BIT_DATA_OUT) != 0,
                out_fifo.re.eq(1),
                NextValue(shreg_o, out_fifo.dout),
            ).Else(
                NextValue(shreg_o, 0)
            ),
            If(((cmd & BIT_DATA_IN) != 0) | out_fifo.readable,
                NextValue(count, count - 1),
                NextValue(bitno, 8),
                NextState("TRANSFER")
            )
        )
        self.comb += self.clkgen.reset.eq(~self.fsm.ongoing("TRANSFER")),
        self.fsm.act("TRANSFER",
            If(self.clkgen.stb_r,
                NextValue(bitno, bitno - 1)
            ).Elif(self.clkgen.stb_f,
                If(bitno == 0,
                    NextState("SEND-DATA")
                ),
            )
        )
        self.fsm.act("SEND-DATA",
            If((cmd & BIT_DATA_IN) != 0,
                in_fifo.din.eq(shreg_i),
                in_fifo.we.eq(1),
            ),
            If(((cmd & BIT_DATA_OUT) != 0) | in_fifo.writable,
                If(count == 0,
                    If((cmd & BIT_HOLD_SS) == 0,
                        NextValue(self.bus.cs, not cs_active),
                    ),
                    NextState("RECV-COMMAND")
                ).Else(
                    NextState("RECV-DATA")
                )
            )
        )


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


class SPIControllerApplet(GlasgowApplet, name="spi-controller"):
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

    def build(self, target, args, pins=__pins):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        return iface.add_subtarget(SPIControllerSubtarget(
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
        ))

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

# -------------------------------------------------------------------------------------------------

class SPIControllerAppletTestCase(GlasgowAppletTestCase, applet=SPIControllerApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--pin-sck",  "0", "--pin-cs",   "1",
                                "--pin-copi", "2", "--pin-cipo", "3"])

    def setup_loopback(self):
        self.build_simulated_applet()
        mux_iface = self.applet.mux_interface
        mux_iface.comb += mux_iface.pads.cipo_t.i.eq(mux_iface.pads.copi_t.o)

    @applet_simulation_test("setup_loopback",
                            ["--pin-sck",  "0", "--pin-cs", "1",
                             "--pin-copi", "2", "--pin-cipo",   "3",
                             "--frequency", "5000"])
    @asyncio.coroutine
    def test_loopback(self):
        mux_iface = self.applet.mux_interface
        spi_iface = yield from self.run_simulated_applet()

        self.assertEqual((yield mux_iface.pads.cs_t.o), 1)
        result = yield from spi_iface.transfer([0xAA, 0x55, 0x12, 0x34])
        self.assertEqual(result, bytearray([0xAA, 0x55, 0x12, 0x34]))
        self.assertEqual((yield mux_iface.pads.cs_t.o), 1)
