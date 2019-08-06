# Ref: IEEE Std 1149.1-2001
# Accession: G00018

# Transport layers
# ----------------
#
# The industry has defined a number of custom JTAG transport layers, such as cJTAG, Spy-Bi-Wire,
# and so on. As long as these comprise a straightforward serialization of the four JTAG signals,
# it is possible to reuse most of this applet by defining a TransportLayerProbeAdapter, with
# the same interface as JTAGProbeAdapter.
#
# Sideband signals
# ----------------
#
# Devices using JTAG for programming and debugging (as opposed to boundary scan) often define
# a number of sideband input or output signals, such as a reset signal or a program success signal.
# The probe driver allows setting or retrieving the state of up to 8 auxiliary signals provided
# by the probe adapter, synchronized to the normal JTAG command stream.
#
# By convention, aux[0:1] are {TRST#.Z, TRST#.O} if the probe adapter provides TRST#.

import struct
import logging
import asyncio
from migen import *
from migen.genlib.cdc import MultiReg

from ....support.bits import *
from ....support.logging import *
from ....support.pyrepl import *
from ....gateware.pads import *
from ....database.jedec import *
from ....arch.jtag import *
from ... import *


class JTAGProbeBus(Module):
    def __init__(self, pads):
        self.tck = Signal(reset=1)
        self.tms = Signal(reset=1)
        self.tdo = Signal(reset=1)
        self.tdi = Signal(reset=1)
        self.trst_z = Signal(reset=0)
        self.trst_o = Signal(reset=0)

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
                pads.trst_t.o.eq(~self.trst_o)
            ]


BIT_AUX_TRST_Z  = 0b01
BIT_AUX_TRST_O  = 0b10


