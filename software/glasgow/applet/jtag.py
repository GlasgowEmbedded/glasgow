import struct
import logging
import asyncio
from bitarray import bitarray
from migen import *
from migen.genlib.cdc import MultiReg
from migen.genlib.fsm import FSM

from . import *
from ..gateware.pads import *
from ..database.jedec import *
from ..pyrepl import *


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
            self.sync += [
                pads.trst_t.oe.eq(1),
                pads.trst_t.o.eq(~self.trst)
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
                NextValue(bus.trst, 1),
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
                NextValue(bus.trst, 0),
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

    # Low-level operations

    async def pulse_trst(self):
        self._log("pulse trst")
        await self.lower.write(struct.pack("<B",
            CMD_RESET))

    async def shift_tms(self, tms_bits):
        tms_bits = bitarray(tms_bits, endian="little")
        self._log("shift tms=<%s>", tms_bits.to01())
        await self.lower.write(struct.pack("<BH",
            CMD_SHIFT_TMS|BIT_DATA_OUT, len(tms_bits)))
        await self.lower.write(tms_bits.tobytes())

    async def shift_tdio(self, tdi_bits, last=True):
        tdi_bits = bitarray(tdi_bits, endian="little")
        tdo_bits = bitarray(endian="little")
        self._log("shift tdio-i=<%s>", tdi_bits.to01())
        await self.lower.write(struct.pack("<BH",
            CMD_SHIFT_TDIO|BIT_DATA_IN|BIT_DATA_OUT|(BIT_LAST if last else 0),
            len(tdi_bits)))
        tdi_bytes = tdi_bits.tobytes()
        await self.lower.write(tdi_bytes)
        tdo_bytes = await self.lower.read(len(tdi_bytes))
        tdo_bits.frombytes(bytes(tdo_bytes))
        while len(tdo_bits) > len(tdi_bits): tdo_bits.pop()
        self._log("shift tdio-o=<%s>", tdo_bits.to01())
        return tdo_bits

    async def shift_tdi(self, tdi_bits, last=True):
        tdi_bits = bitarray(tdi_bits, endian="little")
        self._log("shift tdi=<%s>", tdi_bits.to01())
        await self.lower.write(struct.pack("<BH",
            CMD_SHIFT_TDIO|BIT_DATA_OUT|(BIT_LAST if last else 0),
            len(tdi_bits)))
        tdi_bytes = tdi_bits.tobytes()
        await self.lower.write(tdi_bytes)

    async def shift_tdo(self, count, last=True):
        tdo_bits = bitarray(endian="little")
        await self.lower.write(struct.pack("<BH",
            CMD_SHIFT_TDIO|BIT_DATA_IN|(BIT_LAST if last else 0),
            count))
        tdo_bytes = await self.lower.read((count + 7) // 8)
        tdo_bits.frombytes(bytes(tdo_bytes))
        while len(tdo_bits) > count: tdo_bits.pop()
        self._log("shift tdo=<%s>", tdo_bits.to01())
        return tdo_bits

    async def clock(self, count):
        self._log("clock count=%d", count)
        await self.lower.write(struct.pack("<BH",
            CMD_SHIFT_TDIO, count))

    # State machine transitions

    async def _enter_run_test_idle(self):
        await self.pulse_trst()
        await self.shift_tms("11111") # * -> Test-Logic-Reset
        await self.shift_tms("0") # Test-Logic-Reset -> Run-Test/Idle

    async def _enter_shift_dr(self):
        await self.shift_tms("100") # Run-Test/Idle -> Shift-DR

    async def _enter_shift_ir(self):
        await self.shift_tms("1100") # Run-Test/Idle -> Shift-IR

    async def _leave_shift_xr(self):
        await self.shift_tms("10") # Shift-?R -> Run-Test/Idle

    # High-level register manipulation

    async def test_reset(self):
        self._log("test reset")
        await self._enter_run_test_idle()

    async def shift_ir_out(self, count):
        self._log("shift ir")
        await self._enter_shift_ir()
        data = await self.shift_tdo(count)
        await self._leave_shift_xr()
        return data

    async def shift_ir_in(self, data):
        self._log("shift ir")
        await self._enter_shift_ir()
        await self.shift_tdi(data)
        await self._leave_shift_xr()

    async def shift_dr(self, data):
        self._log("shift dr")
        await self._enter_shift_dr()
        data = await self.shift_tdio(data)
        await self._leave_shift_xr()
        return data

    async def shift_dr_out(self, count):
        self._log("shift dr")
        await self._enter_shift_dr()
        data = await self.shift_tdo(count)
        await self._leave_shift_xr()
        return data

    async def shift_dr_in(self, data):
        self._log("shift dr")
        await self._enter_shift_dr()
        await self.shift_tdi(data)
        await self._leave_shift_xr()

    # Specialized operations

    async def scan_idcode(self, limit=8):
        await self.test_reset()

        self._log("shift idcode")
        await self._enter_shift_dr()

        idcodes = []
        idcode_bits = bitarray()
        while len(idcodes) < limit:
            while len(idcodes) < limit:
                first_bit = await self.shift_tdo(1, last=False)
                if first_bit[0]:
                    break # IDCODE
                else:
                    idcodes.append(None)
                    pass  # BYPASS
            else:
                return None

            idcode_bits = first_bit + await self.shift_tdo(31, last=False)
            idcode, = struct.unpack("<L", idcode_bits.tobytes())
            if idcode == 0xffffffff:
                break
            idcodes.append(idcode)

        await self._leave_shift_xr()
        return idcodes


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
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION")

        p_scan = p_operation.add_parser(
            "scan", help="scan JTAG chain and attempt to identify devices",
            description="""
            Reset the JTAG TAPs and shift IDCODE or BYPASS register values out to determine
            the count and (hopefully) identity of the devices in the scan chain.
            """)

        p_operation.add_parser(
            "repl", help="drop into Python shell; use `jtag_iface` to communicate")

    async def interact(self, device, args, jtag_iface):
        if args.operation == "scan":
            idcodes = await jtag_iface.scan_idcode()
            if not idcodes:
                self.logger.warning("chain scan discovered no devices")
            else:
                for n, idcode in enumerate(idcodes):
                    if idcode is None:
                        self.logger.info("TAP #%d: BYPASS", n)
                    else:
                        mfg_id   = (idcode >>  1) &  0x7ff
                        mfg_name = jedec_mfg_name_from_bank_id(mfg_id >> 7, mfg_id & 0x7f) or \
                                        "unknown"
                        part_id  = (idcode >> 12) & 0xffff
                        version  = (idcode >> 28) &    0xf
                        self.logger.info("TAP #%d: IDCODE=%#010x", n, idcode)
                        self.logger.info("manufacturer=%#05x (%s) part=%#06x version=%#03x",
                                         mfg_id, mfg_name, part_id, version)

        if args.operation == "repl":
            await AsyncInteractiveConsole(locals={"jtag_iface":jtag_iface}).interact()

# -------------------------------------------------------------------------------------------------

class JTAGAppletTestCase(GlasgowAppletTestCase, applet=JTAGApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
