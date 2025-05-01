# Ref: IEEE Std 1149.1-2001
# Accession: G00018

# Note: this TAP implementation primarily exists to test the JTAG probe gateware. It has some
# known design quirks. If you want to add a TAP to your design, use the one from amaranth-stdio,
# (assuming it has been merged by the time you're reading this).

from typing import Iterable

from amaranth import *
from amaranth.lib import enum, data, wiring, io, cdc
from amaranth.lib.wiring import In, Out


__all__ = ["State", "DataRegister", "Controller"]


class State(enum.Enum, shape=unsigned(4)):
    Test_Logic_Reset = 0x0
    Run_Test_Idle    = 0x8

    Select_DR_Scan   = 0x1
    Capture_DR       = 0x2
    Shift_DR         = 0x3
    Exit1_DR         = 0x4
    Pause_DR         = 0x5
    Exit2_DR         = 0x6
    Update_DR        = 0x7

    Select_IR_Scan   = 0x9
    Capture_IR       = 0xA
    Shift_IR         = 0xB
    Exit1_IR         = 0xC
    Pause_IR         = 0xD
    Exit2_IR         = 0xE
    Update_IR        = 0xF


class DataRegister(wiring.PureInterface):
    def __init__(self, length):
        assert length >= 1, "DR must be at least 1 bit long"

        self._length = length

        super().__init__(wiring.Signature({
            "cap": In(length),
            "upd": Out(length),
        }))

    @property
    def length(self):
        return self._length