class JTAGProbeAdapter(Module):
    def __init__(self, bus, period_cyc):
        self.stb = Signal()
        self.rdy = Signal()

        self.tms = Signal()
        self.tdo = Signal()
        self.tdi = Signal()
        self.aux_i = C(0)
        self.aux_o = Cat(bus.trst_z, bus.trst_o)

        ###

        half_cyc = int(period_cyc // 2)
        timer    = Signal(max=half_cyc)

        self.submodules.fsm = FSM()
        self.fsm.act("TCK-H",
            bus.tck.eq(1),
            If(timer != 0,
                NextValue(timer, timer - 1)
            ).Else(
                If(self.stb,
                    NextValue(timer, half_cyc - 1),
                    NextValue(bus.tms, self.tms),
                    NextValue(bus.tdi, self.tdi),
                    NextState("TCK-L")
                ).Else(
                    self.rdy.eq(1)
                )
            )
        )
        self.fsm.act("TCK-L",
            bus.tck.eq(0),
            If(timer != 0,
                NextValue(timer, timer - 1)
            ).Else(
                NextValue(timer, half_cyc - 1),
                NextValue(self.tdo, bus.tdo),
                NextState("TCK-H")
            )
        )


CMD_MASK       = 0b11110000
CMD_SHIFT_TMS  = 0b00000000
CMD_SHIFT_TDIO = 0b00010000
CMD_GET_AUX    = 0b10000000
CMD_SET_AUX    = 0b10010000
# CMD_SHIFT_{TMS,TDIO}
BIT_DATA_OUT   =     0b0001
BIT_DATA_IN    =     0b0010
BIT_LAST       =     0b0100
# CMD_SHIFT_TMS
BIT_TDI        =     0b1000


class JTAGProbeDriver(Module):
    def __init__(self, adapter, out_fifo, in_fifo):
        cmd     = Signal(8)
        count   = Signal(16)
        bitno   = Signal(3)
        align   = Signal(3)
        shreg_o = Signal(8)
        shreg_i = Signal(8)

        self.submodules.fsm = FSM()
        self.fsm.act("RECV-COMMAND",
            in_fifo.flush.eq(1),
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(cmd, out_fifo.dout),
                NextState("COMMAND")
            )
        )
        self.fsm.act("COMMAND",
            If(((cmd & CMD_MASK) == CMD_SHIFT_TMS) |
                   ((cmd & CMD_MASK) == CMD_SHIFT_TDIO),
                NextState("RECV-COUNT-1")
            ).Elif((cmd & CMD_MASK) == CMD_GET_AUX,
                NextState("SEND-AUX")
            ).Elif((cmd & CMD_MASK) == CMD_SET_AUX,
                NextState("RECV-AUX")
            )
        )
        self.fsm.act("SEND-AUX",
            If(in_fifo.writable,
                in_fifo.we.eq(1),
                in_fifo.din.eq(adapter.aux_i),
                NextState("RECV-COMMAND")
            )
        )
        self.fsm.act("RECV-AUX",
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(adapter.aux_o, out_fifo.dout),
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
                    NextValue(bitno, 0)
                ).Else(
                    NextValue(align, 8 - count[:3]),
                    NextValue(bitno, 8 - count[:3])
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
            NextValue(adapter.stb, 1),
            If((cmd & CMD_MASK) == CMD_SHIFT_TMS,
                NextValue(adapter.tms, shreg_o[0]),
                NextValue(adapter.tdi, (cmd & BIT_TDI) != 0),
            ).Else(
                NextValue(adapter.tms, 0),
                If(cmd & BIT_LAST,
                    NextValue(adapter.tms, count == 1)
                ),
                NextValue(adapter.tdi, shreg_o[0]),
            ),
            NextValue(shreg_o, Cat(shreg_o[1:], 1)),
            NextValue(count, count - 1),
            NextValue(bitno, bitno + 1),
            NextState("SHIFT-CAPTURE")
        )
        self.fsm.act("SHIFT-CAPTURE",
            NextValue(adapter.stb, 0),
            If(adapter.rdy,
                NextValue(shreg_i, Cat(shreg_i[1:], adapter.tdo)),
                If(bitno == 0,
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


class JTAGProbeSubtarget(Module):
    def __init__(self, pads, out_fifo, in_fifo, period_cyc):
        self.submodules.bus     = JTAGProbeBus(pads)
        self.submodules.adapter = JTAGProbeAdapter(self.bus, period_cyc)
        self.submodules.driver  = JTAGProbeDriver(self.adapter, out_fifo, in_fifo)


class JTAGProbeError(GlasgowAppletError):
    pass


class JTAGProbeStateTransitionError(JTAGProbeError):
    def __init__(self, message, old_state, new_state):
        super().__init__(message.format(old_state, new_state))
        self.old_state = old_state
        self.new_state = new_state


class JTAGProbeInterface:
    def __init__(self, interface, logger, has_trst=False, __name__=__name__):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        self.has_trst    = has_trst
        self._state      = "Unknown"
        self._current_ir = None

    def _log_l(self, message, *args):
        self._logger.log(self._level, "JTAG-L: " + message, *args)

    def _log_h(self, message, *args):
        self._logger.log(self._level, "JTAG-H: " + message, *args)

    # Low-level operations

    async def flush(self):
        self._log_l("flush")
        await self.lower.flush()

    async def set_aux(self, value):
        self._log_l("set aux=%s", format(value, "08b"))
        await self.lower.write(struct.pack("<BB",
            CMD_SET_AUX, value))

    async def get_aux(self):
        await self.lower.write(struct.pack("<B",
            CMD_GET_AUX))
        value, = await self.lower.read(1)
        self._log_l("get aux=%s", format(value, "08b"))
        return value

    async def set_trst(self, active):
        if not self.has_trst:
            raise JTAGProbeError("cannot set TRST#: adapter does not provide TRST#")
        if active is None:
            self._log_l("set trst=z")
            await self.set_aux(BIT_AUX_TRST_Z)
        else:
            self._log_l("set trst=%d", active)
            await self.set_aux(BIT_AUX_TRST_O if active else 0)

    async def shift_tms(self, tms_bits, tdi=False):
        tms_bits = bits(tms_bits)
        self._log_l("shift tms=<%s>", dump_bin(tms_bits))
        await self.lower.write(struct.pack("<BH",
            CMD_SHIFT_TMS|BIT_DATA_OUT|(BIT_TDI if tdi else 0), len(tms_bits)))
        await self.lower.write(tms_bits)

    def _shift_last(self, last):
        if last:
            if self._state == "Shift-IR":
                self._log_l("state Shift-IR → Exit1-IR")
                self._state = "Exit1-IR"
            elif self._state == "Shift-DR":
                self._log_l("state Shift-DR → Exit1-DR")
                self._state = "Exit1-DR"

    @staticmethod
    def _chunk_count(count, last, chunk_size=0xffff):
        while count > chunk_size:
            yield chunk_size, False
            count -= chunk_size
        yield count, last

    @staticmethod
    def _chunk_bits(bits, last, chunk_size=0xffff):
        offset = 0
        while len(bits) - offset > chunk_size:
            yield bits[offset:offset + chunk_size], False
            offset += chunk_size
        yield bits[offset:], last

    async def shift_tdio(self, tdi_bits, last=True):
        assert self._state in ("Shift-IR", "Shift-DR")
        tdi_bits = bits(tdi_bits)
        tdo_bits = bits()
        self._log_l("shift tdio-i=<%s>", dump_bin(tdi_bits))
        for tdi_bits, last in self._chunk_bits(tdi_bits, last):
            await self.lower.write(struct.pack("<BH",
                CMD_SHIFT_TDIO|BIT_DATA_IN|BIT_DATA_OUT|(BIT_LAST if last else 0),
                len(tdi_bits)))
            tdi_bytes = bytes(tdi_bits)
            await self.lower.write(tdi_bytes)
            tdo_bytes = await self.lower.read(len(tdi_bytes))
            tdo_bits += bits(tdo_bytes, len(tdi_bits))
        self._log_l("shift tdio-o=<%s>", dump_bin(tdo_bits))
        self._shift_last(last)
        return tdo_bits

    async def shift_tdi(self, tdi_bits, last=True):
        assert self._state in ("Shift-IR", "Shift-DR")
        tdi_bits = bits(tdi_bits)
        self._log_l("shift tdi=<%s>", dump_bin(tdi_bits))
        for tdi_bits, last in self._chunk_bits(tdi_bits, last):
            await self.lower.write(struct.pack("<BH",
                CMD_SHIFT_TDIO|BIT_DATA_OUT|(BIT_LAST if last else 0),
                len(tdi_bits)))
            tdi_bytes = bytes(tdi_bits)
            await self.lower.write(tdi_bytes)
        self._shift_last(last)

    async def shift_tdo(self, count, last=True):
        assert self._state in ("Shift-IR", "Shift-DR")
        tdo_bits = bits()
        for count, last in self._chunk_count(count, last):
            await self.lower.write(struct.pack("<BH",
                CMD_SHIFT_TDIO|BIT_DATA_IN|(BIT_LAST if last else 0),
                count))
            tdo_bytes = await self.lower.read((count + 7) // 8)
            tdo_bits += bits(tdo_bytes, count)
        self._log_l("shift tdo=<%s>", dump_bin(tdo_bits))
        self._shift_last(last)
        return tdo_bits

    async def shift_dummy(self, count, last=True):
        assert self._state in ("Shift-IR", "Shift-DR")
        self._log_l("shift dummy count=%d", count)
        for count, last in self._chunk_count(count, last):
            await self.lower.write(struct.pack("<BH",
                CMD_SHIFT_TDIO|(BIT_LAST if last else 0), count))
        self._shift_last(last)

    async def pulse_tck(self, count):
        assert self._state in ("Run-Test/Idle", "Pause-IR", "Pause-DR")
        self._log_l("pulse tck count=%d", count)
        for count, last in self._chunk_count(count, last=True):
            await self.lower.write(struct.pack("<BH",
                CMD_SHIFT_TDIO, count))

    # State machine transitions

    def _state_error(self, new_state):
        raise JTAGProbeStateTransitionError("cannot transition from state {} to {}",
                                            self._state, new_state)

    async def enter_test_logic_reset(self, force=True):
        if force:
            self._log_l("state * → Test-Logic-Reset")
        elif self._state != "Test-Logic-Reset":
            self._log_l("state %s → Test-Logic-Reset", self._state)
        else:
            return

        await self.shift_tms((1,1,1,1,1))
        self._state = "Test-Logic-Reset"

    async def enter_run_test_idle(self):
        if self._state == "Run-Test/Idle": return

        self._log_l("state %s → Run-Test/Idle", self._state)
        if self._state == "Test-Logic-Reset":
            await self.shift_tms((0,))
        elif self._state in ("Exit1-IR", "Exit1-DR"):
            await self.shift_tms((1,0))
        elif self._state in ("Pause-IR", "Pause-DR"):
            await self.shift_tms((1,1,0))
        elif self._state in ("Update-IR", "Update-DR"):
            await self.shift_tms((0,))
        else:
            self._state_error("Run-Test/Idle")
        self._state = "Run-Test/Idle"

    async def enter_shift_ir(self):
        if self._state == "Shift-IR": return

        self._log_l("state %s → Shift-IR", self._state)
        if self._state == "Test-Logic-Reset":
            await self.shift_tms((0,1,1,0,0))
        elif self._state in ("Run-Test/Idle", "Update-IR", "Update-DR"):
            await self.shift_tms((1,1,0,0))
        elif self._state in ("Pause-DR"):
            await self.shift_tms((1,1,1,1,0,0))
        elif self._state in ("Pause-IR"):
            await self.shift_tms((1,0))
        else:
            self._state_error("Shift-IR")
        self._state = "Shift-IR"

    async def enter_pause_ir(self):
        if self._state == "Pause-IR": return

        self._log_l("state %s → Pause-IR", self._state)
        if self._state == "Exit1-IR":
            await self.shift_tms((0,))
        else:
            self._state_error("Pause-IR")
        self._state = "Pause-IR"

    async def enter_update_ir(self):
        if self._state == "Update-IR": return

        self._log_l("state %s → Update-IR", self._state)
        if self._state == "Shift-IR":
            await self.shift_tms((1,1))
        elif self._state == "Exit1-IR":
            await self.shift_tms((1,))
        else:
            self._state_error("Update-IR")
        self._state = "Update-IR"

    async def enter_shift_dr(self):
        if self._state == "Shift-DR": return

        self._log_l("state %s → Shift-DR", self._state)
        if self._state == "Test-Logic-Reset":
            await self.shift_tms((0,1,0,0))
        elif self._state in ("Run-Test/Idle", "Update-IR", "Update-DR"):
            await self.shift_tms((1,0,0))
        elif self._state in ("Pause-IR"):
            await self.shift_tms((1,1,1,0,0))
        elif self._state in ("Pause-DR"):
            await self.shift_tms((1,0))
        else:
            self._state_error("Shift-DR")
        self._state = "Shift-DR"

    async def enter_pause_dr(self):
        if self._state == "Pause-DR": return

        self._log_l("state %s → Pause-DR", self._state)
        if self._state == "Exit1-DR":
            await self.shift_tms((0,))
        else:
            self._state_error("Pause-DR")
        self._state = "Pause-DR"

    async def enter_update_dr(self):
        if self._state == "Update-DR": return

        self._log_l("state %s → Update-DR", self._state)
        if self._state == "Shift-DR":
            await self.shift_tms((1,1))
        elif self._state == "Exit1-DR":
            await self.shift_tms((1,))
        else:
            self._state_error("Update-DR")
        self._state = "Update-DR"

    # High-level register manipulation

    async def pulse_trst(self):
        self._log_h("pulse trst")
        await self.set_trst(True)
        # IEEE 1149.1 3.6.1 (d): "To ensure deterministic operation of the test logic, TMS should
        # be held at 1 while the signal applied at TRST* changes from [active] to [inactive]."
        await self.shift_tms((1,))
        await self.set_trst(False)
        self._current_ir = None

    async def test_reset(self):
        self._log_h("test reset")
        await self.enter_test_logic_reset()
        await self.enter_run_test_idle()
        self._current_ir = None

    async def run_test_idle(self, count):
        self._log_h("run-test/idle count=%d", count)
        await self.enter_run_test_idle()
        await self.pulse_tck(count)

    async def exchange_ir(self, data):
        self._current_ir = data = bits(data)
        self._log_h("exchange ir")
        await self.enter_shift_ir()
        data = await self.shift_tdio(data)
        await self.enter_update_ir()
        return data

    async def read_ir(self, count):
        self._current_ir = bits((1,)) * count
        await self.enter_shift_ir()
        data = await self.shift_tdo(count)
        await self.enter_update_ir()
        self._log_h("read ir=<%s>", dump_bin(data))
        return data

    async def write_ir(self, data, *, elide=True):
        if data == self._current_ir and elide:
            self._log_h("write ir (elided)")
            return
        self._current_ir = data = bits(data)
        self._log_h("write ir=<%s>", dump_bin(data))
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
            self._log_h("read idempotent dr=<%s>", dump_bin(data))
        else:
            self._log_h("read dr=<%s>", dump_bin(data))
        return data

    async def write_dr(self, data):
        data = bits(data)
        self._log_h("write dr=<%s>", dump_bin(data))
        await self.enter_shift_dr()
        await self.shift_tdi(data)
        await self.enter_update_dr()

    # Specialized operations

    async def _scan_xr(self, xr, max_length, zero_ok=False):
        assert xr in ("ir", "dr")
        self._log_h("scan %s length", xr)

        if xr ==  "ir":
            await self.enter_shift_ir()
        if xr ==  "dr":
            await self.enter_shift_dr()

        try:
            data_1 = await self.shift_tdio((1,) * max_length, last=False)
            data_0 = await self.shift_tdio((0,) * max_length, last=False)
            for length in range(max_length):
                if data_0[length] == 0:
                    self._log_h("scan %s length=%d data=<%s>",
                                xr, length, dump_bin(data_1[:length]))
                    return data_1[:length]
            else:
                self._log_h("overlong %s", xr)
                return

        finally:
            if xr == "ir":
                # Fill the register with BYPASS instructions.
                await self.shift_tdi((1,) * length, last=True)
            if xr == "dr":
                # Restore the old contents, just in case this matters.
                await self.shift_tdi(data_1[:length], last=True)

            await self.enter_run_test_idle()

    async def scan_ir(self, max_length):
        return await self._scan_xr("ir", max_length)

    async def scan_dr(self, max_length):
        return await self._scan_xr("dr", max_length)

    async def scan_ir_length(self, max_length):
        data = await self.scan_ir(max_length)
        if data is None: return
        return len(data)

    async def scan_dr_length(self, max_length, zero_ok=False):
        data = await self.scan_dr(max_length)
        if data is None: return
        length = len(data)
        assert zero_ok or length > 0
        return length

    def segment_idcodes(self, dr_value):
        idcodes = []
        index = 0
        while index < len(dr_value):
            if dr_value[index]:
                if len(dr_value) - index >= 32:
                    idcode = int(dr_value[index:index + 32])
                    self._log_h("found idcode=<%08x>", idcode)
                    idcodes.append(idcode)
                    index += 32
                else:
                    self._log_h("found truncated idcode=<%s>", dump_bin(dr_value[index:]))
                    return
            else:
                self._log_h("found bypass")
                idcodes.append(None)
                index += 1

        return idcodes

    def segment_irs(self, ir_value, count=None):
        if ir_value[0:2] != (1,0):
            self._log_h("ir does not start with 10")
            return

        irs = []
        ir_offset = 0
        if count == 1:
            # 1 TAP case; the entire IR belongs to the only TAP we have.
            ir_length = len(ir_value)
            self._log_h("found ir[%d] (1-tap)", ir_length)
            irs.append((ir_offset, ir_length))
        else:
            # >1 TAP case; there is no way to segment IR without knowledge of specific devices
            # involved.
            self._log_h("found more than 1 tap")
            return

        if count is not None and len(irs) != count:
            self._log_h("ir count does not match idcode count")
            return

        return irs

    async def select_tap(self, tap, max_ir_length=128, max_dr_length=1024):
        await self.test_reset()

        dr_value = await self.scan_dr(max_dr_length)
        if dr_value is None:
            return

        idcodes = self.segment_idcodes(dr_value)
        if idcodes is None:
            return

        ir_value = await self.scan_ir(max_ir_length)
        if ir_value is None:
            return

        irs = self.segment_irs(ir_value, count=len(idcodes))
        if not irs:
            return

        if tap >= len(irs):
            self._log_h("tap %d not present on chain")
            return

        ir_offset, ir_length = irs[tap]
        total_ir_length = sum(length for offset, length in irs)

        dr_offset, dr_length = tap, 1
        total_dr_length = len(idcodes)

        bypass = bits((1,))
        def affix(offset, length, total_length):
            prefix = bypass * offset
            suffix = bypass * (total_length - offset - length)
            return prefix, suffix

        return TAPInterface(self, ir_length,
            *affix(ir_offset, ir_length, total_ir_length),
            *affix(dr_offset, dr_length, total_dr_length))


class TAPInterface:
    def __init__(self, lower, ir_length, ir_prefix, ir_suffix, dr_prefix, dr_suffix):
        self.lower = lower
        self.ir_length    = ir_length
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

    async def exchange_ir(self, data):
        data = bits(data)
        assert len(data) == self.ir_length
        data = await self.lower.exchange_ir(self._ir_prefix + data + self._ir_suffix)
        if self._ir_suffix:
            return data[len(self._ir_prefix):-len(self._ir_suffix)]
        else:
            return data[len(self._ir_prefix):]

    async def read_ir(self):
        data = await self.lower.read_ir(self._ir_overhead + self.ir_length)
        if self._ir_suffix:
            return data[len(self._ir_prefix):-len(self._ir_suffix)]
        else:
            return data[len(self._ir_prefix):]

    async def write_ir(self, data, *, elide=True):
        data = bits(data)
        assert len(data) == self.ir_length
        await self.lower.write_ir(self._ir_prefix + data + self._ir_suffix, elide=elide)

    async def exchange_dr(self, data):
        data = bits(data)
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
        data = bits(data)
        await self.lower.write_dr(self._dr_prefix + data + self._dr_suffix)

    async def scan_dr_length(self, max_length, zero_ok=False):
        length = await self.lower.scan_dr_length(max_length=self._dr_overhead + max_length,
                                                 zero_ok=zero_ok)
        if length is None or length == 0:
            return
        assert length >= self._dr_overhead
        assert zero_ok or length - self._dr_overhead > 0
        return length - self._dr_overhead


class JTAGProbeApplet(GlasgowApplet, name="jtag-probe"):
    logger = logging.getLogger(__name__)
    help = "test integrated circuits via IEEE 1149.1 JTAG"
    description = """
    Identify, test and debug integrated circuits and board assemblies via IEEE 1149.1 JTAG.
    """
    has_custom_repl = True

    __pins = ("tck", "tms", "tdi", "tdo", "trst")

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        for pin in ("tck", "tms", "tdi", "tdo"):
            access.add_pin_argument(parser, pin, default=True)
        access.add_pin_argument(parser, "trst")

        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=100,
            help="set clock frequency to FREQ kHz (default: %(default)s)")

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        iface.add_subtarget(JTAGProbeSubtarget(
            pads=iface.get_pads(args, pins=self.__pins),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(auto_flush=False),
            period_cyc=target.sys_clk_freq // (args.frequency * 1000),
        ))

    async def run(self, device, args, reset=False):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        jtag_iface = JTAGProbeInterface(iface, self.logger, has_trst=args.pin_trst is not None)
        if reset:
            if jtag_iface.has_trst:
                await jtag_iface.pulse_trst()
            else:
                await jtag_iface.test_reset()
        return jtag_iface

    @classmethod
    def add_run_tap_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)

        parser.add_argument(
            "--tap-index", metavar="INDEX", type=int, default=0,
            help="select TAP #INDEX for communication (default: %(default)s)")

    async def run_tap(self, cls, device, args):
        jtag_iface = await self.run_lower(cls, device, args)
        tap_iface = await jtag_iface.select_tap(args.tap_index)
        if not tap_iface:
            raise JTAGProbeError("cannot select TAP #%d" % args.tap_index)
        return tap_iface

    @classmethod
    def add_interact_arguments(cls, parser):
        parser.add_argument(
            "--max-ir-length", metavar="LENGTH", type=int, default=128,
            help="give up scanning IR after LENGTH bits")
        parser.add_argument(
            "--max-dr-length", metavar="LENGTH", type=int, default=1024,
            help="give up scanning DR after LENGTH bits")

        # TODO(py3.7): add required=True
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
            "tap_indexes", metavar="INDEX", type=int, nargs="+",
            help="enumerate IR values for TAP #INDEX")

        # This one is identical to run-repl, and is just for consistency when using the subcommands
        # tap-repl and jtag-repl alternately.
        p_jtag_repl = p_operation.add_parser(
            "jtag-repl", help="drop into Python REPL")

        p_tap_repl = p_operation.add_parser(
            "tap-repl", help="select a TAP and drop into Python REPL")
        p_tap_repl.add_argument(
            "tap_index", metavar="INDEX", type=int, default=0, nargs="?",
            help="select TAP #INDEX for communication (default: %(default)s)")

    async def interact(self, device, args, jtag_iface):
        if args.operation in ("scan", "enumerate-ir"):
            await jtag_iface.test_reset()

            dr_value = await jtag_iface.scan_dr(max_length=args.max_dr_length)
            if dr_value is None:
                self.logger.warning("DR length scan did not terminate")
                return
            self.logger.info("shifted %d-bit DR=<%s>", len(dr_value), dump_bin(dr_value))

            ir_value = await jtag_iface.scan_ir(max_length=args.max_ir_length)
            if ir_value is None:
                self.logger.warning("IR length scan did not terminate")
                return
            self.logger.info("shifted %d-bit IR=<%s>", len(ir_value), dump_bin(ir_value))

            idcodes = jtag_iface.segment_idcodes(dr_value)
            if not idcodes:
                self.logger.warning("DR segmentation discovered no devices")
                return
            self.logger.info("DR segmentation discovered %d devices", len(idcodes))

            irs = jtag_iface.segment_irs(ir_value, count=len(idcodes))

        if args.operation == "scan":
            if not irs:
                self.logger.warning("automatic IR segmentation failed")
                irs = [(None, "?") for _ in idcodes]

            for tap_index, (idcode_value, (ir_offset, ir_length)) in enumerate(zip(idcodes, irs)):
                if idcode_value is None:
                    self.logger.info("TAP #%d: IR[%s] BYPASS",
                                     tap_index, ir_length)
                else:
                    idcode   = DR_IDCODE.from_int(idcode_value)
                    mfg_name = jedec_mfg_name_from_bank_num(idcode.mfg_id >> 7,
                                                            idcode.mfg_id & 0x7f) or \
                                    "unknown"
                    self.logger.info("TAP #%d: IR[%s] IDCODE=%#010x",
                                     tap_index, ir_length, idcode_value)
                    self.logger.info("manufacturer=%#05x (%s) part=%#06x version=%#03x",
                                     idcode.mfg_id, mfg_name, idcode.part_id, idcode.version)

        if args.operation == "enumerate-ir":
            if not irs:
                self.logger.error("automatic IR segmentation failed")
                return

            for tap_index in args.tap_indexes or range(len(irs)):
                ir_offset, ir_length = irs[tap_index]
                self.logger.info("TAP #%d: IR[%d]", tap_index, ir_length)

                tap_iface = await jtag_iface.select_tap(tap_index,
                                                        args.max_ir_length, args.max_dr_length)
                if not tap_iface:
                    raise GlasgowAppletError("cannot select TAP #%d" % tap_index)

                for ir_value in range(0, (1 << ir_length)):
                    ir_value = bits(ir_value & (1 << bit) for bit in range(ir_length))
                    await tap_iface.test_reset()
                    await tap_iface.write_ir(ir_value)
                    dr_length = await tap_iface.scan_dr_length(max_length=args.max_dr_length,
                                                               zero_ok=True)
                    if dr_length is None:
                        level = logging.ERROR
                        dr_length = "?"
                    elif dr_length == 0:
                        level = logging.WARN
                    elif dr_length == 1:
                        level = logging.DEBUG
                    else:
                        level = logging.INFO
                    self.logger.log(level, "  IR=%s DR[%s]", ir_value, dr_length)

        if args.operation == "jtag-repl":
            await AsyncInteractiveConsole(locals={"iface":jtag_iface}).interact()

        if args.operation == "tap-repl":
            tap_iface = await jtag_iface.select_tap(args.tap_index,
                                                    args.max_ir_length, args.max_dr_length)
            if not tap_iface:
                self.logger.error("cannot select TAP #%d" % args.tap_index)
                return

            await AsyncInteractiveConsole(locals={"iface":tap_iface}).interact()

# -------------------------------------------------------------------------------------------------

class JTAGProbeAppletTestCase(GlasgowAppletTestCase, applet=JTAGProbeApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
