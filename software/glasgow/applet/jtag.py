import struct
import logging
import asyncio
from bitarray import bitarray
from migen import *
from migen.genlib.cdc import MultiReg
from migen.genlib.fsm import FSM

from . import *
from ..gateware.pads import *


class JTAGBus(Module):
    def __init__(self, pads):
        self.tck  = Signal(reset=1)
        self.tms  = Signal(reset=1)
        self.tdo  = Signal(reset=1)
        self.tdi  = Signal(reset=1)
        self.trst = Signal(reset=1)

        ###

        self.comb += [
            pads.tck_t.oe.eq(1),
            pads.tck_t.o.eq(self.tck),
            pads.tms_t.oe.eq(1),
            pads.tms_t.o.eq(self.tms),
            pads.tdi_t.oe.eq(1),
            pads.tdi_t.o.eq(self.tdi),
        ]
        self.specials += [
            MultiReg(pads.tdo_t.i, self.tdo),
        ]
        if hasattr(pads, "trst_t"):
            self.comb += [
                pads.trst_t.oe.eq(1),
                pads.trst_t.o.eq(self.trst)
            ]


CMD_MASK       = 0b11110000
CMD_RESET      = 0b00000000
CMD_SHIFT_TMS  = 0b00100000
CMD_SHIFT_TDIO = 0b00110000
BIT_DATA_OUT   =     0b0001
BIT_DATA_IN    =     0b0010
BIT_LAST       =     0b0100


