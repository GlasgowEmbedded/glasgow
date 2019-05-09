import struct
import logging
import asyncio
import math
from migen import *
from migen.genlib.cdc import *

from ....support.logging import *
from ....gateware.clockgen import *
from ... import *


class SPIMasterBus(Module):
    def __init__(self, pads, sck_idle, sck_edge, ss_active):
        self.oe   = Signal(reset=1)

        self.sck  = Signal(reset=sck_idle)
        self.ss   = Signal(reset=not ss_active)
        self.mosi = Signal()
        self.miso = Signal()

        self.comb += [
            pads.sck_t.oe.eq(self.oe),
            pads.sck_t.o.eq(self.sck),
        ]
        if hasattr(pads, "ss_t"):
            self.comb += [
                pads.ss_t.oe.eq(1),
                pads.ss_t.o.eq(self.ss),
            ]
        if hasattr(pads, "mosi_t"):
            self.comb += [
                pads.mosi_t.oe.eq(self.oe),
                pads.mosi_t.o.eq(self.mosi)
            ]
        if hasattr(pads, "miso_t"):
            self.specials += \
                MultiReg(pads.miso_t.i, self.miso)

        sck_r = Signal()
        self.sync += sck_r.eq(self.sck)

        self.setup = Signal()
        self.latch = Signal()
        if sck_edge in ("r", "rising"):
            self.comb += [
                self.setup.eq(sck_r & ~self.sck),
                self.latch.eq(~sck_r & self.sck),
            ]
        elif sck_edge in ("f", "falling"):
            self.comb += [
                self.setup.eq(~sck_r & self.sck),
                self.latch.eq(sck_r & ~self.sck),
            ]
        else:
            assert False


CMD_XFER    = 0x00
CMD_READ    = 0x01
CMD_WRITE   = 0x02
CMD_DELAY   = 0x03
CMD_SYNC    = 0x04
BIT_HOLD_SS = 0x80


