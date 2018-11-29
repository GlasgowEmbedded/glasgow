import struct
import logging
import asyncio
from bitarray import bitarray
from migen import *
from migen.genlib.cdc import MultiReg
from migen.genlib.fsm import FSM

from .. import *
from ...support.pyrepl import *
from ...gateware.pads import *
from ...database.jedec import *
from ...arch.jtag import *


class JTAGBus(Module):
    def __init__(self, pads):
        self.tck = Signal(reset=1)
        self.tms = Signal(reset=1)
        self.tdo = Signal(reset=1)
        self.tdi = Signal(reset=1)
        self.trst_z = Signal(reset=0)
        self.trst   = Signal(reset=1)

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
                pads.trst_t.oe.eq(~self.trst_z),
                pads.trst_t.o.eq(~self.trst)
            ]


CMD_MASK       = 0b11110000
CMD_RESET      = 0b00000000
CMD_TRST       = 0b00010000
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
                NextValue(bus.trst_z, 0),
                NextValue(bus.trst,   1),
                NextState("TEST-RESET")
            ).Elif((cmd & CMD_MASK) == CMD_TRST,
                NextValue(bus.trst_z, cmd[0]),
                NextValue(bus.trst,   cmd[1]),
                NextState("RECV-COMMAND")
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
                # IEEE 1149.1 3.6.1 (d): "To ensure deterministic operation of the test logic,
                # TMS should be held at 1 while the signal applied at TRST* changes from 0 to 1."
                NextValue(bus.tms,  1),
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

        self._state      = "Unknown"
        self._current_ir = None

    def _log_l(self, message, *args):
        self._logger.log(self._level, "JTAG-L: " + message, *args)

    def _log_h(self, message, *args):
        self._logger.log(self._level, "JTAG-H: " + message, *args)

    # Low-level operations

    async def set_trst(self, state):
        if state is None:
            self._log_l("set trst=z")
            await self.lower.write(struct.pack("<B",
                CMD_TRST|0b01))
        else:
            state = state & 1
            self._log_l("set trst=%d", state)
            await self.lower.write(struct.pack("<B",
                CMD_TRST|(state << 1)))

    async def pulse_trst(self):
        self._log_l("pulse trst")
        await self.lower.write(struct.pack("<B",
            CMD_RESET))
        self._current_ir = None

    async def shift_tms(self, tms_bits):
        tms_bits = bitarray(tms_bits, endian="little")
        self._log_l("shift tms=<%s>", tms_bits.to01())
        await self.lower.write(struct.pack("<BH",
            CMD_SHIFT_TMS|BIT_DATA_OUT, len(tms_bits)))
        await self.lower.write(tms_bits.tobytes())

    def _shift_last(self, last):
        if last:
            if self._state == "Shift-IR":
                self._log_l("state Shift-IR → Exit1-IR")
                self._state = "Exit1-IR"
            elif self._state == "Shift-DR":
                self._log_l("state Shift-DR → Exit1-DR")
                self._state = "Exit1-DR"

    async def shift_tdio(self, tdi_bits, last=True):
        assert self._state in ("Shift-IR", "Shift-DR")
        tdi_bits = bitarray(tdi_bits, endian="little")
        tdo_bits = bitarray(endian="little")
        self._log_l("shift tdio-i=<%s>", tdi_bits.to01())
        await self.lower.write(struct.pack("<BH",
            CMD_SHIFT_TDIO|BIT_DATA_IN|BIT_DATA_OUT|(BIT_LAST if last else 0),
            len(tdi_bits)))
        tdi_bytes = tdi_bits.tobytes()
        await self.lower.write(tdi_bytes)
        tdo_bytes = await self.lower.read(len(tdi_bytes))
        tdo_bits.frombytes(bytes(tdo_bytes))
        while len(tdo_bits) > len(tdi_bits): tdo_bits.pop()
        self._log_l("shift tdio-o=<%s>", tdo_bits.to01())
        self._shift_last(last)
        return tdo_bits

    async def shift_tdi(self, tdi_bits, last=True):
        assert self._state in ("Shift-IR", "Shift-DR")
        tdi_bits = bitarray(tdi_bits, endian="little")
        self._log_l("shift tdi=<%s>", tdi_bits.to01())
        await self.lower.write(struct.pack("<BH",
            CMD_SHIFT_TDIO|BIT_DATA_OUT|(BIT_LAST if last else 0),
            len(tdi_bits)))
        tdi_bytes = tdi_bits.tobytes()
        await self.lower.write(tdi_bytes)
        self._shift_last(last)

    async def shift_tdo(self, count, last=True):
        assert self._state in ("Shift-IR", "Shift-DR")
        tdo_bits = bitarray(endian="little")
        await self.lower.write(struct.pack("<BH",
            CMD_SHIFT_TDIO|BIT_DATA_IN|(BIT_LAST if last else 0),
            count))
        tdo_bytes = await self.lower.read((count + 7) // 8)
        tdo_bits.frombytes(bytes(tdo_bytes))
        while len(tdo_bits) > count: tdo_bits.pop()
        self._log_l("shift tdo=<%s>", tdo_bits.to01())
        self._shift_last(last)
        return tdo_bits

    async def pulse_tck(self, count):
        assert self._state in ("Run-Test/Idle", "Shift-IR", "Shift-DR", "Pause-IR", "Pause-DR")
        self._log_l("pulse tck count=%d", count)
        while count > 0xffff:
            await self.lower.write(struct.pack("<BH",
                CMD_SHIFT_TDIO, 0xffff))
            count -= 0xffff
        await self.lower.write(struct.pack("<BH",
            CMD_SHIFT_TDIO, count))

    # State machine transitions

    async def enter_test_logic_reset(self, force=True):
        if force:
            self._log_l("state * → Test-Logic-Reset")
        elif self._state != "Test-Logic-Reset":
            self._log_l("state %s → Test-Logic-Reset", self._state)
        else:
            return

        await self.shift_tms("11111")
        self._state = "Test-Logic-Reset"

    async def enter_run_test_idle(self):
        if self._state == "Run-Test/Idle": return

        self._log_l("state %s → Run-Test/Idle", self._state)
        if self._state == "Test-Logic-Reset":
            await self.shift_tms("0")
        elif self._state in ("Exit1-IR", "Exit1-DR"):
            await self.shift_tms("10")
        elif self._state in ("Pause-IR", "Pause-DR"):
            await self.shift_tms("110")
        elif self._state in ("Update-IR", "Update-DR"):
            await self.shift_tms("0")
        else:
            assert False
        self._state = "Run-Test/Idle"

    async def enter_shift_ir(self):
        if self._state == "Shift-IR": return

        self._log_l("state %s → Shift-IR", self._state)
        if self._state == "Test-Logic-Reset":
            await self.shift_tms("01100")
        elif self._state in ("Run-Test/Idle", "Update-IR", "Update-DR"):
            await self.shift_tms("1100")
        else:
            assert False
        self._state = "Shift-IR"

    async def enter_pause_ir(self):
        if self._state == "Pause-IR": return

        self._log_l("state %s → Pause-IR", self._state)
        if self._state == "Exit1-IR":
            await self.shift_tms("0")
        else:
            assert False
        self._state = "Pause-IR"

    async def enter_update_ir(self):
        if self._state == "Update-IR": return

        self._log_l("state %s → Update-IR", self._state)
        if self._state == "Shift-IR":
            await self.shift_tms("11")
        elif self._state == "Exit1-IR":
            await self.shift_tms("1")
        else:
            assert False
        self._state = "Update-IR"

    async def enter_shift_dr(self):
        if self._state == "Shift-DR": return

        self._log_l("state %s → Shift-DR", self._state)
        if self._state == "Test-Logic-Reset":
            await self.shift_tms("0100")
        elif self._state in ("Run-Test/Idle", "Update-IR", "Update-DR"):
            await self.shift_tms("100")
        else:
            assert False
        self._state = "Shift-DR"

    async def enter_pause_dr(self):
        if self._state == "Pause-DR": return

        self._log_l("state %s → Pause-DR", self._state)
        if self._state == "Exit1-DR":
            await self.shift_tms("0")
        else:
            assert False
        self._state = "Pause-DR"

    async def enter_update_dr(self):
        if self._state == "Update-DR": return

        self._log_l("state %s → Update-DR", self._state)
        if self._state == "Shift-DR":
            await self.shift_tms("11")
        elif self._state == "Exit1-DR":
            await self.shift_tms("1")
        else:
            assert False
        self._state = "Update-DR"

    # High-level register manipulation

    async def test_reset(self):
        self._log_h("test reset")
        await self.enter_test_logic_reset()
        await self.enter_run_test_idle()
        self._current_ir = None

    async def run_test_idle(self, count):
        self._log_h("run-test/idle count=%d", count)
        await self.enter_run_test_idle()
        await self.pulse_tck(count)

    async def write_ir(self, data):
        if data == self._current_ir:
            self._log_h("write ir (elided)")
            return
        else:
            self._current_ir = bitarray(data, endian="little")

        self._log_h("write ir=<%s>", data.to01())
        await self.enter_shift_ir()
        await self.shift_tdi(data)
        await self.enter_update_ir()

    async def exchange_dr(self, data):
        self._log_h("exchange dr")
        await self.enter_shift_dr()
        data = await self.shift_tdio(data)
        await self.enter_update_dr()
        return data

    async def read_dr(self, count, idempotent=False):
        await self.enter_shift_dr()
        data = await self.shift_tdo(count, last=not idempotent)
        if idempotent:
            # Shift what we just read back in. This is useful to avoid disturbing any bits
            # in R/W DRs when we go through Update-DR.
            await self.shift_tdi(data)
        await self.enter_update_dr()
        if idempotent:
            self._log_h("read idempotent dr=<%s>", data.to01())
        else:
            self._log_h("read dr=<%s>", data.to01())
        return data

    async def write_dr(self, data):
        self._log_h("write dr=<%s>", data.to01())
        await self.enter_shift_dr()
        await self.shift_tdi(data)
        await self.enter_update_dr()

    # Specialized operations

    async def scan_idcode(self, max_idcodes=8):
        await self.test_reset()

        self._log_h("scan idcode")
        await self.enter_shift_dr()

        try:
            idcodes = []
            idcode_bits = bitarray()
            while len(idcodes) < max_idcodes:
                while len(idcodes) < max_idcodes:
                    first_bit = await self.shift_tdo(1, last=False)
                    if first_bit[0]:
                        break # IDCODE
                    else:
                        self._log_h("found bypass")
                        idcodes.append(None)
                        pass  # BYPASS
                else:
                    self._log_h("too many idcodes")
                    return

                idcode_bits = first_bit + await self.shift_tdo(31, last=False)
                idcode, = struct.unpack("<L", idcode_bits.tobytes())
                if idcode == 0xffffffff:
                    break
                self._log_h("found idcode=<%08x>", idcode)
                idcodes.append(idcode)

            return idcodes
        finally:
            await self.shift_tdo(1, last=True)
            await self.enter_run_test_idle()

    async def scan_ir(self, count=None, max_length=128):
        await self.test_reset()

        self._log_h("scan ir")
        await self.enter_shift_ir()

        try:
            ir_0, = await self.shift_tdo(1, last=False)
            if not ir_0:
                self._log_h("invalid ir[0]")
                return

            irs = []
            ir_offset = 0
            while count is None or len(irs) < count:
                ir_1, = await self.shift_tdo(1, last=False)
                if ir_1:
                    break

                ir_length = 2
                while ir_length < max_length:
                    ir_n, = await self.shift_tdo(1, last=False)
                    if ir_n:
                        break
                    ir_length += 1
                else:
                    self._log_h("overlong ir")
                    return

                self._log_h("found ir[%d]", ir_length)
                irs.append((ir_offset, ir_length))
                ir_offset += ir_length

            if count is not None and len(irs) != count:
                self._log_h("ir count does not match idcode count")
                return

            return irs
        finally:
            await self.shift_tdo(1, last=True)
            await self.enter_run_test_idle()

    async def scan_dr_length(self, max_length, zero_ok=False):
        self._log_h("scan dr length")

        try:
            await self.enter_shift_dr()

            # Fill the entire DR chain with ones.
            data = await self.shift_tdio(bitarray("1") * max_length, last=False)

            length = 0
            while length < max_length:
                out = await self.shift_tdio(bitarray("0"), last=False)
                if out[0] == 0:
                    break
                length += 1
            else:
                self._log_h("overlong dr")
                return

            # Restore the old contents, just in case this matters.
            await self.shift_tdi(data[:length], last=True)

            if not zero_ok:
                assert length > 0
            self._log_h("scan dr length=%d", length)
            return length

        finally:
            await self.enter_run_test_idle()

    async def select_tap(self, tap):
        idcodes = await self.scan_idcode()
        if not idcodes:
            return

        irs = await self.scan_ir(count=len(idcodes))
        if not irs:
            return

        if tap >= len(irs):
            self._log_h("tap %d not present on chain")
            return

        ir_offset, ir_length = irs[tap]
        total_ir_length = sum(length for offset, length in irs)

        dr_offset, dr_length = tap, 1
        total_dr_length = len(idcodes)

        bypass = bitarray("1", endian="little")
        def affix(offset, length, total_length):
            prefix = bypass * offset
            suffix = bypass * (total_length - offset - length)
            return prefix, suffix

        return TAPInterface(self,
            *affix(ir_offset, ir_length, total_ir_length),
            *affix(dr_offset, dr_length, total_dr_length))


class TAPInterface:
    def __init__(self, lower, ir_prefix, ir_suffix, dr_prefix, dr_suffix):
        self.lower = lower
        self._ir_prefix   = ir_prefix
        self._ir_suffix   = ir_suffix
        self._ir_overhead = len(ir_prefix) + len(ir_suffix)
        self._dr_prefix   = dr_prefix
        self._dr_suffix   = dr_suffix
        self._dr_overhead = len(dr_prefix) + len(dr_suffix)

    async def test_reset(self):
        await self.lower.test_reset()

    async def run_test_idle(self, count):
        await self.lower.run_test_idle(count)

    async def write_ir(self, data):
        data = bitarray(data, endian="little")
        await self.lower.write_ir(self._ir_prefix + data + self._ir_suffix)

    async def exchange_dr(self, data):
        data = bitarray(data, endian="little")
        data = await self.lower.exchange_dr(self._dr_prefix + data + self._dr_suffix)
        if self._dr_suffix:
            return data[len(self._dr_prefix):-len(self._dr_suffix)]
        else:
            return data[len(self._dr_prefix):]

    async def read_dr(self, count, idempotent=False):
        data = await self.lower.read_dr(self._dr_overhead + count, idempotent=idempotent)
        if self._dr_suffix:
            return data[len(self._dr_prefix):-len(self._dr_suffix)]
        else:
            return data[len(self._dr_prefix):]

    async def write_dr(self, data):
        data = bitarray(data, endian="little")
        await self.lower.write_dr(self._dr_prefix + data + self._dr_suffix)

    async def scan_dr_length(self, max_length, zero_ok=False):
        length = await self.lower.scan_dr_length(max_length=self._dr_overhead + max_length,
                                                 zero_ok=zero_ok)
        if length is None:
            return
        assert length >= self._dr_overhead
        return length - self._dr_overhead


class JTAGApplet(GlasgowApplet, name="jtag"):
    logger = logging.getLogger(__name__)
    help = "test integrated circuits via IEEE 1149.1 JTAG"
    description = """
    Identify, test and debug integrated circuits and board assemblies via IEEE 1149.1 JTAG.
    """

    __pins = ("tck", "tms", "tdi", "tdo", "trst")

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        for pin in ("tck", "tms", "tdi", "tdo"):
            access.add_pin_argument(parser, pin, default=True)
        access.add_pin_argument(parser, "trst")

        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=100,
            help="set clock period to FREQ kHz (default: %(default)s)")

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        iface.add_subtarget(JTAGSubtarget(
            pads=iface.get_pads(args, pins=self.__pins),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(),
            period_cyc=target.sys_clk_freq // (args.frequency * 1000),
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

        p_enumerate_ir = p_operation.add_parser(
            "enumerate-ir", help="use heuristics to enumerate JTAG IR values (DANGEROUS)",
            description="""
            THIS COMMAND CAN HAVE POTENTIALLY DESTRUCTIVE CONSEQUENCES.

            IEEE 1149.1 requires that any unimplemented IR value select the BYPASS DR.
            By exploiting this, and measuring DR lengths for every possible IR value,
            we can discover DR lengths for every IR value.

            Note that discovering DR length requires going through Capture-DR and Update-DR
            states. While we strive to be as unobtrustive as possible by shifting the original
            DR value back after we discover DR length, there is no guarantee that updating DR
            with the captured DR value is side effect free. As such, this command can potentially
            have UNPREDICTABLE side effects that, due to the nature of JTAG, can permanently
            damage your target. Use with care.

            Note that while unimplemented IR values are required to select the BYPASS DR,
            in practice, many apparently (from the documentation) unimplemented IR values
            would actually select reserved DRs instead, which can lead to confusion. In some
            cases they even select a constant 0 level on TDO!
            """)
        p_enumerate_ir.add_argument(
            "--max-dr-length", metavar="LENGTH", type=int, default=1024,
            help="give up scanning DR after LENGTH bits")
        p_enumerate_ir.add_argument(
            "tap_indexes", metavar="INDEX", type=int, nargs="+",
            help="enumerate IR values for TAP #INDEX")

        p_jtag_repl = p_operation.add_parser(
            "jtag-repl", help="drop into Python shell; use `jtag_iface` to communicate")

        p_tap_repl = p_operation.add_parser(
            "tap-repl", help="drop into Python shell; use `tap_iface` to communicate")
        p_tap_repl.add_argument(
            "tap_index", metavar="INDEX", type=int, default=0, nargs="?",
            help="select TAP #INDEX for communication (default: %(default)s)")

    async def interact(self, device, args, jtag_iface):
        await jtag_iface.pulse_trst()

        if args.operation in ("scan", "enumerate-ir"):
            idcodes = await jtag_iface.scan_idcode()
            if not idcodes:
                self.logger.warning("DR scan discovered no devices")
                return

            irs = await jtag_iface.scan_ir(count=len(idcodes))
            if not irs:
                self.logger.warning("IR scan does not match DR scan")
                return

        if args.operation == "scan":
            for tap_index, (idcode_value, (ir_offset, ir_length)) in enumerate(zip(idcodes, irs)):
                if idcode_value is None:
                    self.logger.info("TAP #%d: IR[%d] BYPASS",
                                     tap_index, ir_length)
                else:
                    idcode   = DR_IDCODE.from_int(idcode_value)
                    mfg_name = jedec_mfg_name_from_bank_num(idcode.mfg_id >> 7,
                                                            idcode.mfg_id & 0x7f) or \
                                    "unknown"
                    self.logger.info("TAP #%d: IR[%d] IDCODE=%#010x",
                                     tap_index, ir_length, idcode_value)
                    self.logger.info("manufacturer=%#05x (%s) part=%#06x version=%#03x",
                                     idcode.mfg_id, mfg_name, idcode.part_id, idcode.version)

        if args.operation == "enumerate-ir":
            for tap_index in args.tap_indexes or range(len(irs)):
                ir_offset, ir_length = irs[tap_index]
                self.logger.info("TAP #%d: IR[%d]", tap_index, ir_length)

                tap_iface = await jtag_iface.select_tap(tap_index)
                for ir_value in range(0, (1 << ir_length)):
                    await tap_iface.test_reset()
                    await tap_iface.write_ir([ir_value & (1 << bit) for bit in range(ir_length)])
                    dr_length = await tap_iface.scan_dr_length(max_length=args.max_dr_length,
                                                               zero_ok=True)
                    if dr_length == 0:
                        level = logging.WARN
                    elif dr_length == 1:
                        level = logging.DEBUG
                    else:
                        level = logging.INFO
                    self.logger.log(level, "  IR=%s DR[%d]",
                                    "{:0{}b}".format(ir_value, ir_length), dr_length)

        if args.operation == "jtag-repl":
            await AsyncInteractiveConsole(locals={"jtag_iface":jtag_iface}).interact()

        if args.operation == "tap-repl":
            tap_iface = await jtag_iface.select_tap(args.tap_index)
            if not tap_iface:
                self.logger.error("cannot select TAP #%d" % args.tap_index)
                return

            await AsyncInteractiveConsole(locals={"tap_iface":tap_iface}).interact()

# -------------------------------------------------------------------------------------------------

class JTAGAppletTestCase(GlasgowAppletTestCase, applet=JTAGApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
