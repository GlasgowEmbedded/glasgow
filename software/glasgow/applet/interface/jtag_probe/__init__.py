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
import argparse
import enum
from amaranth import *
from amaranth.lib import io, cdc

from ....support.bits import *
from ....support.logging import *
from ....support.arepl import *
from ....database.jedec import *
from ....arch.jtag import *
from ... import *


class JTAGState(str, enum.Enum):
    # The names are JTAG SVF state names; the values are IEEE names.
    UNKNOWN = "Unknown"
    RESET = "Test-Logic-Reset"
    IDLE = "Run-Test/Idle"
    DRSELECT = "Select-DR-Scan"
    DRCAPTURE = "Capture-DR"
    DRSHIFT = "Shift-DR"
    DREXIT1 = "Exit1-DR"
    DRPAUSE = "Pause-DR"
    DREXIT2 = "Exit2-DR"
    DRUPDATE = "Update-DR"
    IRSELECT = "Select-IR-Scan"
    IRCAPTURE = "Capture-IR"
    IRSHIFT = "Shift-IR"
    IREXIT1 = "Exit1-IR"
    IRPAUSE = "Pause-IR"
    IREXIT2 = "Exit2-IR"
    IRUPDATE = "Update-IR"


JTAG_TRANSITIONS = {
    JTAGState.RESET: (JTAGState.IDLE, JTAGState.RESET),
    JTAGState.IDLE: (JTAGState.IDLE, JTAGState.DRSELECT),
    JTAGState.DRSELECT: (JTAGState.DRCAPTURE, JTAGState.IRSELECT),
    JTAGState.DRCAPTURE: (JTAGState.DRSHIFT, JTAGState.DREXIT1),
    JTAGState.DRSHIFT: (JTAGState.DRSHIFT, JTAGState.DREXIT1),
    JTAGState.DREXIT1: (JTAGState.DRPAUSE, JTAGState.DRUPDATE),
    JTAGState.DRPAUSE: (JTAGState.DRPAUSE, JTAGState.DREXIT2),
    JTAGState.DREXIT2: (JTAGState.DRSHIFT, JTAGState.DRUPDATE),
    JTAGState.DRUPDATE: (JTAGState.IDLE, JTAGState.DRSELECT),
    JTAGState.IRSELECT: (JTAGState.IRCAPTURE, JTAGState.RESET),
    JTAGState.IRCAPTURE: (JTAGState.IRSHIFT, JTAGState.IREXIT1),
    JTAGState.IRSHIFT: (JTAGState.IRSHIFT, JTAGState.IREXIT1),
    JTAGState.IREXIT1: (JTAGState.IRPAUSE, JTAGState.IRUPDATE),
    JTAGState.IRPAUSE: (JTAGState.IRPAUSE, JTAGState.IREXIT2),
    JTAGState.IREXIT2: (JTAGState.IRSHIFT, JTAGState.IRUPDATE),
    JTAGState.IRUPDATE: (JTAGState.IDLE, JTAGState.DRSELECT),
}


class JTAGProbeBus(Elaboratable):
    def __init__(self, ports):
        self._ports = ports

        self.tck = Signal(init=1)
        self.tms = Signal(init=1)
        self.tdo = Signal(init=1)
        self.tdi = Signal(init=1)
        self.trst_z = Signal(init=0)
        self.trst_o = Signal(init=0)

    def elaborate(self, platform):
        m = Module()
        m.submodules.tck = tck_buffer = io.Buffer("o", self._ports.tck)
        m.d.comb += tck_buffer.o.eq(self.tck)
        m.submodules.tms = tms_buffer = io.Buffer("o", self._ports.tms)
        m.d.comb += tms_buffer.o.eq(self.tms)
        m.submodules.tdi = tdi_buffer = io.Buffer("o", self._ports.tdi)
        m.d.comb += tdi_buffer.o.eq(self.tdi)
        m.submodules.tdo = tdo_buffer = io.Buffer("i", self._ports.tdo)
        m.submodules += cdc.FFSynchronizer(tdo_buffer.i, self.tdo)
        if self._ports.trst is not None:
            m.submodules.trst = trst_buffer = io.Buffer("o", ~self._ports.trst)
            m.d.comb += trst_buffer.oe.eq(~self.trst_z)
            m.d.comb += trst_buffer.o.eq(self.trst_o)
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
                with m.If(self._out_fifo.r_rdy):
                    m.d.comb += self._out_fifo.r_en.eq(1)
                    m.d.sync += cmd.eq(self._out_fifo.r_data)
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
                with m.If(self._in_fifo.w_rdy):
                    m.d.comb += [
                        self._in_fifo.w_en.eq(1),
                        self._in_fifo.w_data.eq(self.adapter.aux_i),
                    ]
                    m.next = "RECV-COMMAND"

            with m.State("RECV-AUX"):
                with m.If(self._out_fifo.r_rdy):
                    m.d.comb += self._out_fifo.r_en.eq(1)
                    m.d.sync += self.adapter.aux_o.eq(self._out_fifo.r_data)
                    m.next = "RECV-COMMAND"

            with m.State("RECV-COUNT-1"):
                with m.If(self._out_fifo.r_rdy):
                    m.d.comb += self._out_fifo.r_en.eq(1)
                    m.d.sync += count[0:8].eq(self._out_fifo.r_data)
                    m.next = "RECV-COUNT-2"

            with m.State("RECV-COUNT-2"):
                with m.If(self._out_fifo.r_rdy):
                    m.d.comb += self._out_fifo.r_en.eq(1),
                    m.d.sync += count[8:16].eq(self._out_fifo.r_data)
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
                        with m.If(self._out_fifo.r_rdy):
                            m.d.comb += self._out_fifo.r_en.eq(1)
                            m.d.sync += shreg_o.eq(self._out_fifo.r_data)
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
                    with m.If(self._in_fifo.w_rdy):
                        m.d.comb += self._in_fifo.w_en.eq(1),
                        with m.If(count == 0):
                            m.d.comb += self._in_fifo.w_data.eq(shreg_i >> align)
                        with m.Else():
                            m.d.comb += self._in_fifo.w_data.eq(shreg_i)
                        m.next = "RECV-BITS"
                with m.Else():
                    m.next = "RECV-BITS"

        return m


