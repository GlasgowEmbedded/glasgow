import struct
import logging
import asyncio
from migen import *
from migen.genlib.fsm import *
from migen.genlib.cdc import *

from .. import *


class SPIBus(Module):
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
                pads.ss_t.oe.eq(self.oe),
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


class SPIMasterSubtarget(Module):
    def __init__(self, pads, out_fifo, in_fifo, bit_rate, sck_idle, sck_edge, ss_active):
        self.submodules.bus = SPIBus(pads, sck_idle, sck_edge, ss_active)

        ###

        half_cyc = round(30e6 // (bit_rate * 2))
        timer    = Signal(max=half_cyc)

        count = Signal(16)
        bitno = Signal(max=8, reset=7)
        oreg  = Signal(8)
        ireg  = Signal(8)

        self.comb += self.bus.mosi.eq(oreg[oreg.nbits - 1])
        self.sync += [
            If(self.bus.setup,
                oreg[1:].eq(oreg)
            ).Elif(self.bus.latch,
                ireg.eq(Cat(self.bus.miso, ireg))
            )
        ]

        self.submodules.fsm = FSM(reset_state="COUNT-MSB")
        self.fsm.act("COUNT-MSB",
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(count[8:], out_fifo.dout),
                NextState("COUNT-LSB")
            )
        )
        self.fsm.act("COUNT-LSB",
             If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(count[0:], out_fifo.dout),
                NextState("COUNT-CHECK")
             )
        )
        self.fsm.act("COUNT-CHECK",
            If(count == 0,
                NextState("COUNT-MSB")
            ).Else(
                NextValue(self.bus.ss, ss_active),
                NextState("DATA-OUT")
            )
        )
        self.fsm.act("DATA-OUT",
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(count, count - 1),
                NextValue(oreg, out_fifo.dout),
                NextValue(timer, half_cyc - 1),
                NextState("TRANSFER")
            )
        )
        self.fsm.act("TRANSFER",
            If(timer == 0,
                NextValue(timer, half_cyc - 1),
                NextValue(self.bus.sck, ~self.bus.sck),
                If((self.bus.sck == (not sck_idle)),
                    NextValue(bitno, bitno - 1),
                    If(bitno == 0,
                        NextState("DATA-IN")
                    )
                )
            ).Else(
                NextValue(timer, timer - 1)
            )
        )
        self.fsm.act("DATA-IN",
            in_fifo.din.eq(ireg),
            If(in_fifo.writable,
                in_fifo.we.eq(1),
                If(count == 0,
                    NextState("WAIT")
                ).Else(
                    NextState("DATA-OUT")
                )
            )
        )
        self.fsm.act("WAIT",
            If(timer == 0,
                NextValue(self.bus.ss, not ss_active),
                NextState("COUNT-MSB")
            ).Else(
                NextValue(timer, timer - 1)
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

    async def transfer(self, data):
        assert len(data) <= 0xffff
        data = bytes(data)

        self._log("out=<%s>", data.hex())

        await self.lower.write(struct.pack(">H", len(data)))
        await self.lower.write(data)
        data = await self.lower.read(len(data))

        self._log("in=<%s>", data.hex())

        return data


class SPIMasterApplet(GlasgowApplet, name="spi-master"):
    logger = logging.getLogger(__name__)
    help = "initiate SPI transactions"
    description = """
    Initiate transactions on the SPI bus.

    Maximum transaction length is 65535 bytes.
    """

    __pins = ("sck", "ss", "mosi", "miso")

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_argument(parser, "sck", required=True)
        access.add_pin_argument(parser, "ss")
        access.add_pin_argument(parser, "mosi")
        access.add_pin_argument(parser, "miso")

        parser.add_argument(
            "-b", "--bit-rate", metavar="FREQ", type=int, default=100,
            help="set SPI bit rate to FREQ kHz (default: %(default)s)")
        parser.add_argument(
            "--sck-idle", metavar="LEVEL", type=int, choices=[0, 1], default=0,
            help="set idle clock level to LEVEL (default: %(default)s")
        parser.add_argument(
            "--sck-edge", metavar="EDGE", type=str, choices=["r", "rising", "f", "falling"],
            default="rising",
            help="latch data at clock edge EDGE (default: %(default)s")
        parser.add_argument(
            "--ss-active", metavar="LEVEL", type=int, choices=[0, 1], default=0,
            help="set active chip select level to LEVEL (default: %(default)s")

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        return iface.add_subtarget(SPIMasterSubtarget(
            pads=iface.get_pads(args, pins=self.__pins),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(),
            bit_rate=args.bit_rate * 1000,
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