class SPIMasterSubtarget(Module):
    def __init__(self, pads, out_fifo, in_fifo, period_cyc, delay_cyc,
                 sck_idle, sck_edge, ss_active):
        self.submodules.bus = SPIMasterBus(pads, sck_idle, sck_edge, ss_active)

        ###

        self.submodules.clkgen = ResetInserter()(ClockGen(period_cyc))

        oreg  = Signal(8)
        ireg  = Signal(8)
        self.comb += [
            self.bus.sck.eq(self.clkgen.clk),
            self.bus.mosi.eq(oreg[oreg.nbits - 1]),
        ]
        self.sync += [
            If(self.bus.setup,
                oreg[1:].eq(oreg)
            ).Elif(self.bus.latch,
                ireg.eq(Cat(self.bus.miso, ireg))
            )
        ]

        cmd   = Signal(8)
        count = Signal(16)
        bitno = Signal(max=8 + 1)
        timer = Signal(max=delay_cyc)

        self.submodules.fsm = FSM(reset_state="RECV-COMMAND")
        self.fsm.act("RECV-COMMAND",
            in_fifo.flush.eq(1),
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(cmd, out_fifo.dout),
                If(out_fifo.dout == CMD_SYNC,
                    NextState("SYNC")
                ).Else(
                    NextState("RECV-COUNT-MSB")
                )
            )
        )
        self.fsm.act("RECV-COUNT-MSB",
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(count[8:16], out_fifo.dout),
                NextState("RECV-COUNT-LSB")
            )
        )
        self.fsm.act("RECV-COUNT-LSB",
             If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(count[0:8], out_fifo.dout),
                If(cmd == CMD_DELAY,
                    NextState("DELAY")
                ).Else(
                    NextState("COUNT-CHECK")
                )
             )
        )
        self.fsm.act("COUNT-CHECK",
            If(count == 0,
                NextState("RECV-COMMAND"),
                If((cmd & BIT_HOLD_SS) != 0,
                    NextValue(self.bus.ss, ss_active),
                ),
            ).Else(
                NextValue(self.bus.ss, ss_active),
                NextState("RECV-DATA")
            )
        )
        self.fsm.act("RECV-DATA",
            If(cmd[:4] != CMD_READ,
                out_fifo.re.eq(1),
                NextValue(oreg, out_fifo.dout),
            ).Else(
                NextValue(oreg, 0)
            ),
            If((cmd[:4] == CMD_READ) | out_fifo.readable,
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
            If(cmd[:4] != CMD_WRITE,
                in_fifo.din.eq(ireg),
                in_fifo.we.eq(1),
            ),
            If((cmd[:4] == CMD_WRITE) | in_fifo.writable,
                If(count == 0,
                    If((cmd & BIT_HOLD_SS) == 0,
                        NextValue(self.bus.ss, not ss_active),
                    ),
                    NextState("WAIT")
                ).Else(
                    NextState("RECV-DATA")
                )
            )
        )
        self.fsm.act("WAIT",
            If(timer == 0,
                NextState("RECV-COMMAND")
            ).Else(
                NextValue(timer, timer - 1)
            )
        )
        self.fsm.act("DELAY",
            If(timer == 0,
                If(count == 0,
                    NextState("RECV-COMMAND")
                ).Else(
                    NextValue(count, count - 1),
                    NextValue(timer, delay_cyc),
                )
            ).Else(
                NextValue(timer, timer - 1)
            )
        )
        self.fsm.act("SYNC",
            If(in_fifo.writable,
                in_fifo.we.eq(1),
                in_fifo.din.eq(0),
                NextState("RECV-COMMAND")
            )
        )


class SPIMasterInterface:
    def __init__(self, interface, logger):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

    def _log(self, message, *args):
        self._logger.log(self._level, "SPI: " + message, *args)

    async def reset(self):
        self._log("reset")
        await self.lower.reset()

    async def transfer(self, data, hold_ss=False):
        assert len(data) <= 0xffff
        data = bytes(data)

        self._log("xfer-out=<%s>", dump_hex(data))

        cmd = CMD_XFER | (BIT_HOLD_SS if hold_ss else 0)
        await self.lower.write(struct.pack(">BH", cmd, len(data)))
        await self.lower.write(data)
        data = await self.lower.read(len(data))

        self._log("xfer-in=<%s>", dump_hex(data))

        return data

    async def read(self, count, hold_ss=False):
        assert count <= 0xffff

        cmd = CMD_READ | (BIT_HOLD_SS if hold_ss else 0)
        await self.lower.write(struct.pack(">BH", cmd, count))
        data = await self.lower.read(count)

        self._log("read-in=<%s>", dump_hex(data))

        return data

    async def write(self, data, hold_ss=False):
        assert len(data) <= 0xffff
        data = bytes(data)

        self._log("write-out=<%s>", dump_hex(data))

        cmd = CMD_WRITE | (BIT_HOLD_SS if hold_ss else 0)
        await self.lower.write(struct.pack(">BH", cmd, len(data)))
        await self.lower.write(data)

    async def delay_us(self, delay):
        if delay == 0:
            return

        self._log("delay=%d us", delay)

        while delay > 0xffff:
            await self.lower.write(struct.pack(">BH", CMD_DELAY, 0xffff))
            delay -= 0xffff
        await self.lower.write(struct.pack(">BH", CMD_DELAY, delay))

    async def delay_ms(self, delay):
        await self.delay_us(delay * 1000)

    async def synchronize(self):
        self._log("sync")

        await self.lower.write([CMD_SYNC])
        await self.lower.read(1)


class SPIMasterApplet(GlasgowApplet, name="spi-master"):
    logger = logging.getLogger(__name__)
    help = "initiate SPI transactions"
    description = """
    Initiate transactions on the SPI bus.

    Maximum transaction length is 65535 bytes.
    """

    __pins = ("sck", "ss", "mosi", "miso")

    @classmethod
    def add_build_arguments(cls, parser, access, omit_pins=False):
        super().add_build_arguments(parser, access)

        if not omit_pins:
            access.add_pin_argument(parser, "sck", required=True)
            access.add_pin_argument(parser, "ss")
            access.add_pin_argument(parser, "mosi")
            access.add_pin_argument(parser, "miso")

        parser.add_argument(
            "-b", "--bit-rate", metavar="FREQ", type=int, default=100,
            help="set SPI bit rate to FREQ kHz (default: %(default)s)")
        parser.add_argument(
            "--sck-idle", metavar="LEVEL", type=int, choices=[0, 1], default=0,
            help="set idle clock level to LEVEL (default: %(default)s)")
        parser.add_argument(
            "--sck-edge", metavar="EDGE", type=str, choices=["r", "rising", "f", "falling"],
            default="rising",
            help="latch data at clock edge EDGE (default: %(default)s)")
        parser.add_argument(
            "--ss-active", metavar="LEVEL", type=int, choices=[0, 1], default=0,
            help="set active chip select level to LEVEL (default: %(default)s)")

    def build(self, target, args, pins=__pins):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        return iface.add_subtarget(SPIMasterSubtarget(
            pads=iface.get_pads(args, pins=pins),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(auto_flush=False),
            period_cyc=self.derive_clock(input_hz=target.sys_clk_freq,
                                         output_hz=args.bit_rate * 1000,
                                         clock_name="master",
                                         # 2 cyc MultiReg delay from SCK to MISO requires a 4 cyc
                                         # period with current implementation of SERDES
                                         min_cyc=4),
            delay_cyc=self.derive_clock(input_hz=target.sys_clk_freq,
                                        output_hz=1e6,
                                        clock_name="delay"),
            sck_idle=args.sck_idle,
            sck_edge=args.sck_edge,
            ss_active=args.ss_active,
        ))

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        spi_iface = SPIMasterInterface(iface, self.logger)
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

class SPIMasterAppletTestCase(GlasgowAppletTestCase, applet=SPIMasterApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--pin-sck",  "0", "--pin-ss",   "1",
                                "--pin-mosi", "2", "--pin-miso", "3"])

    def setup_loopback(self):
        self.build_simulated_applet()
        mux_iface = self.applet.mux_interface
        mux_iface.comb += mux_iface.pads.miso_t.i.eq(mux_iface.pads.mosi_t.o)

    @applet_simulation_test("setup_loopback",
                            ["--pin-sck",  "0", "--pin-ss", "1",
                             "--pin-mosi", "2", "--pin-miso",   "3",
                             "--bit-rate", "5000"])
    @asyncio.coroutine
    def test_loopback(self):
        mux_iface = self.applet.mux_interface
        spi_iface = yield from self.run_simulated_applet()

        self.assertEqual((yield mux_iface.pads.ss_t.o), 1)
        result = yield from spi_iface.transfer([0xAA, 0x55, 0x12, 0x34])
        self.assertEqual(result, bytearray([0xAA, 0x55, 0x12, 0x34]))
        self.assertEqual((yield mux_iface.pads.ss_t.o), 1)