class Controller(wiring.Component):
    def __init__(self, *, ir_length, ir_idcode=None):
        assert ir_length >= 2, "IR must be at least 2 bits long"

        self._ir_length = ir_length
        self._drs       = dict()

        if ir_idcode is not None:
            self._dr_idcode = self.add({ir_idcode}, length=32)
        else:
            self._dr_idcode = None

        super().__init__({
            # TRST# is implicit in the (asynchronous) reset signal of the `jtag` clock domain.
            # TCK is implicit in the clock signal `jtag` clock domain.
            "tms": Out(io.Buffer.Signature("i", 1)),
            "tdi": Out(io.Buffer.Signature("i", 1)),
            "tdo": Out(io.Buffer.Signature("o", 1)),

            # TAP state.
            "state": Out(State, init=State.Test_Logic_Reset),

            # The high bits of the value loaded into the IR scan chain in the Capture-IR state.
            # The low bits are fixed at `01` (with 1 loaded into the least significant bit).
            "ir_cap": In(ir_length - 2),
            # The last value loaded into the IR scan chain in the Update-IR state; in other words,
            # the contents of the instruction register.
            "ir_upd": Out(ir_length, init=~0 if ir_idcode is None else ir_idcode),
        })

    @property
    def ir_length(self) -> int:
        return self._ir_length

    @property
    def dr_idcode(self) -> DataRegister:
        return self._dr_idcode

    def add(self, ir_values: Iterable[int], *, length: int) -> DataRegister:
        ir_values = set(ir_values)

        for ir_value in ir_values:
            assert ir_value in range(0, 1 << self._ir_length), "IR value must be within range"
            assert ir_value != ((1 << self._ir_length) - 1), "IR value must not be all-ones"
        for used_ir_values in self._drs.values():
            assert not (ir_values & used_ir_values), "IR values must be unused"

        dr = DataRegister(length)
        self._drs[dr] = ir_values
        return dr

    def elaborate(self, platform):
        m = Module()

        with m.Switch(self.state):
            with m.Case(State.Test_Logic_Reset):
                with m.If(~self.tms.i):
                    m.d.jtag += self.state.eq(State.Run_Test_Idle)

            with m.Case(State.Run_Test_Idle):
                with m.If(self.tms.i):
                    m.d.jtag += self.state.eq(State.Select_DR_Scan)

            with m.Case(State.Select_DR_Scan):
                with m.If(~self.tms.i):
                    m.d.jtag += self.state.eq(State.Capture_DR)
                with m.Else():
                    m.d.jtag += self.state.eq(State.Select_IR_Scan)

            with m.Case(State.Capture_DR):
                with m.If(self.tms.i):
                    m.d.jtag += self.state.eq(State.Exit1_DR)
                with m.Else():
                    m.d.jtag += self.state.eq(State.Shift_DR)

            with m.Case(State.Shift_DR):
                with m.If(self.tms.i):
                    m.d.jtag += self.state.eq(State.Exit1_DR)

            with m.Case(State.Exit1_DR):
                with m.If(self.tms.i):
                    m.d.jtag += self.state.eq(State.Update_DR)
                with m.Else():
                    m.d.jtag += self.state.eq(State.Pause_DR)

            with m.Case(State.Pause_DR):
                with m.If(self.tms.i):
                    m.d.jtag += self.state.eq(State.Exit2_DR)

            with m.Case(State.Exit2_DR):
                with m.If(self.tms.i):
                    m.d.jtag += self.state.eq(State.Update_DR)
                with m.Else():
                    m.d.jtag += self.state.eq(State.Shift_DR)

            with m.Case(State.Update_DR):
                with m.If(self.tms.i):
                    m.d.jtag += self.state.eq(State.Select_DR_Scan)
                with m.Else():
                    m.d.jtag += self.state.eq(State.Run_Test_Idle)

            with m.Case(State.Select_IR_Scan):
                with m.If(~self.tms.i):
                    m.d.jtag += self.state.eq(State.Capture_IR)
                with m.Else():
                    m.d.jtag += self.state.eq(State.Test_Logic_Reset)

            with m.Case(State.Capture_IR):
                with m.If(~self.tms.i):
                    m.d.jtag += self.state.eq(State.Shift_IR)
                with m.Else():
                    m.d.jtag += self.state.eq(State.Exit1_IR)

            with m.Case(State.Shift_IR):
                with m.If(self.tms.i):
                    m.d.jtag += self.state.eq(State.Exit1_IR)

            with m.Case(State.Exit1_IR):
                with m.If(self.tms.i):
                    m.d.jtag += self.state.eq(State.Update_IR)
                with m.Else():
                    m.d.jtag += self.state.eq(State.Pause_IR)

            with m.Case(State.Pause_IR):
                with m.If(self.tms.i):
                    m.d.jtag += self.state.eq(State.Exit2_IR)

            with m.Case(State.Exit2_IR):
                with m.If(self.tms.i):
                    m.d.jtag += self.state.eq(State.Update_IR)
                with m.Else():
                    m.d.jtag += self.state.eq(State.Shift_IR)

            with m.Case(State.Update_IR):
                with m.If(self.tms.i):
                    m.d.jtag += self.state.eq(State.Select_DR_Scan)
                with m.Else():
                    m.d.jtag += self.state.eq(State.Run_Test_Idle)

        dr_chain = Signal(max([1, *(dr.length for dr in self._drs)]))
        ir_chain = Signal(self.ir_length)

        with m.Switch(self.state):
            m.d.comb += self.tdo.oe.eq(0)

            with m.Case(State.Test_Logic_Reset):
                m.d.jtag += self.ir_upd.eq(self.ir_upd.init)
                for dr, ir_values in self._drs.items():
                    m.d.jtag += dr.upd.eq(dr.upd.init)

            with m.Case(State.Capture_DR):
                with m.Switch(self.ir_upd):
                    for dr, ir_values in self._drs.items():
                        with m.Case(*ir_values):
                            m.d.jtag += dr_chain[-dr.length:].eq(dr.cap)
                    with m.Default(): # BYPASS
                        m.d.jtag += dr_chain.eq(0)

            with m.Case(State.Shift_DR):
                m.d.jtag += dr_chain.eq(Cat(dr_chain[1:], self.tdi.i))
                with m.Switch(self.ir_upd):
                    for dr, ir_values in self._drs.items():
                        with m.Case(*ir_values):
                            m.d.comb += self.tdo.o.eq(dr_chain[-dr.length])
                    with m.Default(): # BYPASS
                        m.d.comb += self.tdo.o.eq(dr_chain[-1])
                m.d.comb += self.tdo.oe.eq(1)

            with m.Case(State.Update_DR):
                with m.Switch(self.ir_upd):
                    for dr, ir_values in self._drs.items():
                        with m.Case(*ir_values):
                            m.d.jtag += dr.upd.eq(dr_chain[-dr.length:])
                    with m.Default(): # BYPASS
                        pass

            with m.Case(State.Capture_IR):
                m.d.jtag += ir_chain.eq(Cat(1, 0, self.ir_cap))

            with m.Case(State.Shift_IR):
                m.d.jtag += ir_chain.eq(Cat(ir_chain[1:], self.tdi.i))
                m.d.comb += self.tdo.o.eq(ir_chain[0])
                m.d.comb += self.tdo.oe.eq(1)

            with m.Case(State.Update_IR):
                m.d.jtag += self.ir_upd.eq(ir_chain)

        return m
