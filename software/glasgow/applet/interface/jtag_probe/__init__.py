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
from nmigen import *
from nmigen.lib.cdc import FFSynchronizer

from ....support.bits import *
from ....support.logging import *
from ....support.pyrepl import *
from ....gateware.pads import *
from ....database.jedec import *
from ....arch.jtag import *
from ... import *


class JTAGProbeBus(Elaboratable):
    def __init__(self, pads):
        self._pads = pads
        self.tck = Signal(reset=1)
        self.tms = Signal(reset=1)
        self.tdo = Signal(reset=1)
        self.tdi = Signal(reset=1)
        self.trst_z = Signal(reset=0)
        self.trst_o = Signal(reset=0)

    def elaborate(self, platform):
        m = Module()
        pads = self._pads
        m.d.comb += [
            pads.tck_t.oe.eq(1),
            pads.tck_t.o.eq(self.tck),
            pads.tms_t.oe.eq(1),
            pads.tms_t.o.eq(self.tms),
            pads.tdi_t.oe.eq(1),
            pads.tdi_t.o.eq(self.tdi),
        ]
        m.submodules += [
            FFSynchronizer(pads.tdo_t.i, self.tdo),
        ]
        if hasattr(pads, "trst_t"):
            m.d.sync += [
                pads.trst_t.oe.eq(~self.trst_z),
                pads.trst_t.o.eq(~self.trst_o)
            ]
        return m


BIT_AUX_TRST_Z  = 0b01
BIT_AUX_TRST_O  = 0b10