class JTAGSubtarget(Module):
    def __init__(self, pads, out_fifo, in_fifo, period_cyc):
        self.submodules.bus = bus = JTAGBus(pads)

        ###

        half_cyc  = int(period_cyc // 2)
        timer     = Signal(max=half_cyc)
        timer_rdy = Signal()
        timer_stb = Signal()
        self.comb += timer_rdy.eq(timer == 0)
        self.sync += [
            If(~timer_rdy,
                timer.eq(timer - 1)
            ).Elif(timer_stb,
                timer.eq(half_cyc - 1)
            )
        ]

        cmd     = Signal(8)
        count   = Signal(16)
        bit     = Signal(3)
        align   = Signal(3)
        shreg_o = Signal(8)
        shreg_i = Signal(8)

        self.submodules.fsm = FSM(reset_state="RECV-COMMAND")
        self.fsm.act("RECV-COMMAND",
            If(timer_rdy & out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(cmd, out_fifo.dout),
                NextState("COMMAND")
            )
        )
        self.fsm.act("COMMAND",
            If((cmd & CMD_MASK) == CMD_RESET,
                timer_stb.eq(1),
                NextValue(bus.trst, 0),
                NextState("TEST-RESET")
            ).Elif(((cmd & CMD_MASK) == CMD_SHIFT_TMS) |
                   ((cmd & CMD_MASK) == CMD_SHIFT_TDIO),
                NextState("RECV-COUNT-1")
            ).Else(
                NextState("RECV-COMMAND")
            )
        )
        self.fsm.act("TEST-RESET",
            If(timer_rdy,
                NextValue(bus.trst, 1),
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
                NextState("RECV-BITS")
            )
        )
        self.fsm.act("RECV-BITS",
            If(count == 0,
                NextState("RECV-COMMAND")
            ).Else(
                If(count > 8,
                    NextValue(bit, 0)
                ).Else(
                    NextValue(align, 8 - count),
                    NextValue(bit, 8 - count)
                ),
                If(cmd & BIT_DATA_OUT,
                    If(out_fifo.readable,
                        out_fifo.re.eq(1),
                        NextValue(shreg_o, out_fifo.dout),
                        NextState("SHIFT-SETUP")
                    )
                ).Else(
                    NextValue(shreg_o, 0b11111111),
                    NextState("SHIFT-SETUP")
                )
            )
        )
        self.fsm.act("SHIFT-SETUP",
            If(timer_rdy,
                timer_stb.eq(1),
                If((cmd & CMD_MASK) == CMD_SHIFT_TMS,
                    NextValue(bus.tms, shreg_o[0]),
                    NextValue(bus.tdi, 0),
                ).Else(
                    NextValue(bus.tms, 0),
                    If(cmd & BIT_LAST,
                        NextValue(bus.tms, count == 1)
                    ),
                    NextValue(bus.tdi, shreg_o[0]),
                ),
                NextValue(bus.tck, 0),
                NextValue(shreg_o, Cat(shreg_o[1:], 1)),
                NextValue(count, count - 1),
                NextValue(bit, bit + 1),
                NextState("SHIFT-HOLD")
            )
        )
        self.fsm.act("SHIFT-HOLD",
            If(timer_rdy,
                timer_stb.eq(1),
                NextValue(bus.tck, 1),
                NextValue(shreg_i, Cat(shreg_i[1:], bus.tdo)),
                If(bit == 0,
                    NextState("SEND-BITS")
                ).Else(
                    NextState("SHIFT-SETUP")
                )
            )
        )
        self.fsm.act("SEND-BITS",
            If(cmd & BIT_DATA_IN,
                If(in_fifo.writable,
                    in_fifo.we.eq(1),
                    If(count == 0,
                        in_fifo.din.eq(shreg_i >> align)
                    ).Else(
                        in_fifo.din.eq(shreg_i)
                    ),
                    NextState("RECV-BITS")
                )
            ).Else(
                NextState("RECV-BITS")
            )
        )


class JTAGInterface:
    def __init__(self, interface, logger):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

    def _log(self, message, *args):
        self._logger.log(self._level, "JTAG: " + message, *args)

    # Low-level JTAG commands

    async def shift_tms(self, tms_bits):
        tms_bits = bitarray(tms_bits, endian="little")
        self._log("shift tms=<%s>", tms_bits.to01())
        await self.lower.write(struct.pack("<BH",
            CMD_SHIFT_TMS|BIT_DATA_OUT, len(tms_bits)))
        await self.lower.write(tms_bits.tobytes())

    async def shift_tdio(self, tdi_bits):
        tdi_bits = bitarray(tdi_bits, endian="little")
        tdo_bits = bitarray(endian="little")
        self._log("shift tdio-i=<%s>", tdi_bits.to01())
        await self.lower.write(struct.pack("<BH",
            CMD_SHIFT_TDIO|BIT_DATA_IN|BIT_DATA_OUT|BIT_LAST, len(tdi_bits)))
        tdi_bytes = tdi_bits.tobytes()
        await self.lower.write(tdi_bytes)
        tdo_bytes = await self.lower.read(len(tdi_bytes))
        tdo_bits.frombytes(bytes(tdo_bytes))
        while len(tdo_bits) > len(tdi_bits): tdo_bits.pop()
        self._log("shift tdio-o=<%s>", tdo_bits.to01())
        return tdo_bits

    async def shift_tdi(self, tdi_bits):
        tdi_bits = bitarray(tdi_bits, endian="little")
        self._log("shift tdi=<%s>", tdi_bits.to01())
        await self.lower.write(struct.pack("<BH",
            CMD_SHIFT_TDIO|BIT_DATA_OUT|BIT_LAST, len(tdi_bits)))
        tdi_bytes = tdi_bits.tobytes()
        await self.lower.write(tdi_bytes)

    async def shift_tdo(self, count):
        tdo_bits = bitarray(endian="little")
        await self.lower.write(struct.pack("<BH",
            CMD_SHIFT_TDIO|BIT_DATA_IN|BIT_LAST, count))
        tdo_bytes = await self.lower.read((count + 7) // 8)
        tdo_bits.frombytes(bytes(tdo_bytes))
        while len(tdo_bits) > count: tdo_bits.pop()
        self._log("shift tdo=<%s>", tdo_bits.to01())
        return tdo_bits

    async def clock(self, count):
        self._log("clock count=%d", count)
        await self.lower.write(struct.pack("<BH",
            CMD_SHIFT_TDIO, count))

    # High-level JTAG commands

    async def test_reset(self):
        self._log("test reset")
        await self.shift_tms("111110")

    async def shift_ir_out(self, count):
        self._log("shift ir")
        await self.shift_tms("1100")
        data = await self.shift_tdo(count)
        await self.shift_tms("10")
        return data

    async def shift_ir_in(self, data):
        self._log("shift ir")
        await self.shift_tms("1100")
        await self.shift_tdi(data)
        await self.shift_tms("10")

    async def shift_dr(self, data):
        self._log("shift dr")
        await self.shift_tms("100")
        data = await self.shift_tdio(data)
        await self.shift_tms("10")
        return data


class JTAGApplet(GlasgowApplet, name="jtag"):
    logger = logging.getLogger(__name__)
    help = "test integrated circuits via JTAG"
    description = """
    Identify, test and debug integrated circuits and board assemblies via JTAG.
    """

    __pins = ("tck", "tms", "tdi", "tdo", "trst")

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        for pin in ("tck", "tms", "tdi", "tdo"):
            access.add_pin_argument(parser, pin, default=True)
        access.add_pin_argument(parser, "trst")

        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=100000,
            help="set clock period to FREQ Hz (default: %(default)s)")

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        iface.add_subtarget(JTAGSubtarget(
            pads=iface.get_pads(args, pins=self.__pins),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(),
            period_cyc=target.sys_clk_freq // args.frequency,
        ))

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        return JTAGInterface(iface, self.logger)

    @classmethod
    def add_interact_arguments(cls, parser):
        pass

    async def interact(self, device, args, jtag_iface):
        await jtag_iface.test_reset()
        ir_chain = await jtag_iface.shift_ir_out(32)
        self.logger.info("IR chain: <%s>", ir_chain.to01())

        await jtag_iface.test_reset()
        idcode = await jtag_iface.shift_dr("1"*32)
        idcode, = struct.unpack("<L", idcode[0:].tobytes())
        self.logger.info("IDCODE %#010x", idcode)
        await jtag_iface.lower.flush()

# -------------------------------------------------------------------------------------------------

class JTAGAppletTestCase(GlasgowAppletTestCase, applet=JTAGApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