class JTAGProbeSubtarget(Elaboratable):
    def __init__(self, ports, out_fifo, in_fifo, period_cyc):
        self._ports      = ports
        self._out_fifo   = out_fifo
        self._in_fifo    = in_fifo
        self._period_cyc = period_cyc

    def elaborate(self, platform):
        m = Module()
        m.submodules.bus     = JTAGProbeBus(self._ports)
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
    scan_ir_max_length = 128
    scan_dr_max_length = 1024

    def __init__(self, interface, logger, has_trst=False, __name__=__name__):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        self.has_trst    = has_trst
        self._state      = JTAGState.UNKNOWN
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
            if self._state == JTAGState.IRSHIFT:
                self._log_l("state Shift-IR → Exit1-IR")
                self._state = JTAGState.IREXIT1
            elif self._state == JTAGState.DRSHIFT:
                self._log_l("state Shift-DR → Exit1-DR")
                self._state = JTAGState.DREXIT1

    @staticmethod
    def _chunk_count(count, last, chunk_size=0xffff):
        assert count >= 0
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

    async def _shift_dummy(self, count, last=False):
        for count, chunk_last in self._chunk_count(count, last):
            await self.lower.write(struct.pack("<BH",
                CMD_SHIFT_TDIO|(BIT_LAST if chunk_last else 0), count))

    async def shift_tdio(self, tdi_bits, *, prefix=0, suffix=0, last=True):
        assert self._state in (JTAGState.IRSHIFT, JTAGState.DRSHIFT)
        tdi_bits = bits(tdi_bits)
        tdo_bits = bits()
        self._log_l("shift tdio-i=%d,<%s>,%d", prefix, dump_bin(tdi_bits), suffix)
        await self._shift_dummy(prefix)
        for tdi_bits, chunk_last in self._chunk_bits(tdi_bits, last and suffix == 0):
            await self.lower.write(struct.pack("<BH",
                CMD_SHIFT_TDIO|BIT_DATA_IN|BIT_DATA_OUT|(BIT_LAST if chunk_last else 0),
                len(tdi_bits)))
            tdi_bytes = bytes(tdi_bits)
            await self.lower.write(tdi_bytes)
            tdo_bytes = await self.lower.read(len(tdi_bytes))
            tdo_bits += bits(tdo_bytes, len(tdi_bits))
        await self._shift_dummy(suffix, last)
        self._log_l("shift tdio-o=%d,<%s>,%d", prefix, dump_bin(tdo_bits), suffix)
        self._shift_last(last)
        return tdo_bits

    async def shift_tdi(self, tdi_bits, *, prefix=0, suffix=0, last=True):
        assert self._state in (JTAGState.IRSHIFT, JTAGState.DRSHIFT)
        tdi_bits = bits(tdi_bits)
        self._log_l("shift tdi=%d,<%s>,%d", prefix, dump_bin(tdi_bits), suffix)
        await self._shift_dummy(prefix)
        for tdi_bits, chunk_last in self._chunk_bits(tdi_bits, last and suffix == 0):
            await self.lower.write(struct.pack("<BH",
                CMD_SHIFT_TDIO|BIT_DATA_OUT|(BIT_LAST if chunk_last else 0),
                len(tdi_bits)))
            tdi_bytes = bytes(tdi_bits)
            await self.lower.write(tdi_bytes)
        await self._shift_dummy(suffix, last)
        self._shift_last(last)

    async def shift_tdo(self, count, *, prefix=0, suffix=0, last=True):
        assert self._state in (JTAGState.IRSHIFT, JTAGState.DRSHIFT)
        tdo_bits = bits()
        await self._shift_dummy(prefix)
        for count, chunk_last in self._chunk_count(count, last and suffix == 0):
            await self.lower.write(struct.pack("<BH",
                CMD_SHIFT_TDIO|BIT_DATA_IN|(BIT_LAST if chunk_last else 0),
                count))
            tdo_bytes = await self.lower.read((count + 7) // 8)
            tdo_bits += bits(tdo_bytes, count)
        await self._shift_dummy(suffix, last)
        self._log_l("shift tdo=%d,<%s>,%d", prefix, dump_bin(tdo_bits), suffix)
        self._shift_last(last)
        return tdo_bits

    async def pulse_tck(self, count):
        assert self._state in (JTAGState.IDLE, JTAGState.IRPAUSE, JTAGState.DRPAUSE)
        self._log_l("pulse tck count=%d", count)
        for count, last in self._chunk_count(count, last=True):
            await self.lower.write(struct.pack("<BH",
                CMD_SHIFT_TDIO, count))

    # State machine transitions

    def _state_error(self, new_state, old_state=None):
        if old_state is None:
            old_state = self._state
        raise JTAGProbeStateTransitionError("cannot transition from state {} to {}",
                                            old_state.value, new_state.value)

    def get_state(self):
        return self._state

    async def enter_test_logic_reset(self, force=True):
        if force:
            self._log_l("state * → Test-Logic-Reset")
        elif self._state != JTAGState.RESET:
            self._log_l("state %s → Test-Logic-Reset", self._state.value)
        else:
            return

        await self.shift_tms((1,1,1,1,1))
        self._state = JTAGState.RESET

    async def enter_run_test_idle(self):
        if self._state == JTAGState.IDLE: return

        self._log_l("state %s → Run-Test/Idle", self._state.value)
        if self._state == JTAGState.RESET:
            await self.shift_tms((0,))
        elif self._state in (JTAGState.IREXIT1, JTAGState.DREXIT1):
            await self.shift_tms((1,0))
        elif self._state in (JTAGState.IRPAUSE, JTAGState.DRPAUSE):
            await self.shift_tms((1,1,0))
        elif self._state in (JTAGState.IRUPDATE, JTAGState.DRUPDATE):
            await self.shift_tms((0,))
        else:
            self._state_error(JTAGState.IDLE)
        self._state = JTAGState.IDLE

    async def enter_capture_ir(self):
        if self._state == JTAGState.IRCAPTURE: return

        self._log_l("state %s → Capture-IR", self._state.value)
        if self._state == JTAGState.RESET:
            await self.shift_tms((0,1,1,0))
        elif self._state in (JTAGState.IDLE, JTAGState.IRUPDATE, JTAGState.DRUPDATE):
            await self.shift_tms((1,1,0))
        elif self._state in (JTAGState.DRPAUSE, JTAGState.IRPAUSE):
            await self.shift_tms((1,1,1,1,0))
        else:
            self._state_error(JTAGState.IRCAPTURE)
        self._state = JTAGState.IRCAPTURE

    async def enter_shift_ir(self):
        if self._state == JTAGState.IRSHIFT: return

        self._log_l("state %s → Shift-IR", self._state.value)
        if self._state == JTAGState.RESET:
            await self.shift_tms((0,1,1,0,0))
        elif self._state in (JTAGState.IDLE, JTAGState.IRUPDATE, JTAGState.DRUPDATE):
            await self.shift_tms((1,1,0,0))
        elif self._state == JTAGState.DRPAUSE:
            await self.shift_tms((1,1,1,1,0,0))
        elif self._state == JTAGState.IRPAUSE:
            await self.shift_tms((1,0))
        elif self._state == JTAGState.IRCAPTURE:
            await self.shift_tms((0,))
        else:
            self._state_error(JTAGState.IRSHIFT)
        self._state = JTAGState.IRSHIFT

    async def enter_pause_ir(self):
        if self._state == JTAGState.IRPAUSE: return

        self._log_l("state %s → Pause-IR", self._state.value)
        if self._state == JTAGState.IREXIT1:
            await self.shift_tms((0,))
        else:
            self._state_error(JTAGState.IRPAUSE)
        self._state = JTAGState.IRPAUSE

    async def enter_update_ir(self):
        if self._state == JTAGState.IRUPDATE: return

        self._log_l("state %s → Update-IR", self._state.value)
        if self._state in (JTAGState.IRSHIFT, JTAGState.IRCAPTURE):
            await self.shift_tms((1,1))
        elif self._state == JTAGState.IREXIT1:
            await self.shift_tms((1,))
        else:
            self._state_error(JTAGState.IRUPDATE)
        self._state = JTAGState.IRUPDATE

    async def enter_capture_dr(self):
        if self._state == JTAGState.DRCAPTURE: return

        self._log_l("state %s → Capture-DR", self._state.value)
        if self._state == JTAGState.RESET:
            await self.shift_tms((0,1,0))
        elif self._state in (JTAGState.IDLE, JTAGState.IRUPDATE, JTAGState.DRUPDATE):
            await self.shift_tms((1,0))
        elif self._state in (JTAGState.IRPAUSE, JTAGState.DRPAUSE):
            await self.shift_tms((1,1,1,0))
        else:
            self._state_error(JTAGState.DRCAPTURE)
        self._state = JTAGState.DRCAPTURE

    async def enter_shift_dr(self):
        if self._state == JTAGState.DRSHIFT: return

        self._log_l("state %s → Shift-DR", self._state.value)
        if self._state == JTAGState.RESET:
            await self.shift_tms((0,1,0,0))
        elif self._state in (JTAGState.IDLE, JTAGState.IRUPDATE, JTAGState.DRUPDATE):
            await self.shift_tms((1,0,0))
        elif self._state == JTAGState.IRPAUSE:
            await self.shift_tms((1,1,1,0,0))
        elif self._state == JTAGState.DRPAUSE:
            await self.shift_tms((1,0))
        elif self._state == JTAGState.DRCAPTURE:
            await self.shift_tms((0,))
        else:
            self._state_error(JTAGState.DRSHIFT)
        self._state = JTAGState.DRSHIFT

    async def enter_pause_dr(self):
        if self._state == JTAGState.DRPAUSE: return

        self._log_l("state %s → Pause-DR", self._state.value)
        if self._state == JTAGState.DREXIT1:
            await self.shift_tms((0,))
        else:
            self._state_error(JTAGState.DRPAUSE)
        self._state = JTAGState.DRPAUSE

    async def enter_update_dr(self):
        if self._state == JTAGState.DRUPDATE: return

        self._log_l("state %s → Update-DR", self._state.value)
        if self._state in (JTAGState.DRSHIFT, JTAGState.DRCAPTURE):
            await self.shift_tms((1,1))
        elif self._state == JTAGState.DREXIT1:
            await self.shift_tms((1,))
        else:
            self._state_error(JTAGState.DRUPDATE)
        self._state = JTAGState.DRUPDATE

    async def traverse_state_path(self, path):
        if not path:
            return
        self._log_l(f"state {self._state.value} → {' → '.join(s.value for s in path)}")
        state = self._state
        bits = []
        for target in path:
            assert isinstance(state, JTAGState)
            if JTAG_TRANSITIONS[state][0] == target:
                bits.append(0)
            elif JTAG_TRANSITIONS[state][1] == target:
                bits.append(1)
            else:
                self._state_error(target, state)
            state = target
        await self.shift_tms(bits)
        self._state = state

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

    async def exchange_ir(self, data, *, prefix=0, suffix=0):
        data = bits(data)
        self._current_ir = (prefix, data, suffix)
        self._log_h("exchange ir-i=%d,<%s>,%d", prefix, dump_bin(data), suffix)
        if not data:
            await self.enter_capture_ir()
            data = bits()
        else:
            await self.enter_shift_ir()
            data = await self.shift_tdio(data, prefix=prefix, suffix=suffix)
        await self.enter_update_ir()
        self._log_h("exchange ir-o=%d,<%s>,%d", prefix, dump_bin(data), suffix)
        return data

    async def read_ir(self, count, *, prefix=0, suffix=0):
        self._current_ir = (prefix, bits((1,)) * count, suffix)
        if not count:
            await self.enter_capture_ir()
            data = bits()
        else:
            await self.enter_shift_ir()
            data = await self.shift_tdo(count, prefix=prefix, suffix=suffix)
        await self.enter_update_ir()
        self._log_h("read ir=%d,<%s>,%d", prefix, dump_bin(data), suffix)
        return data

    async def write_ir(self, data, *, prefix=0, suffix=0, elide=True):
        data = bits(data)
        if (prefix, data, suffix) == self._current_ir and elide:
            self._log_h("write ir (elided)")
            return
        self._current_ir = (prefix, data, suffix)
        self._log_h("write ir=%d,<%s>,%d", prefix, dump_bin(data), suffix)
        if not data:
            await self.enter_capture_ir()
        else:
            await self.enter_shift_ir()
            await self.shift_tdi(data, prefix=prefix, suffix=suffix)
        await self.enter_update_ir()

    async def exchange_dr(self, data, *, prefix=0, suffix=0):
        self._log_h("exchange dr-i=%d,<%s>,%d", prefix, dump_bin(data), suffix)
        if not data:
            await self.enter_capture_dr()
            data = bits()
        else:
            await self.enter_shift_dr()
            data = await self.shift_tdio(data, prefix=prefix, suffix=suffix)
        await self.enter_update_dr()
        self._log_h("exchange dr-o=%d,<%s>,%d", prefix, dump_bin(data), suffix)
        return data

    async def read_dr(self, count, *, prefix=0, suffix=0):
        if not count:
            await self.enter_capture_dr()
            data = bits()
        else:
            await self.enter_shift_dr()
            data = await self.shift_tdo(count, prefix=prefix, suffix=suffix)
        await self.enter_update_dr()
        self._log_h("read dr=%d,<%s>,%d", prefix, dump_bin(data), suffix)
        return data

    async def write_dr(self, data, *, prefix=0, suffix=0):
        data = bits(data)
        self._log_h("write dr=%d,<%s>,%d", prefix, dump_bin(data), suffix)
        if not data:
            await self.enter_capture_dr()
        else:
            await self.enter_shift_dr()
            await self.shift_tdi(data, prefix=prefix, suffix=suffix)
        await self.enter_update_dr()

    # Shift chain introspection

    async def _scan_xr(self, xr, *, max_length=None, check=True, idempotent=True):
        assert xr in ("ir", "dr")
        if idempotent:
            self._log_h("scan %s idempotent", xr)
        else:
            self._log_h("scan %s", xr)

        if max_length is None:
            if xr == "ir":
                max_length = self.scan_ir_max_length
            if xr == "dr":
                max_length = self.scan_dr_max_length

        if xr == "ir":
            await self.enter_shift_ir()
        if xr == "dr":
            await self.enter_shift_dr()

        # Add 1 so that registers of exactly `max_length` could be scanned successfully.
        data_0 = await self.shift_tdio((0,) * (max_length + 1), last=False)
        data_1 = await self.shift_tdio((1,) * (max_length + 1), last=not idempotent)

        try:
            value = None
            for length in range(max_length + 1):
                if data_1[length] == 1:
                    if data_0[length:].to_int() == 0:
                        value = data_0[:length]
                    break

            if value is None:
                self._log_h("scan %s overlong", xr)
                if check:
                    raise JTAGProbeError(f"{xr.upper()} shift chain is too long")
            elif len(value) == 0:
                self._log_h("scan %s empty", xr)
                if check:
                    raise JTAGProbeError(f"{xr.upper()} shift chain is empty")
            else:
                self._log_h("scan %s length=%d data=<%s>",
                            xr, length, dump_bin(data_0[:length]))
            return value

        finally:
            if idempotent:
                if value is None or length == 0:
                    # Idempotent scan requested, but isn't possible: finish shifting.
                    await self.shift_tdi((1,), last=True)
                else:
                    # Idempotent scan is possible: shift scanned data back.
                    await self.shift_tdi(value, last=True)

            await self.enter_run_test_idle()

    async def scan_ir(self, *, max_length=None, check=True):
        return await self._scan_xr("ir", max_length=max_length, check=check, idempotent=False)

    async def scan_dr(self, *, max_length=None, check=True):
        return await self._scan_xr("dr", max_length=max_length, check=check, idempotent=True)

    async def scan_ir_length(self, *, max_length=None):
        return len(await self.scan_ir(max_length=max_length))

    async def scan_dr_length(self, *, max_length=None):
        return len(await self.scan_dr(max_length=max_length))

    async def scan_reset_dr_ir(self):
        """Capture IR values and IDCODE/BYPASS DR values using Test-Logic-Reset."""

        await self.test_reset()
        # Scan DR chain first, since scanning IR chain will latch BYPASS into every IR.
        dr_value = await self._scan_xr("dr", idempotent=False)
        ir_value = await self._scan_xr("ir", idempotent=False)
        return (dr_value, ir_value)

    # Blind interrogation

    def interrogate_dr(self, dr_value, *, check=True):
        """Split DR value captured after TAP reset into IDCODE/BYPASS chunks."""

        idcodes = []
        offset = 0
        while offset < len(dr_value):
            if dr_value[offset]:
                if len(dr_value) - offset >= 32:
                    dr_chunk = dr_value[offset:offset + 32]
                    idcode = int(dr_chunk)
                    if dr_chunk[1:12] == bits("00001111111"):
                        self._log_h("invalid dr idcode=%08x", idcode)
                        if check:
                            raise JTAGProbeError("TAP #{} has invalid DR IDCODE={:08x}"
                                                 .format(len(idcodes), idcode))
                        return
                    else:
                        self._log_h("found dr idcode=%08x (tap #%d)", idcode, len(idcodes))
                    idcodes.append(idcode)
                    offset += 32
                else:
                    self._log_h("truncated dr idcode=<%s>", dump_bin(dr_value[offset:]))
                    if check:
                        raise JTAGProbeError("TAP #{} has truncated DR IDCODE=<{}>"
                                             .format(len(idcodes), dump_bin(dr_value[offset:])))
                    return
            else:
                self._log_h("found dr bypass (tap #%d)", len(idcodes))
                idcodes.append(None)
                offset += 1

        return idcodes

    def interrogate_ir(self, ir_value, tap_count, *, ir_lengths=None, check=True):
        """Split IR value captured after TAP reset to determine IR boundaries."""
        assert tap_count > 0

        # Each captured IR value in a chain must start with <10>. However, the rest of captured
        # IR bits has unspecified value, which may include <10>.
        ir_starts = []
        while True:
            ir_start = ir_value.find((1,0), start=ir_starts[-1] + 1 if ir_starts else 0)
            if ir_start == -1:
                break
            ir_starts.append(ir_start)

        # There must be at least as many captured IRs in the chain as there are IDCODE/BYPASS DRs.
        if tap_count > len(ir_starts):
            self._log_h("invalid ir taps=%d starts=%d", tap_count, len(ir_starts))
            if check:
                raise JTAGProbeError("IR capture has fewer <10> transitions than TAPs")
            return

        # The chain must start with a valid captured IR value.
        if ir_starts[0] != 0:
            self._log_h("invalid ir starts[0]=%d", ir_starts[0])
            if check:
                raise JTAGProbeError("IR capture does not start with <10> transition")
            return

        # If IR lengths are specified explicitly, use them but validate first.
        if ir_lengths is not None:
            if len(ir_lengths) != tap_count:
                self._log_h("invalid ir taps=%d user-lengths=%d", tap_count, len(ir_lengths))
                if check:
                    raise JTAGProbeError("IR length count differs from TAP count")
                return

            if sum(ir_lengths) != len(ir_value):
                self._log_h("invalid ir total-length=%d user-total-length=%d",
                            sum(ir_lengths), len(ir_value))
                if check:
                    raise JTAGProbeError("IR capture length differs from sum of IR lengths")
                return

            ir_offset = 0
            for tap_index, ir_length in enumerate(ir_lengths):
                if (ir_offset + ir_length not in ir_starts and
                        ir_offset + ir_length != len(ir_value)):
                    self._log_h("misaligned ir (tap #%d)", tap_index)
                    if check:
                        raise JTAGProbeError("IR length for TAP #{:d} misaligns next TAP"
                                             .format(tap_index))
                    return

                self._log_h("explicit ir length=%d (tap #%d)", ir_length, tap_index)
                ir_offset += ir_length

            return list(ir_lengths)

        # If there's only one device in the chain, then the entire captured IR belongs to it.
        elif tap_count == 1:
            ir_length = len(ir_value)
            self._log_h("found ir length=%d (single tap)", ir_length)
            return [ir_length]

        # If there are no more captured IRs than devices in the chain, then IR lengths can be
        # determined unambiguously.
        elif tap_count == len(ir_starts):
            ir_layout = []
            for ir_start0, ir_start1 in zip(ir_starts, ir_starts[1:] + [len(ir_value)]):
                ir_length = ir_start1 - ir_start0
                self._log_h("found ir length=%d (tap #%d)", ir_length, len(ir_layout))
                ir_layout.append(ir_length)
            return ir_layout

        # Otherwise IR lengths are ambiguous.
        else:
            ir_chunks = []
            for ir_start0, ir_start1 in zip(ir_starts, ir_starts[1:] + [len(ir_value)]):
                ir_chunks.append(ir_start1 - ir_start0)
            self._log_h("ambiguous ir taps=%d chunks=[%s]",
                        tap_count, ",".join(f"{chunk:d}" for chunk in ir_chunks))
            if check:
                raise JTAGProbeError("IR capture insufficiently constrains IR lengths")
            return

    async def select_tap(self, index, *, ir_lengths=None):
        dr_value, ir_value = await self.scan_reset_dr_ir()
        idcodes = self.interrogate_dr(dr_value)
        ir_layout = self.interrogate_ir(ir_value, tap_count=len(idcodes), ir_lengths=ir_lengths)
        return TAPInterface.from_layout(self, ir_layout, index=index)


class TAPInterface:
    @classmethod
    def from_layout(cls, lower, ir_layout, *, index):
        if index not in range(len(ir_layout)):
            raise JTAGProbeError("TAP #{:d} is not a part of {:d}-TAP chain"
                                 .format(index, len(ir_layout)))

        return cls(lower, ir_length=ir_layout[index],
            ir_prefix=sum(ir_layout[:index]), ir_suffix=sum(ir_layout[index + 1:]),
            dr_prefix=len(ir_layout[:index]), dr_suffix=len(ir_layout[index + 1:]))

    def __init__(self, lower, *, ir_length, ir_prefix=0, ir_suffix=0, dr_prefix=0, dr_suffix=0):
        self.lower = lower
        self.ir_length  = ir_length
        self._ir_prefix = ir_prefix
        self._ir_suffix = ir_suffix
        self._dr_prefix = dr_prefix
        self._dr_suffix = dr_suffix

    async def flush(self):
        await self.lower.flush()

    async def test_reset(self):
        await self.lower.test_reset()

    async def run_test_idle(self, count):
        await self.lower.run_test_idle(count)

    async def exchange_ir(self, data):
        data = bits(data)
        assert len(data) == self.ir_length
        return await self.lower.exchange_ir(data,
            prefix=self._ir_prefix, suffix=self._ir_suffix)

    async def read_ir(self):
        return await self.lower.read_ir(self.ir_length,
            prefix=self._ir_prefix, suffix=self._ir_suffix)

    async def write_ir(self, data, *, elide=True):
        data = bits(data)
        assert len(data) == self.ir_length
        await self.lower.write_ir(data, elide=elide,
            prefix=self._ir_prefix, suffix=self._ir_suffix)

    async def exchange_dr(self, data):
        return await self.lower.exchange_dr(data,
            prefix=self._dr_prefix, suffix=self._dr_suffix)

    async def read_dr(self, length):
        return await self.lower.read_dr(length,
            prefix=self._dr_prefix, suffix=self._dr_suffix)

    async def write_dr(self, data):
        await self.lower.write_dr(data,
            prefix=self._dr_prefix, suffix=self._dr_suffix)

    async def scan_dr(self, *, check=True, max_length=None):
        if max_length is not None:
            max_length = self._dr_prefix + max_length + self._dr_suffix
        data = await self.lower.scan_dr(check=check, max_length=max_length)
        if data is None:
            return data
        if check and len(data) == self._dr_prefix + self._dr_suffix:
            raise JTAGProbeError("DR shift chain is empty")
        assert len(data) > self._dr_prefix + self._dr_suffix
        if self._dr_suffix:
            return data[self._dr_prefix:-self._dr_suffix]
        else:
            return data[self._dr_prefix:]

    async def scan_dr_length(self, *, max_length=None):
        if max_length is not None:
            max_length = self._dr_prefix + max_length + self._dr_suffix
        length = await self.lower.scan_dr_length(max_length=max_length)
        if length == self._dr_prefix + self._dr_suffix:
            raise JTAGProbeError("DR shift chain is empty")
        assert length > self._dr_prefix + self._dr_suffix
        return length - self._dr_prefix - self._dr_suffix


class JTAGProbeApplet(GlasgowApplet):
    logger = logging.getLogger(__name__)
    help = "test integrated circuits via IEEE 1149.1 JTAG"
    description = """
    Identify, test and debug integrated circuits and board assemblies via IEEE 1149.1 JTAG.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        for pin in ("tck", "tms", "tdi", "tdo"):
            access.add_pins_argument(parser, pin, default=True)
        access.add_pins_argument(parser, "trst")

        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=100,
            help="set TCK frequency to FREQ kHz (default: %(default)s)")

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        iface.add_subtarget(JTAGProbeSubtarget(
            ports=iface.get_port_group(
                tck=args.tck,
                tms=args.tms,
                tdi=args.tdi,
                tdo=args.tdo,
                trst=args.trst,
            ),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(auto_flush=False),
            period_cyc=target.sys_clk_freq // (args.frequency * 1000),
        ))

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)

        parser.add_argument(
            "--scan-ir-max-length", metavar="LENGTH", type=int,
            default=JTAGProbeInterface.scan_ir_max_length,
            help="give up scanning IRs longer than LENGTH bits (default: %(default)s)")
        parser.add_argument(
            "--scan-dr-max-length", metavar="LENGTH", type=int,
            default=JTAGProbeInterface.scan_dr_max_length,
            help="give up scanning DRs longer than LENGTH bits (default: %(default)s)")

        def ir_lengths(args):
            lengths = []
            for arg in args.split(","):
                try:
                    length = int(arg, 10)
                    if length >= 2:
                        lengths.append(length)
                        continue
                except ValueError:
                    pass
                raise argparse.ArgumentTypeError("{!r} is not a valid IR length"
                                                 .format(arg))
            return lengths

        parser.add_argument(
            "--ir-lengths", metavar="IR-LENGTH,...", default=None, type=ir_lengths,
            help="set IR lengths of each TAP to corresponding IR-LENGTH (default: autodetect)")

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        jtag_iface = JTAGProbeInterface(iface, self.logger, has_trst=args.trst is not None)
        jtag_iface.scan_ir_max_length = args.scan_ir_max_length
        jtag_iface.scan_dr_max_length = args.scan_dr_max_length
        return jtag_iface

    @classmethod
    def add_run_tap_arguments(cls, parser):
        parser.add_argument(
            "--tap-index", metavar="INDEX", type=int,
            help="select TAP #INDEX for communication (default: select only TAP)")

    async def run_tap(self, cls, device, args):
        jtag_iface = await self.run_lower(cls, device, args)

        dr_value, ir_value = await jtag_iface.scan_reset_dr_ir()
        idcodes = jtag_iface.interrogate_dr(dr_value)
        ir_layout = jtag_iface.interrogate_ir(ir_value,
            tap_count=len(idcodes), ir_lengths=args.ir_lengths)

        tap_index = args.tap_index
        if tap_index is None:
            if len(idcodes) > 1:
                raise JTAGProbeError("multiple TAPs found; use explicit --tap-index")
            else:
                tap_index = 0
        return TAPInterface.from_layout(jtag_iface, ir_layout, index=tap_index)

    @classmethod
    def add_interact_arguments(cls, parser):
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
            help="enumerate IR values for TAP(s) #INDEX")

    async def interact(self, device, args, jtag_iface):
        dr_value, ir_value = await jtag_iface.scan_reset_dr_ir()
        self.logger.info("shifted %d-bit DR=<%s>", len(dr_value), dump_bin(dr_value))
        self.logger.info("shifted %d-bit IR=<%s>", len(ir_value), dump_bin(ir_value))

        idcodes = jtag_iface.interrogate_dr(dr_value)
        if len(idcodes) == 0:
            self.logger.warning("DR interrogation discovered no TAPs")
            return
        self.logger.info("discovered %d TAPs", len(idcodes))

        if args.operation == "scan":
            ir_layout = jtag_iface.interrogate_ir(ir_value,
                tap_count=len(idcodes), ir_lengths=args.ir_lengths, check=False)
            if not ir_layout:
                self.logger.warning("IR interrogation failed")
                ir_layout = ["?" for _ in idcodes]

            for tap_index, (idcode_value, ir_length) in enumerate(zip(idcodes, ir_layout)):
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
            ir_layout = jtag_iface.interrogate_ir(ir_value,
                tap_count=len(idcodes), ir_lengths=args.ir_lengths)
            for tap_index in args.tap_indexes:
                ir_length = ir_layout[tap_index]
                self.logger.info("TAP #%d: IR[%d]", tap_index, ir_length)

                tap_iface = TAPInterface.from_layout(jtag_iface, ir_layout, index=tap_index)
                for ir_value in range(0, (1 << ir_length)):
                    ir_value = bits(ir_value, ir_length)
                    await tap_iface.test_reset()
                    await tap_iface.write_ir(ir_value)
                    dr_value = await tap_iface.scan_dr(check=False)
                    if dr_value is None:
                        dr_length = "?"
                        level = logging.WARN
                    else:
                        dr_length = len(dr_value)
                        if dr_length == 0:
                            level = logging.WARN
                        elif dr_length == 1:
                            level = logging.DEBUG
                        else:
                            level = logging.INFO
                    self.logger.log(level, "  IR=%s DR[%s]", ir_value, dr_length)

    @classmethod
    def add_repl_arguments(cls, parser):
        # Inheriting from the JTAG probe applet does not inherit the REPL.
        if cls is not JTAGProbeApplet:
            return super().add_repl_arguments(parser)

        parser.add_argument(
            "--tap-index", metavar="INDEX", type=int,
            help="select TAP #INDEX instead of the full chain")

    async def repl(self, device, args, jtag_iface):
        # See explanation in add_repl_arguments().
        if type(self) is not JTAGProbeApplet:
            return await super().repl(device, args, jtag_iface)

        if args.tap_index is None:
            iface = jtag_iface
            self.logger.info("dropping to REPL for JTAG chain; "
                             "use 'help(iface)' to see available APIs")
        else:
            iface = await jtag_iface.select_tap(args.tap_index, ir_lengths=args.ir_lengths)
            self.logger.info("dropping to REPL for TAP #%d; "
                             "use 'help(iface)' to see available APIs",
                             args.tap_index)
        await AsyncInteractiveConsole(
            locals={"iface":iface},
            run_callback=jtag_iface.flush
        ).interact()

    @classmethod
    def tests(cls):
        from . import test
        return test.JTAGProbeAppletTestCase