class JTAGProbeAdapter(Elaboratable):
    def __init__(self, bus, period_cyc):
        self.bus = bus
        self._period_cyc = period_cyc

        self.stb = Signal()
        self.rdy = Signal()

        self.tms = Signal()
        self.tdo = Signal()
        self.tdi = Signal()
        self.aux_i = C(0)
        self.aux_o = Cat(bus.trst_z, bus.trst_o)

    def elaborate(self, platform):
        m = Module()
        half_cyc = int(self._period_cyc // 2)
        timer    = Signal(range(half_cyc+1))

        with m.FSM() as fsm:
            with m.State("TCK-H"):
                m.d.comb += self.bus.tck.eq(1)
                with m.If(timer != 0):
                    m.d.sync += timer.eq(timer - 1)
                with m.Else():
                    with m.If(self.stb):
                        m.d.sync += [
                            timer   .eq(half_cyc - 1),
                            self.bus.tms .eq(self.tms),
                            self.bus.tdi .eq(self.tdi),
                        ]
                        m.next = "TCK-L"
                    with m.Else():
                        m.d.comb += self.rdy.eq(1)
            with m.State("TCK-L"):
                m.d.comb += self.bus.tck.eq(0)
                with m.If(timer != 0):
                    m.d.sync += timer.eq(timer - 1)
                with m.Else():
                    m.d.sync += [
                        timer   .eq(half_cyc - 1),
                        self.tdo.eq(self.bus.tdo),
                    ]
                    m.next = "TCK-H"
        return m


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


class JTAGProbeDriver(Elaboratable):
    def __init__(self, adapter, out_fifo, in_fifo):
        self.adapter = adapter
        self._out_fifo = out_fifo
        self._in_fifo = in_fifo

    def elaborate(self, platform):
        m = Module()
        cmd     = Signal(8)
        count   = Signal(16)
        bitno   = Signal(3)
        align   = Signal(3)
        shreg_o = Signal(8)
        shreg_i = Signal(8)

        with m.FSM() as fsm:
            with m.State("RECV-COMMAND"):
                m.d.comb += self._in_fifo.flush.eq(1)
                with m.If(self._out_fifo.readable):
                    m.d.comb += self._out_fifo.re.eq(1)
                    m.d.sync += cmd.eq(self._out_fifo.dout)
                    m.next = "COMMAND"

            with m.State("COMMAND"):
                with m.If(((cmd & CMD_MASK) == CMD_SHIFT_TMS) |
                    ((cmd & CMD_MASK) == CMD_SHIFT_TDIO)):
                    m.next = "RECV-COUNT-1"
                with m.Elif((cmd & CMD_MASK) == CMD_GET_AUX):
                    m.next = "SEND-AUX"
                with m.Elif((cmd & CMD_MASK) == CMD_SET_AUX):
                    m.next = "RECV-AUX"

            with m.State("SEND-AUX"):
                with m.If(self._in_fifo.writable):
                    m.d.comb += [
                        self._in_fifo.we.eq(1),
                        self._in_fifo.din.eq(self.adapter.aux_i),
                    ]
                    m.next = "RECV-COMMAND"

            with m.State("RECV-AUX"):
                with m.If(self._out_fifo.readable):
                    m.d.comb += self._out_fifo.re.eq(1)
                    m.d.sync += self.adapter.aux_o.eq(self._out_fifo.dout)
                    m.next = "RECV-COMMAND"

            with m.State("RECV-COUNT-1"):
                with m.If(self._out_fifo.readable):
                    m.d.comb += self._out_fifo.re.eq(1)
                    m.d.sync += count[0:8].eq(self._out_fifo.dout)
                    m.next = "RECV-COUNT-2"

            with m.State("RECV-COUNT-2"):
                with m.If(self._out_fifo.readable):
                    m.d.comb += self._out_fifo.re.eq(1),
                    m.d.sync += count[8:16].eq(self._out_fifo.dout)
                    m.next = "RECV-BITS"

            with m.State("RECV-BITS"):
                with m.If(count == 0):
                    m.next = "RECV-COMMAND"
                with m.Else():
                    with m.If(count > 8):
                        m.d.sync += bitno.eq(0)
                    with m.Else():
                        m.d.sync += [
                            align.eq(8 - count[:3]),
                            bitno.eq(8 - count[:3]),
                        ]
                    with m.If(cmd & BIT_DATA_OUT):
                        with m.If(self._out_fifo.readable):
                            m.d.comb += self._out_fifo.re.eq(1)
                            m.d.sync += shreg_o.eq(self._out_fifo.dout)
                            m.next = "SHIFT-SETUP"
                    with m.Else():
                        m.d.sync += shreg_o.eq(0b11111111)
                        m.next = "SHIFT-SETUP"

            with m.State("SHIFT-SETUP"):
                m.d.sync += self.adapter.stb.eq(1)
                with m.If((cmd & CMD_MASK) == CMD_SHIFT_TMS):
                    m.d.sync += self.adapter.tms.eq(shreg_o[0])
                    m.d.sync += self.adapter.tdi.eq((cmd & BIT_TDI) != 0)
                with m.Else():
                    m.d.sync += self.adapter.tms.eq(0)
                    with m.If(cmd & BIT_LAST):
                        m.d.sync += self.adapter.tms.eq(count == 1)
                    m.d.sync += self.adapter.tdi.eq(shreg_o[0])
                m.d.sync += [
                    shreg_o.eq(Cat(shreg_o[1:], 1)),
                    count.eq(count - 1),
                    bitno.eq(bitno + 1),
                ]
                m.next = "SHIFT-CAPTURE"

            with m.State("SHIFT-CAPTURE"):
                m.d.sync += self.adapter.stb.eq(0)
                with m.If(self.adapter.rdy):
                    m.d.sync += shreg_i.eq(Cat(shreg_i[1:], self.adapter.tdo))
                    with m.If(bitno == 0):
                        m.next = "SEND-BITS"
                    with m.Else():
                        m.next = "SHIFT-SETUP"

            with m.State("SEND-BITS"):
                with m.If(cmd & BIT_DATA_IN):
                    with m.If(self._in_fifo.writable):
                        m.d.comb += self._in_fifo.we.eq(1),
                        with m.If(count == 0):
                            m.d.comb += self._in_fifo.din.eq(shreg_i >> align)
                        with m.Else():
                            m.d.comb += self._in_fifo.din.eq(shreg_i)
                        m.next = "RECV-BITS"
                with m.Else():
                    m.next = "RECV-BITS"

        return m


class JTAGProbeSubtarget(Elaboratable):
    def __init__(self, pads, out_fifo, in_fifo, period_cyc):
        self._pads       = pads
        self._out_fifo   = out_fifo
        self._in_fifo    = in_fifo
        self._period_cyc = period_cyc

    def elaborate(self, platform):
        m = Module()
        m.submodules.bus     = JTAGProbeBus(self._pads)
        m.submodules.adapter = JTAGProbeAdapter(m.submodules.bus, self._period_cyc)
        m.submodules.driver  = JTAGProbeDriver(m.submodules.adapter, self._out_fifo, self._in_fifo)
        return m


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
        self._log_h("exchange ir-i=<%s>", dump_bin(data))
        await self.enter_shift_ir()
        data = await self.shift_tdio(data)
        await self.enter_update_ir()
        self._log_h("exchange ir-o=<%s>", dump_bin(data))
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
        self._log_h("exchange dr-i=<%s>", dump_bin(data))
        await self.enter_shift_dr()
        data = await self.shift_tdio(data)
        await self.enter_update_dr()
        self._log_h("exchange dr-o=<%s>", dump_bin(data))
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
            # Add 1 so that registers of exactly `max_length` could be scanned successfully.
            data_1 = await self.shift_tdio((1,) * (max_length + 1), last=False)
            data_0 = await self.shift_tdio((0,) * (max_length + 1), last=False)
            for length in range(max_length + 1):
                if data_0[length] == 0:
                    if all(data_1[length:]):
                        self._log_h("scan %s length=%d data=<%s>",
                                    xr, length, dump_bin(data_1[:length]))
                        return data_1[:length]
                    else:
                        self._log_h("overlong %s", xr)
                        return
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

    def interrogate_dr(self, dr_value):
        """Split DR value captured after TAP reset into IDCODE/BYPASS chunks."""

        idcodes = []
        offset = 0
        while offset < len(dr_value):
            if dr_value[offset]:
                if len(dr_value) - offset >= 32:
                    dr_chunk = dr_value[offset:offset + 32]
                    idcode = int(dr_chunk)
                    if dr_chunk[1:12] == bits("00001111111"):
                        self._log_h("invalid idcode=<%08x>", idcode)
                        return
                    else:
                        self._log_h("found idcode=<%08x>", idcode)
                    idcodes.append(idcode)
                    offset += 32
                else:
                    self._log_h("truncated idcode=<%s>", dump_bin(dr_value[offset:]))
                    return
            else:
                self._log_h("found bypass")
                idcodes.append(None)
                offset += 1

        return idcodes

    def interrogate_ir(self, ir_value, dr_count):
        assert dr_count > 0

        # Each captured IR value in a chain must start with <10>. However, the rest of captured
        # IR bits has unspecified value, which may include <10>.
        ir_starts = []
        while True:
            ir_start = ir_value.find((1,0), start=ir_starts[-1] + 1 if ir_starts else 0)
            if ir_start == -1:
                break
            ir_starts.append(ir_start)

        # There must be at least as many captured IRs in the chain as there are IDCODE/BYPASS DRs,
        # and the chain must start with a valid captured IR value.
        if len(ir_starts) < dr_count or ir_starts[0] != 0:
            self._log_h("invalid ir chain")
            return

        # If there's only one device in the chain, then the entire captured IR belongs to it.
        if dr_count == 1:
            ir_offset = 0
            ir_length = len(ir_value)
            self._log_h("found ir[%d] (only tap)", ir_length)
            return [(ir_offset, ir_length)]

        # If there are no more captured IRs than devices in the chain, then IR lengths can be
        # determined unambiguously.
        elif dr_count == len(ir_starts):
            irs = []
            ir_offset = 0
            for ir_start0, ir_start1 in zip(ir_starts, ir_starts[1:] + [len(ir_value)]):
                ir_length = ir_start1 - ir_start0
                self._log_h("found ir[%d] (tap #%d)", ir_length, len(irs))
                irs.append((ir_offset, ir_length))
                ir_offset += ir_length
            return irs

        # Otherwise IR lengths are ambiguous.
        else:
            ir_chunks = []
            for ir_start0, ir_start1 in zip(ir_starts, ir_starts[1:] + [len(ir_value)]):
                ir_chunks.append(ir_start1 - ir_start0)
            self._log_h("ambiguous ir chain length=%d chunks=%s",
                        len(ir_value), ",".join("{:d}".format(chunk) for chunk in ir_chunks))
            return None

    async def select_tap(self, tap, max_ir_length=128, max_dr_length=1024):
        await self.test_reset()

        dr_value = await self.scan_dr(max_dr_length)
        if dr_value is None:
            return

        idcodes = self.interrogate_dr(dr_value)
        if idcodes is None:
            return

        ir_value = await self.scan_ir(max_ir_length)
        if ir_value is None:
            return

        irs = self.interrogate_ir(ir_value, dr_count=len(idcodes))
        if not irs:
            return

        if tap >= len(irs):
            self._log_h("missing tap %d")
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
            help="set TCK frequency to FREQ kHz (default: %(default)s)")

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        iface.add_subtarget(JTAGProbeSubtarget(
            pads=iface.get_pads(args, pins=self.__pins),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(auto_flush=False),
            period_cyc=target.sys_clk_freq // (args.frequency * 1000),
        ))

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        return JTAGProbeInterface(iface, self.logger, has_trst=args.pin_trst is not None)

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

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

        p_scan = p_operation.add_parser(
            "scan", help="scan JTAG chain and attempt to identify devices",
            formatter_class=parser.formatter_class,
            description="""
            Reset the JTAG TAPs and shift IDCODE or BYPASS register values out to determine
            the count and (if available) identity of the devices in the scan chain.
            """)

        p_enumerate_ir = p_operation.add_parser(
            "enumerate-ir", help="(DANGEROUS) use heuristics to enumerate JTAG IR values",
            formatter_class=parser.formatter_class,
            description="""
            THIS COMMAND CAN PERMANENTLY DAMAGE DEVICE UNDER TEST.

            IEEE 1149.1 requires every unimplemented IR value to select the BYPASS DR.
            By selecting every possible IR value and measuring DR lengths, it is possible to
            discover IR values that definitively correspond to non-BYPASS DRs.

            Due to the design of JTAG state machine, measuring DR length requires going
            through Capture-DR and Update-DR states for instructions that may have
            IRREVERSIBLE or UNDEFINED behavior. Although this command updates the DR with
            the data just captured from it, IEEE 1149.1 does not require this operation
            to be idempotent. Additionally, many devices are not strictly compliant and
            in practice may perform IRREVERSIBLE or UNDEFINED actions during operations
            that IEEE 1149.1 requires to be benign, such as selecting an unimplemented
            instruction, or shifting into DR. USE THIS COMMAND AT YOUR OWN RISK.

            DR length measurement can have one of the following four results:
                * DR[n], n > 1: non-BYPASS n-bit DR.
                * DR[1]: (likely) BYPASS or (less likely) non-BYPASS 1-bit DR.
                  This result is not shown because most IR values correspond to DR[1].
                * DR[0]: TDI connected directly to TDO.
                  This is not allowed by IEEE 1149.1, but is very common in practice.
                * DR[?]: (commonly) no connection to TDO or (less commonly) complex logic
                  connected between TDI and TDO that is active during Shift-DR.
                  This is not allowed by IEEE 1149.1, but is common in practice.
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
                self.logger.error("DR length scan did not terminate")
                return
            self.logger.info("shifted %d-bit DR=<%s>", len(dr_value), dump_bin(dr_value))

            ir_value = await jtag_iface.scan_ir(max_length=args.max_ir_length)
            if ir_value is None:
                self.logger.error("IR length scan did not terminate")
                return
            self.logger.info("shifted %d-bit IR=<%s>", len(ir_value), dump_bin(ir_value))

            idcodes = jtag_iface.interrogate_dr(dr_value)
            if idcodes is None:
                self.logger.error("DR interrogation failed")
                return
            if len(idcodes) == 0:
                self.logger.warning("DR interrogation discovered no TAPs")
                return
            self.logger.info("discovered %d TAPs", len(idcodes))

            irs = jtag_iface.interrogate_ir(ir_value, dr_count=len(idcodes))

        if args.operation == "scan":
            if not irs:
                self.logger.warning("IR interrogation failed")
                irs = [(None, "?") for _ in idcodes]

            for tap_index, (idcode_value, (ir_offset, ir_length)) in enumerate(zip(idcodes, irs)):
                if idcode_value is None:
                    self.logger.info("TAP #%d: IR[%s] BYPASS",
                                     tap_index, ir_length)
                else:
                    idcode   = DR_IDCODE.from_int(idcode_value)
                    mfg_name = jedec_mfg_name_from_bank_num(idcode.mfg_id >> 7,
                                                            idcode.mfg_id & 0x7f)
                    if mfg_name is None:
                        mfg_name = "unknown"
                    self.logger.info("TAP #%d: IR[%s] IDCODE=%#010x",
                                     tap_index, ir_length, idcode_value)
                    self.logger.info("manufacturer=%#05x (%s) part=%#06x version=%#03x",
                                     idcode.mfg_id, mfg_name, idcode.part_id, idcode.version)

        if args.operation == "enumerate-ir":
            if not irs:
                self.logger.error("IR interrogation failed")
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
                        level = logging.WARN
                        dr_length = "?"
                    elif dr_length == 0:
                        level = logging.WARN
                    elif dr_length == 1:
                        level = logging.DEBUG
                    else:
                        level = logging.INFO
                    self.logger.log(level, "  IR=%s DR[%s]", ir_value, dr_length)

        if args.operation == "jtag-repl":
            self.logger.info("dropping to REPL; use 'help(iface)' to see available APIs")
            await AsyncInteractiveConsole(
                locals={"iface":jtag_iface},
                run_callback=jtag_iface.flush
            ).interact()

        if args.operation == "tap-repl":
            tap_iface = await jtag_iface.select_tap(args.tap_index,
                                                    args.max_ir_length, args.max_dr_length)
            if not tap_iface:
                self.logger.error("cannot select TAP #%d" % args.tap_index)
                return

            self.logger.info("dropping to REPL; use 'help(iface)' to see available APIs")
            await AsyncInteractiveConsole(
                locals={"iface":tap_iface},
                run_callback=jtag_iface.flush
            ).interact()

# -------------------------------------------------------------------------------------------------

import unittest


class JTAGSegmentationTestCase(unittest.TestCase):
    def setUp(self):
        self.iface = JTAGProbeInterface(interface=None, logger=JTAGProbeApplet.logger)

    def test_dr_empty(self):
        self.assertEqual(self.iface.interrogate_dr(bits("")), [])

    def test_dr_bypass(self):
        self.assertEqual(self.iface.interrogate_dr(bits("0")), [None])

    def test_dr_idcode(self):
        dr = bits("00111011101000000000010001110111")
        self.assertEqual(self.iface.interrogate_dr(dr), [0x3ba00477])

    def test_dr_truncated(self):
        dr = bits("0011101110100000000001000111011")
        self.assertEqual(self.iface.interrogate_dr(dr), None)

    def test_dr_bypass_idcode(self):
        dr = bits("001110111010000000000100011101110")
        self.assertEqual(self.iface.interrogate_dr(dr), [None, 0x3ba00477])

    def test_dr_idcode_bypass(self):
        dr = bits("000111011101000000000010001110111")
        self.assertEqual(self.iface.interrogate_dr(dr), [0x3ba00477, None])

    def test_dr_invalid(self):
        dr = bits("00000000000000000000000011111111")
        self.assertEqual(self.iface.interrogate_dr(dr), None)

    def test_ir_1tap_0start(self):
        ir = bits("0000")
        self.assertEqual(self.iface.interrogate_ir(ir, 1),
                         None)

    def test_ir_1tap_1start(self):
        ir = bits("0001")
        self.assertEqual(self.iface.interrogate_ir(ir, 1),
                         [(0, 4)])

    def test_ir_1tap_2start(self):
        ir = bits("0101")
        self.assertEqual(self.iface.interrogate_ir(ir, 1),
                         [(0, 4)])

    def test_ir_2tap_1start(self):
        ir = bits("0001")
        self.assertEqual(self.iface.interrogate_ir(ir, 2),
                         None)

    def test_ir_2tap_2start(self):
        ir = bits("01001")
        self.assertEqual(self.iface.interrogate_ir(ir, 2),
                         [(0, 3), (3, 2)])


class JTAGProbeAppletTestCase(GlasgowAppletTestCase, applet=JTAGProbeApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
