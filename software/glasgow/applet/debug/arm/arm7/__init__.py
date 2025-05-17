# Ref: ARM7TDMI-S Revision: r4p3 Technical Reference Manual
# Document Number: DDI 0234B
# Accession: G00093

# Ref: ARM7TDMI-S Errata List
# Document number: FR002-PRDC-002719 7.0
# Accession: G00095

# Things you wish ARM told you about this core (more explicitly or at all):
#  * The bit order in the scan chain 1 is backwards. This is technically documented (read p. 5-34
#    _very carefully_), but not in a way that anybody would notice.
#  * The bit order in the data field of the scan chain 2 is documented backwards, but is not.
#  * If you interrupt the core with DBGRQ, you have to drop DBGRQ before it'll do anything.
#  * DBGACK can be set without DBGRQ. It is because DBGACK does a double duty as the signal that
#    causes the peripherals to ignore side effectful memory accesses while debugging. They tell you
#    to make your debugger set it while performing memory accesses.
#  * ... except that you do want peripherals to be manipulatable by your debugger, so sometimes
#    you don't actually want to do that. Also goddess knows whether any given peripheral does
#    anything different with DBGACK asserted and if yes then what the semantics of it is.
#  * The documentation says you can set bit 33 (DBGBREAK) on loads/stores. This is false. You have
#    to set it on the preceding instruction (usually a nop). It does technically say that DBGBREAK
#    is pipeline on top of page 5-41 but in a very confusing way.
#  * Be careful when running `LDR R0, [R0]`. Since you are putting data on the data bus, and not
#    directly into the register, the address in R0 still influences the result: if it's unaligned,
#    the data will be transposed bytewise.
#  * The debug entry latency, when measured, appears to be one lower than the documented value.
#    OpenOCD also uses the lower value, without explanation why.
#  * The documentation states that the debug status register allows "synchronized versions of DBGRQ
#    and DBGACK to be read", but this is misleading. What it actually does is lets you read DBGRQ
#    externally asserted to the core, and DBGACK asserted by the core. Conversely, the control
#    register allows asserting DBGACK to the peripherals without it being reflected in the debug
#    status register. (Conceptually, these registers cut into the wires for DBGRQ/DBGACK.)
#  * Halt on DBGRQ is completely broken on ARM7TDMI due to extensive errata. You have to use
#    a breakpoint configured to activate on any instruction fetch instead.
#    (ARM7TDMI-S Errata List §4.7.4)

# Some design choices in this applet:
#  * The gateware handles all JTAG interfacing with the DUT. It presents a high-level(ish)
#    interface to the software, allowing it to read/write EICE registers as well as shift data
#    in and out of the CPU data bus. It can also poll EICE debug status register for readiness.
#  * The command/response protocol of the gateware is optimized for bulk memory reads/writes, with
#    the goal being multi-MB/s throughput with little host-side CPU load. For this reason,
#    the gateware handles the CPU data bus bit order transformation, and all communication is
#    done in easy to manipulate chunks: 1 or 1+4 byte commands, and 4 byte responses. Responses
#    can be read into a Python `array` (and e.g. endian-swapped, etc) without ever iterating
#    individual words in a Python loop.
#  * The ARM7TDMI context is only 37 words. Since the main factor impacting debugging experience
#    is latency, and fetching a small amount of architectural state has the ~same latency (within
#    a few ms) as all of it, we always fetch all of it. (This happens because we can read out all
#    of the architectural state within a single USB roundtrip.) This also saves us latency later,
#    since GDB can examine all state without any USB communications.

import sys
import array
import asyncio
import logging
import argparse
import contextlib
from dataclasses import dataclass
from amaranth import *
from amaranth.lib import enum, wiring, stream, io
from amaranth.lib.wiring import In, Out

from .....support.lazy import *
from .....support.bits import *
from .....support.logging import *
from .....support.endpoint import ServerEndpoint
from .....arch.jtag import *
from .....arch.arm.jtag.arm7 import *
from .....arch.arm.instr import *
from .....database.jedec import *
from .....gateware.stream import StreamBuffer
from .....gateware.jtag import probe as jtag_probe
from .....protocol.gdb_remote import *
from .... import GlasgowAppletError, GlasgowAppletV2


class DebugARM7Error(GlasgowAppletError):
    pass


class DebugARM7Opcode(enum.Enum, shape=3):
    GET_REG  = 0b000
    SET_REG  = 0b001

    GET_BUS  = 0b010
    PUT_BUS  = 0b011

    RESTART  = 0b101
    POLL_ACK = 0b110
    CANCEL   = 0b100 # (does nothing unless sent directly after POLL_ACK)

    GET_ID   = 0b111


class DebugARM7Sequencer(wiring.Component):
    i_stream: In(stream.Signature(8))
    o_stream: Out(stream.Signature(8))
    o_flush:  Out(1)

    divisor:  In(8)

    def __init__(self, ports):
        self._ports = ports

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        if self._ports.trst:
            m.submodules.trst_buffer = trst_buffer = io.Buffer("o", self._ports.trst)
            m.d.comb += trst_buffer.o.eq(1)

        m.submodules.probe = probe = jtag_probe.Sequencer(self._ports, width=38)
        m.d.comb += probe.divisor.eq(self.divisor)

        m.submodules.probe_o_buffer = probe_o_buffer = StreamBuffer(probe.o_stream.payload.shape())
        wiring.connect(m, probe.o_stream, probe_o_buffer.i)
        probe_o_buffered = probe_o_buffer.o

        @contextlib.contextmanager
        def probe_command(cmd, data):
            m.d.comb += [
                probe.i_stream.p.cmd.eq(cmd),
                probe.i_stream.p.data.eq(data),
                probe.i_stream.p.size.eq(len(data)),
                probe.i_stream.valid.eq(1),
            ]
            with m.If(probe.i_stream.ready):
                yield

        with m.FSM(init="Reset TAP") as fsm:
            header = Signal(8)
            opcode = DebugARM7Opcode(header[5:])
            i_data = Signal(32)
            o_data = Signal(32)

            chain  = Signal(4, init=0)

            @contextlib.contextmanager
            def select_chain(want_chain):
                with m.If(chain == want_chain):
                    yield
                with m.Else():
                    m.d.sync += chain.eq(want_chain)
                    m.next = "Set IR SCAN_N"

            with m.State("Reset TAP"):
                with probe_command(jtag_probe.Command.Reset, bits()):
                    m.next = "Fetch command"

            with m.State("Fetch command"):
                m.d.sync += header.eq(self.i_stream.payload)
                m.d.comb += self.i_stream.ready.eq(1)
                with m.If(self.i_stream.valid):
                    with m.Switch(self.i_stream.payload[5:]):
                        with m.Case(DebugARM7Opcode.SET_REG, DebugARM7Opcode.PUT_BUS):
                            m.next = "Fetch data"
                        with m.Default():
                            m.next = "Run command"
                with m.Else():
                    m.d.comb += self.o_flush.eq(1)

            with m.State("Fetch data"):
                i_offset = Signal(2)
                m.d.sync += i_data.word_select(i_offset, 8).eq(self.i_stream.payload)
                m.d.comb += self.i_stream.ready.eq(1)
                with m.If(self.i_stream.valid):
                    m.d.sync += i_offset.eq(i_offset + 1)
                    with m.If(i_offset == 3):
                        m.next = "Run command"

            with m.State("Run command"):
                with m.Switch(opcode):
                    with m.Case(DebugARM7Opcode.GET_REG, DebugARM7Opcode.SET_REG,
                                DebugARM7Opcode.POLL_ACK):
                        with select_chain(2):
                            m.next = "Set IR INTEST"

                    with m.Case(DebugARM7Opcode.GET_BUS, DebugARM7Opcode.PUT_BUS):
                        with select_chain(1):
                            m.next = "Set IR INTEST"

                    with m.Case(DebugARM7Opcode.RESTART):
                        m.next = "Set IR RESTART"

                    with m.Case(DebugARM7Opcode.CANCEL):
                        m.next = "Fetch command"

                    with m.Case(DebugARM7Opcode.GET_ID):
                        m.next = "Set IR IDCODE"

            with m.State("Set IR SCAN_N"):
                with probe_command(jtag_probe.Command.SetIR, IR_SCAN_N):
                    m.next = "Set DR SCAN_N"

            with m.State("Set DR SCAN_N"):
                with probe_command(jtag_probe.Command.SetDR, chain):
                    m.next = "Run command" # restart command

            with m.State("Set IR INTEST"):
                with probe_command(jtag_probe.Command.SetIR, IR_INTEST):
                    m.next = "Run INTEST command"

            with m.State("Run INTEST command"):
                with m.Switch(opcode):
                    with m.Case(DebugARM7Opcode.GET_REG):
                        jtag_data = Cat(C(0, 32), header[:5], 0)
                        with probe_command(jtag_probe.Command.SetDR, jtag_data):
                            m.next = "Get register value"

                    with m.Case(DebugARM7Opcode.SET_REG):
                        jtag_data = Cat(i_data, header[:5], 1)
                        with probe_command(jtag_probe.Command.SetDR, jtag_data):
                            m.next = "Run test"

                    with m.Case(DebugARM7Opcode.POLL_ACK):
                        jtag_data = Cat(C(0, 32), C(1, 5), 0) # debug status register
                        with probe_command(jtag_probe.Command.SetDR, jtag_data):
                            m.next = "Poll for TRANS[1] & DBGACK"

                    with m.Case(DebugARM7Opcode.GET_BUS):
                        jtag_data = Cat(C(0, 32), 0)
                        with probe_command(jtag_probe.Command.GetDR, jtag_data):
                            m.next = "Send data"

                    with m.Case(DebugARM7Opcode.PUT_BUS):
                        jtag_data = Cat(i_data, header[0])[::-1]
                        with probe_command(jtag_probe.Command.SetDR, jtag_data):
                            m.next = "Run test"

            with m.State("Get register value"):
                jtag_data = Cat(C(0, 32), C(1, 5), 0) # register with no read side effects
                with probe_command(jtag_probe.Command.GetDR, jtag_data):
                    m.next = "Send data"

            with m.State("Poll for TRANS[1] & DBGACK"):
                jtag_data = Cat(C(0, 32), C(1, 5), 0) # debug status register
                with probe_command(jtag_probe.Command.GetDR, jtag_data):
                    m.next = "Check for TRANS[1] & DBGACK"

            with m.State("Check for TRANS[1] & DBGACK"):
                with m.If(probe_o_buffered.valid):
                    # The only way to determine whether the memory access has completed is
                    # to examine the state of both TRANS[1:0] and DBGACK. When both are HIGH,
                    # the access has completed.
                    dbgsta = probe_o_buffered.p.data
                    completed = dbgsta[3] & dbgsta[0]
                    # Certain polls are cancellable by queueing another command. Such polls
                    # always return a response (on both completion and cancellation), unlike
                    # normal polls which do not.
                    cancellable = header[0]
                    cancelled = self.i_stream.valid & \
                        (self.i_stream.payload[5:] == DebugARM7Opcode.CANCEL)
                    with m.If(cancellable & (completed | cancelled)):
                        m.next = "Send data"
                    with m.Elif(completed):
                        m.d.comb += probe_o_buffered.ready.eq(1)
                        m.next = "Fetch command"
                    with m.Else():
                        m.d.comb += probe_o_buffered.ready.eq(1)
                        m.next = "Poll for TRANS[1] & DBGACK"

            with m.State("Set IR RESTART"):
                with probe_command(jtag_probe.Command.SetIR, IR_RESTART):
                    m.next = "Run test"

            with m.State("Set IR IDCODE"):
                with probe_command(jtag_probe.Command.SetIR, IR_IDCODE):
                    m.next = "Get DR IDCODE"

            with m.State("Get DR IDCODE"):
                with probe_command(jtag_probe.Command.GetDR, bits(0, 32)):
                    m.next = "Send data"

            with m.State("Send data"):
                with m.If(opcode == DebugARM7Opcode.GET_BUS):
                    m.d.comb += o_data.eq(probe_o_buffered.p.data[:33][::-1])
                with m.Else():
                    m.d.comb += o_data.eq(probe_o_buffered.p.data[:32])

                o_offset = Signal(2)
                m.d.comb += self.o_stream.payload.eq(o_data.word_select(o_offset, 8))
                m.d.comb += self.o_stream.valid.eq(probe_o_buffered.valid)
                with m.If(self.o_stream.valid & self.o_stream.ready):
                    m.d.sync += o_offset.eq(o_offset + 1)
                    with m.If(o_offset == 3):
                        m.d.comb += probe_o_buffered.ready.eq(1)
                        with m.If(opcode == DebugARM7Opcode.GET_BUS):
                            m.next = "Run test"
                        with m.Else():
                            m.next = "Fetch command"

            with m.State("Run test"):
                with probe_command(jtag_probe.Command.RunTest, bits()):
                    m.next = "Fetch command"

        return m


class DebugARM7Transaction:
    def __init__(self, logger):
        self._logger  = logger
        self._depth   = 2
        self._level   = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        self._buffer  = bytearray()
        self._to_read = 0
        self._results = None

    def _log(self, message, *args):
        level = logging.TRACE if self._depth > 2 else self._level
        self._logger.log(level, "ARM7: " + "  " * self._depth + message, *args)

    @contextlib.contextmanager
    def _log_group(self, message, *args):
        self._log(message, *args)
        self._depth += 1
        try:
            yield
        finally:
            self._depth -= 1

    def _cmd(self, opcode: DebugARM7Opcode, arg1=0, arg2=None):
        self._buffer.append((opcode.value << 5) | (arg1 & 0x1f))
        if arg2 is not None:
            self._buffer += (arg2 & 0xffffffff).to_bytes(4, byteorder="little")

    def _ret(self, count=None):
        if count is None:
            base, self._to_read = self._to_read, self._to_read + 1
            index = base
        else:
            base, self._to_read = self._to_read, self._to_read + count
            index = slice(base, base + count)
        def _get():
            assert self._results is not None, \
                "Attempted to use results before submitting transaction"
            return self._results[index]
        return lazy(_get)

    @property
    def results(self):
        # Useful for reading out all results of a single sequential memory read.
        return self._results

    @contextlib.contextmanager
    def repeat(self, count):
        self._buffer, old_buffer = bytearray(), self._buffer
        self._to_read, old_to_read = 0, self._to_read
        with self._log_group("repeat(%d)", count):
            yield
        self._buffer = old_buffer + self._buffer * count
        self._to_read = old_to_read + self._to_read * count

    def identify(self) -> int:
        self._log("identify() -> 1")
        self._cmd(DebugARM7Opcode.GET_ID)
        return self._ret()

    @staticmethod
    def _eice_reg_cls(addr):
        match addr:
            case EICE_Reg.DBGCTL:
                return EICE_DBGCTL
            case EICE_Reg.DBGSTA:
                return EICE_DBGSTA
            case (EICE_Reg.W0_CTRL_VAL | EICE_Reg.W0_CTRL_MSK |
                  EICE_Reg.W1_CTRL_VAL | EICE_Reg.W1_CTRL_MSK):
                return EICE_Wx_CTRL

    def eice_get(self, addr):
        self._log("eice_get(%d) -> 1", addr)
        self._cmd(DebugARM7Opcode.GET_REG, addr)
        result = self._ret()
        if cls := self._eice_reg_cls(addr):
            return lazy(lambda: cls.from_int(int(result)))
        else:
            return result

    def eice_set(self, addr, value=None, **kwargs):
        if value is None:
            value = self._eice_reg_cls(addr)(**kwargs).to_int()
        else:
            assert not kwargs
            value = int(value)
        if addr in (EICE_Reg.W0_ADDR_MSK, EICE_Reg.W0_DATA_MSK, EICE_Reg.W0_CTRL_MSK,
                    EICE_Reg.W1_ADDR_MSK, EICE_Reg.W1_DATA_MSK, EICE_Reg.W1_CTRL_MSK):
            # Invert mask values. In this debug macrocell, a 1 bit in a certain position means
            # that the corresponding value is don't-care, and 0 means it must match. This is
            # inconvenient, especially for control values which are mostly don't-care; invert them.
            value = value ^ 0xffffffff
        self._log("eice_set(%2d, %08x)", addr, value)
        self._cmd(DebugARM7Opcode.SET_REG, addr, value)

    def watchpt_fetch_addr(self, unit, address, width):
        assert unit in (0, 1)
        match width:
            case 4: size = 0b10 # word
            case 2: size = 0b01 # halfword
            case _: assert False
        self.eice_set(EICE_Reg.Wx_CTRL_VAL(unit), 0) # disable first
        self.eice_set(EICE_Reg.Wx_ADDR_MSK(unit), 0xffffffff & ~(width - 1))
        self.eice_set(EICE_Reg.Wx_ADDR_VAL(unit), address)
        self.eice_set(EICE_Reg.Wx_DATA_MSK(unit), 0)
        self.eice_set(EICE_Reg.Wx_DATA_VAL(unit), 0)
        self.eice_set(EICE_Reg.Wx_CTRL_MSK(unit), PROT=0b01, SIZE=0b11)
        self.eice_set(EICE_Reg.Wx_CTRL_VAL(unit), PROT=0b00, SIZE=size, ENABLE=1)

    def watchpt_fetch_data(self, unit, pattern, width):
        assert unit in (0, 1)
        match width:
            case 4: data = pattern
            case 2: data = (pattern << 16) | (pattern & 0xffff)
            case _: assert False
        self.eice_set(EICE_Reg.Wx_CTRL_VAL(unit), 0) # disable first
        self.eice_set(EICE_Reg.Wx_ADDR_MSK(unit), 0)
        self.eice_set(EICE_Reg.Wx_ADDR_VAL(unit), 0)
        self.eice_set(EICE_Reg.Wx_DATA_MSK(unit), 0xffffffff)
        self.eice_set(EICE_Reg.Wx_DATA_VAL(unit), data)
        self.eice_set(EICE_Reg.Wx_CTRL_MSK(unit), PROT=0b01)
        self.eice_set(EICE_Reg.Wx_CTRL_VAL(unit), PROT=0b00, ENABLE=1)

    def watchpt_step(self, address, width):
        match width:
            case 4: size = 0b10 # word
            case 2: size = 0b01 # halfword
            case _: assert False
        self.eice_set(EICE_Reg.W1_CTRL_VAL, 0) # disable first
        self.eice_set(EICE_Reg.W0_CTRL_VAL, 0)
        # configure watchpoint 1 to match only on the instruction address
        self.eice_set(EICE_Reg.W1_ADDR_MSK, 0xffffffff & ~(width - 1))
        self.eice_set(EICE_Reg.W1_ADDR_VAL, address)
        self.eice_set(EICE_Reg.W1_DATA_MSK, 0)
        self.eice_set(EICE_Reg.W1_DATA_VAL, 0)
        self.eice_set(EICE_Reg.W1_CTRL_MSK, PROT=0b01, SIZE=0b11)
        self.eice_set(EICE_Reg.W1_CTRL_VAL, PROT=0b00, SIZE=size) # must not be enabled!
        # configure watchpoint 0 to invert output of watchpoint 1, thus matching on every
        # instruction but one at the given address
        self.eice_set(EICE_Reg.W0_ADDR_MSK, 0)
        self.eice_set(EICE_Reg.W0_DATA_MSK, 0)
        self.eice_set(EICE_Reg.W0_CTRL_MSK, RANGE=1)
        self.eice_set(EICE_Reg.W0_CTRL_VAL, RANGE=0, ENABLE=1)

    def watchpt_clear(self, unit):
        assert unit in (0, 1)
        self.eice_set(EICE_Reg.Wx_CTRL_VAL(unit), 0)

    def eice_poll(self):
        self._log("eice_poll()")
        self._cmd(DebugARM7Opcode.POLL_ACK)

    def _restart(self):
        self._log("restart()")
        self._cmd(DebugARM7Opcode.RESTART)

    def _a_exec(self, insn, *, sys=0):
        assert sys in (0, 1) # note: `sys` applies for the *next* instruction after `insn`
        self._log("a_exec(%08x,%d)", insn, sys)
        self._cmd(DebugARM7Opcode.PUT_BUS, sys, insn)

    def _t_exec(self, insn, *, sys=0):
        assert (insn & ~0xffff) == 0
        self._log("t_exec(%04x,%d)", insn, sys)
        self._cmd(DebugARM7Opcode.PUT_BUS, sys, (insn << 16) | insn)

    def _load(self, *words):
        self._log("load(%s)", ", ".join(f"{word:08x}" for word in words))
        for word in words:
            self._cmd(DebugARM7Opcode.PUT_BUS, 0, word)

    def _store(self, count=None):
        if count is None:
            self._log("store() -> 1")
            self._cmd(DebugARM7Opcode.GET_BUS, 0)
        else:
            self._log("store() -> [%d]", count)
            for _ in range(count):
                self._cmd(DebugARM7Opcode.GET_BUS, 0)
        return self._ret(count)

    def _a_ld_st_sys(self, insn):
        self._a_exec(A_MOV(8, 8))                   # nop
        self._a_exec(A_MOV(8, 8), sys=1)            # nop
        self._a_exec(insn)                          # <insn>
        self._restart()                             # <restart>
        self.eice_poll()                            # <poll ack>
        self._a_exec(A_MOV(8, 8))                   # nop

    def t_str(self, rt):
        with self._log_group("t_str(r%d) -> 1", rt):
            self._t_exec(T_STR(rt, 0))              # str rt, [r0]
            self._t_exec(T_MOV(8, 8))               # nop
            self._t_exec(T_MOV(8, 8))               # nop
            return self._store()                    # <store rt>

    def a_str(self, rt):
        with self._log_group("a_str(r%d) -> 1", rt):
            self._a_exec(A_STR(rt, 0))              # str rt, [r0]
            self._a_exec(A_MOV(8, 8))               # nop
            self._a_exec(A_MOV(8, 8))               # nop
            return self._store()                    # <store rt>

    def a_stm(self, rn, mask, *, w=0):
        with self._log_group("a_stm(r%d%s, {%04x}) -> [%d]", rn, "!" if w else "",
                mask, mask.bit_count()):
            self._a_exec(A_STM(rn, mask, w=w))      # stm rn{w}, {mask}
            self._a_exec(A_MOV(8, 8))               # nop
            self._a_exec(A_MOV(8, 8))               # nop
            return self._store(mask.bit_count())    # <store mask>

    def t_ldr(self, rt, imm32):
        with self._log_group("t_ldr(r%d, #%08x)", rt, imm32):
            self._t_exec(T_LDR_LIT(rt, 0))          # ldr rt, [pc, #0]
            self._t_exec(T_MOV(8, 8))               # nop
            self._t_exec(T_MOV(8, 8))               # nop
            self._load(imm32)                       # <load imm32>
            self._t_exec(T_MOV(8, 8))               # nop

    def a_ldr(self, rt, imm32):
        with self._log_group("a_ldr(r%d, #%08x)", rt, imm32):
            self._a_exec(A_LDR(rt, 15, 0))          # ldr rt, [pc, #0]
            self._a_exec(A_MOV(8, 8))               # nop
            self._a_exec(A_MOV(8, 8))               # nop
            self._load(imm32)                       # <load imm32>
            self._a_exec(A_MOV(8, 8))               # nop

    def a_ldm(self, rn, mask, regs, *, w=0):
        with self._log_group("a_ldm(r%d%s, {%04x}, [%s])", rn, "!" if w else "",
                mask, ", ".join(f"{r:08x}" for r in regs)):
            self._a_exec(A_LDM(rn, mask, w=w))      # ldm rn{w}, {mask}
            self._a_exec(A_MOV(8, 8))               # nop
            self._a_exec(A_MOV(8, 8))               # nop
            self._load(*regs)                       # <load regs>
            self._a_exec(A_MOV(8, 8))               # nop

    def a_stm_sys(self, rn, mask, *, w=0):
        with self._log_group("a_stm_sys(r%d%s, {%04x})", rn, "!" if w else "", mask):
            self._a_ld_st_sys(A_STM(rn, mask, w=w)) # stm rn{w}, {mask}

    def a_strh_sys(self, rt, rn, imm=0, *, p=0, w=0):
        with self._log_group("a_strh_sys(r%d%s, r%d, #%x)", rt, "!" if w else "", rn, imm):
            self._a_ld_st_sys(A_STRH(rt, rn, imm, p=p, w=w))    # strh rt, [rn], +#imm

    def a_strb_sys(self, rt, rn, imm=0, *, p=0, w=0):
        with self._log_group("a_strb_sys(r%d%s, r%d, #%x)", rt, "!" if w else "", rn, imm):
            self._a_ld_st_sys(A_STRB(rt, rn, imm, p=p, w=w))    # strb rt, [rn], +#imm

    def a_ldm_sys(self, rn, mask, *, w=0):
        with self._log_group("a_ldm_sys(r%d%s, {%04x})", rn, "!" if w else "", mask):
            self._a_ld_st_sys(A_LDM(rn, mask, w=w)) # ldm rn{w}, {mask}

    def a_ldrh_sys(self, rt, rn, imm=0, *, p=0, w=0):
        with self._log_group("a_ldrh_sys(r%d%s, r%d, #%x)", rt, "!" if w else "", rn, imm):
            self._a_ld_st_sys(A_LDRH(rt, rn, imm, p=p, w=w))    # ldrh rt, [rn], +#imm

    def a_ldrb_sys(self, rt, rn, imm=0, *, p=0, w=0):
        with self._log_group("a_ldrb_sys(r%d%s, r%d, #%x)", rt, "!" if w else "", rn, imm):
            self._a_ld_st_sys(A_LDRB(rt, rn, imm, p=p, w=w))    # ldrb rt, [rn], +#imm

    def a_mrs_cpsr(self, rd):
        with self._log_group("a_mrs_cpsr(r%d) -> 1", rd):
            self._a_exec(A_MRS(rd, 0))              # mrs rd, cpsr

    def a_mrs_spsr(self, rd):
        with self._log_group("a_mrs_spsr(r%d) -> 1", rd):
            self._a_exec(A_MRS(rd, 1))              # mrs rd, spsr

    def a_msr_cpsr_c(self, imm):
        assert imm in range(0x100)
        with self._log_group("a_msr_cpsr_c(#%02x)", imm):
            self._a_exec(A_MSR_LIT(0, 0x1, imm))    # msr cpsr_c, #imm

    def a_msr_cpsr_fsxc(self, rn):
        with self._log_group("a_msr_cpsr_fsxc(r%d)", rn):
            self._a_exec(A_MSR_REG(0, 0xf, rn))     # msr cpsr_fsxc, rn

    def a_msr_spsr_fsxc(self, rn):
        with self._log_group("a_msr_spsr_fsxc(r%d)", rn):
            self._a_exec(A_MSR_REG(1, 0xf, rn))     # msr spsr_fsxc, rn

    def t_dbg_enter(self):
        with self._log_group("t_dbg_enter() -> r0, pc"):
            r0 = self.t_str(0)                      # str r0, <r0> [3 insns]
            self._t_exec(T_MOV(0, 15))              # mov r0, pc
            pc = self.t_str(0)                      # str r0, <pc>
            self._t_exec(T_EOR(0, 0))               # eor r0, r0
            self._t_exec(T_BX(0))                   # bx  r0
            self._t_exec(T_MOV(8, 8))               # nop
            self._t_exec(T_MOV(8, 8))               # nop
            return r0, lazy(lambda: pc
                - 3 * 2  # `mov r0, pc` has 3 instructions before it
                - 4)     # reading PC in Thumb state returns PC+4

    def a_dbg_enter(self):
        with self._log_group("a_dbg_enter() -> r0, pc"):
            r0 = self.a_str(0)                      # str r0, <r0> [3 insns]
            self._a_exec(A_MOV(0, 15))              # mov r0, pc
            pc = self.a_str(0)                      # str r0, <pc>
            return r0, lazy(lambda: pc
                - 3 * 4  # `mov r0, pc` has 3 instructions before it
                - 8)     # reading PC in ARM state returns PC+8

    def t_dbg_exit(self, r0, pc):
        with self._log_group("t_dbg_exit(r0=%08x, pc=%08x)", r0, pc):
            self.a_ldr(0, pc | 1)                   # ldr r0, <pc | 1>
            self._a_exec(A_BX(0))                   # bx  r0
            self._a_exec(A_MOV(8, 8))               # nop
            self._a_exec(A_MOV(8, 8))               # nop
            self.t_ldr(0, r0)                       # ldr r0, <r0>
            self._t_exec(T_MOV(8, 8))               # nop
            self._t_exec(T_MOV(8, 8), sys=1)        # nop
            self._t_exec(T_B(-7))                   # b   <back to r0>
            self._restart()                         # <restart>

    def a_dbg_exit(self, r0, pc):
        with self._log_group("a_dbg_exit(r0=%08x, pc=%08x)", r0, pc):
            self.a_ldr(0, pc)                       # ldr r0, <pc>
            self._a_exec(A_MOV(15, 0))              # mov pc, r0
            self._a_exec(A_MOV(8, 8))               # nop
            self._a_exec(A_MOV(8, 8))               # nop
            self.a_ldr(0, r0)                       # ldr r0, <r0>
            self._a_exec(A_MOV(8, 8))               # nop
            self._a_exec(A_MOV(8, 8), sys=1)        # nop
            self._a_exec(A_B(-7))                   # b   <back to r0>
            self._restart()                         # <restart>


@dataclass
class DebugARM7Context:
    cpsr:     int
    r0:       int; r1:       int; r2:       int; r3:       int
    r4:       int; r5:       int; r6:       int; r7:       int
    r8_usr:   int; r9_usr:   int; r10_usr:  int; r11_usr:  int
    r12_usr:  int; r13_usr:  int; r14_usr:  int; r15:      int
    r8_fiq:   int; r9_fiq:   int; r10_fiq:  int; r11_fiq:  int
    r12_fiq:  int; r13_fiq:  int; r14_fiq:  int; spsr_fiq: int
    r13_irq:  int; r14_irq:  int; spsr_irq: int
    r13_svc:  int; r14_svc:  int; spsr_svc: int
    r13_abt:  int; r14_abt:  int; spsr_abt: int
    r13_und:  int; r14_und:  int; spsr_und: int

    def __getattr__(self, name):
        mode = self.__getattribute__("cpsr") & 0x1f
        match name, mode:
            case "r8",   0b10001: return self.r8_fiq
            case "r8",   _:       return self.r8_usr
            case "r9",   0b10001: return self.r9_fiq
            case "r9",   _:       return self.r9_usr
            case "r10",  0b10001: return self.r10_fiq
            case "r10",  _:       return self.r10_usr
            case "r11",  0b10001: return self.r11_fiq
            case "r11",  _:       return self.r11_usr
            case "r12",  0b10001: return self.r12_fiq
            case "r12",  _:       return self.r12_usr
            case "r13",  0b10001: return self.r13_fiq
            case "r13",  0b10010: return self.r13_irq
            case "r13",  0b10011: return self.r13_svc
            case "r13",  0b10111: return self.r13_abt
            case "r13",  0b11011: return self.r13_und
            case "r13",  _:       return self.r13_usr
            case "r14",  0b10001: return self.r14_fiq
            case "r14",  0b10010: return self.r14_irq
            case "r14",  0b10011: return self.r14_svc
            case "r14",  0b10111: return self.r14_abt
            case "r14",  0b11011: return self.r14_und
            case "r14",  _:       return self.r14_usr
            case "spsr", 0b10001: return self.spsr_fiq
            case "spsr", 0b10010: return self.spsr_irq
            case "spsr", 0b10011: return self.spsr_svc
            case "spsr", 0b10111: return self.spsr_abt
            case "spsr", 0b11011: return self.spsr_und
            case "spsr", _:       raise AttributeError(f"mode {mode:#07b} has no SPSR")
            case _:               return self.__getattribute__(name)

    def __setattr__(self, name, value):
        try:
            mode = self.__getattribute__("cpsr") & 0x1f
        except AttributeError:
            mode = 0 # context is being constructed
        match name, mode:
            case "r8",   0b10001: self.r8_fiq   = int(value)
            case "r8",   _:       self.r8_usr   = int(value)
            case "r9",   0b10001: self.r9_fiq   = int(value)
            case "r9",   _:       self.r9_usr   = int(value)
            case "r10",  0b10001: self.r10_fiq  = int(value)
            case "r10",  _:       self.r10_usr  = int(value)
            case "r11",  0b10001: self.r11_fiq  = int(value)
            case "r11",  _:       self.r11_usr  = int(value)
            case "r12",  0b10001: self.r12_fiq  = int(value)
            case "r12",  _:       self.r12_usr  = int(value)
            case "r13",  0b10001: self.r13_fiq  = int(value)
            case "r13",  0b10010: self.r13_irq  = int(value)
            case "r13",  0b10011: self.r13_svc  = int(value)
            case "r13",  0b10111: self.r13_abt  = int(value)
            case "r13",  0b11011: self.r13_und  = int(value)
            case "r13",  _:       self.r13_usr  = int(value)
            case "r14",  0b10001: self.r14_fiq  = int(value)
            case "r14",  0b10010: self.r14_irq  = int(value)
            case "r14",  0b10011: self.r14_svc  = int(value)
            case "r14",  0b10111: self.r14_abt  = int(value)
            case "r14",  0b11011: self.r14_und  = int(value)
            case "r14",  _:       self.r14_usr  = int(value)
            case "spsr", 0b10001: self.spsr_fiq = int(value)
            case "spsr", 0b10010: self.spsr_irq = int(value)
            case "spsr", 0b10011: self.spsr_svc = int(value)
            case "spsr", 0b10111: self.spsr_abt = int(value)
            case "spsr", 0b11011: self.spsr_und = int(value)
            case "spsr", _:       raise AttributeError(f"mode {mode:#07b} has no SPSR")
            case _ if name in self.__annotations__:
                super().__setattr__(name, int(value))
            case _:
                raise AttributeError(f"{name!r} is not a valid register")

    def __str__(self):
        return "\n".join([
            f"       cpsr: {self.cpsr   :08x}",
            f"(usr)  r0:   {self.r0     :08x}  r1:   {self.r1     :08x} "
                  f" r2:   {self.r2     :08x}  r3:   {self.r3     :08x}",
            f"       r4:   {self.r4     :08x}  r5:   {self.r5     :08x} "
                  f" r6:   {self.r6     :08x}  r7:   {self.r7     :08x}",
            f"       r8:   {self.r8_usr :08x}  r9:   {self.r9_usr :08x} "
                  f" r10:  {self.r10_usr:08x}  r11:  {self.r11_usr:08x}",
            f"       r12:  {self.r12_usr:08x}  r13:  {self.r13_usr:08x} "
                  f" r14:  {self.r14_usr:08x}  r15:  {self.r15    :08x}",
            f"(fiq)  r8:   {self.r8_fiq :08x}  r9:   {self.r9_fiq :08x} "
                  f" r10:  {self.r10_fiq:08x}  r11:  {self.r11_fiq:08x}",
            f"       r12:  {self.r12_fiq:08x}  r13:  {self.r13_fiq:08x} "
                  f" r14:  {self.r14_fiq:08x}  spsr: {self.spsr_fiq:08x}",
            f"(irq)  r13:  {self.r13_irq:08x}  r14:  {self.r14_irq:08x}  spsr: {self.spsr_irq:08x}",
            f"(svc)  r13:  {self.r13_svc:08x}  r14:  {self.r14_svc:08x}  spsr: {self.spsr_svc:08x}",
            f"(abt)  r13:  {self.r13_abt:08x}  r14:  {self.r14_abt:08x}  spsr: {self.spsr_abt:08x}",
            f"(und)  r13:  {self.r13_und:08x}  r14:  {self.r14_und:08x}  spsr: {self.spsr_und:08x}",
        ])


class DebugARM7Interface(GDBRemote):
    class _BreakpointKind(enum.Enum):
        HARD_ARM   = 0
        HARD_THUMB = 1
        SOFT_ARM   = 2
        SOFT_THUMB = 3

        @property
        def is_soft(self):
            return self in (self.SOFT_ARM, self.SOFT_THUMB)

        @property
        def is_thumb(self):
            return self in (self.SOFT_THUMB, self.HARD_THUMB)


    def __init__(self, logger, assembly, *, tck, tms, tdo, tdi, trst=None, endian):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        ports = assembly.add_port_group(tck=tck, tms=tms, tdo=tdo, tdi=tdi, trst=trst)
        component = assembly.add_submodule(DebugARM7Sequencer(ports))
        self._pipe = assembly.add_inout_pipe(component.o_stream, component.i_stream,
            in_flush=component.o_flush)
        self._divisor = assembly.add_rw_register(component.divisor)
        self._sys_clk_period = assembly.sys_clk_period

        assert endian in ("big", "little")
        self._endian   = endian
        self._context  = None
        self._breakpts = {} # {(address, kind): saved_code}

    def _log(self, message, *args):
        self._logger.log(self._level, "ARM7: " + message, *args)

    async def get_tck_freq(self):
        divisor = await self._divisor
        return int(1 / (2 * (divisor + 1) * self._sys_clk_period))

    async def set_tck_freq(self, frequency):
        await self._divisor.set(
            max(int(1 / (2 * self._sys_clk_period * frequency) - 1), 0))

    async def _exec(self, buffer):
        self._log("  exec")
        await self._pipe.send(buffer)

    async def _read(self, count):
        await self._pipe.flush()
        words = array.array("I")
        words.frombytes(await self._pipe.recv(4 * count))
        if sys.byteorder == "big":
            words.byteswap()
        self._log("  read [%s]", dump_mapseq(", ", lambda value: f"{value:08x}", words))
        return words

    @contextlib.asynccontextmanager
    async def queue(self):
        self._log("  queue")
        yield (transaction := DebugARM7Transaction(self._logger))
        await self._exec(transaction._buffer)
        if transaction._to_read:
            transaction._results = await self._read(transaction._to_read)
        else:
            await self._pipe.flush(_wait=False)

    async def identify(self):
        async with self.queue() as txn:
            idcode = txn.identify()
        self._log("identify idcode=%08x", idcode)
        return DR_IDCODE.from_int(int(idcode))

    @property
    def _is_halted(self):
        return self._context is not None

    # Unlike all other functions in this file, this one can be cancelled without losing sync
    # with the gateware. This makes the implementation extremely complex.
    async def _debug_wait(self):
        self._log("debug wait")
        # first, make sure the command buffer is empty.
        await self._pipe.flush()
        # submit a cancellable wait; this is not a cancellation point due to the flush above.
        await self._exec([(DebugARM7Opcode.POLL_ACK.value << 5) | 1])
        # this command will always return a response; start a task to read it.
        result_task = asyncio.create_task(self._read(1))
        # the next try..finally statement is where cancellation is actually allowed to occur.
        try:
            # wait for a response, without letting the read task itself be cancelled.
            await asyncio.shield(result_task)
        except asyncio.CancelledError:
            # if *this* task was cancelled, send the cancel opcode to interrupt the gateware.
            self._log("  cancel")
            await self._pipe.send([DebugARM7Opcode.CANCEL.value << 5])
            await self._pipe.flush()
            # either way, wait for the result anyway. note that this function isn't safe to cancel
            # twice, which doesn't happen with GDBRemote but may happen otherwise. if the following
            # wait doesn't complete, the command/response stream could desynchronize.
            await asyncio.shield(result_task)
            # continue cancellation
            raise

    async def _debug_request(self, use_dbgrq=False):
        assert not self._is_halted
        if use_dbgrq:
            """Do not use. DBGRQ entry mode is broken due to errata and this function is present
            for testing purposes only."""
            self._log("debug request (dbgrq)")
            async with self.queue() as txn:
                txn.eice_set(EICE_Reg.DBGCTL, DBGRQ=1)
                txn.eice_poll()
        else:
            self._log("debug request (break)")
            async with self.queue() as txn:
                old_w0_ctrl_val = txn.eice_get(EICE_Reg.W0_CTRL_VAL)
                old_w0_ctrl_msk = txn.eice_get(EICE_Reg.W0_CTRL_MSK)
                old_w0_addr_msk = txn.eice_get(EICE_Reg.W0_ADDR_MSK)
                old_w0_data_msk = txn.eice_get(EICE_Reg.W0_DATA_MSK)
                txn.eice_set(EICE_Reg.W0_CTRL_VAL, 0) # disable first
                txn.eice_set(EICE_Reg.W0_ADDR_MSK, 0)
                txn.eice_set(EICE_Reg.W0_DATA_MSK, 0)
                txn.eice_set(EICE_Reg.W0_CTRL_MSK, PROT=0b01)
                txn.eice_set(EICE_Reg.W0_CTRL_VAL, PROT=0b00, ENABLE=1)
                txn.eice_poll()
            async with self.queue() as txn:
                txn.eice_set(EICE_Reg.W0_ADDR_MSK, old_w0_addr_msk)
                txn.eice_set(EICE_Reg.W0_DATA_MSK, old_w0_data_msk)
                txn.eice_set(EICE_Reg.W0_CTRL_MSK, old_w0_ctrl_msk)
                txn.eice_set(EICE_Reg.W0_CTRL_VAL, old_w0_ctrl_val)

    async def _debug_enter(self, is_dbgrq=False):
        assert not self._is_halted
        self._log("debug enter")
        async with self.queue() as txn:
            dbgsta = txn.eice_get(EICE_Reg.DBGSTA)
        if not dbgsta.DBGACK:
            raise DebugARM7Error("core failed to halt")
        async with self.queue() as txn:
            # set DBGACK to indicate to the rest of the system that we are in debug mode, and
            # disable interrupts to avoid system speed instructions entering a trap
            txn.eice_set(EICE_Reg.DBGCTL, DBGRQ=0, DBGACK=1, INTDIS=1)
            # get R0, R15, CPSR
            if dbgsta.TBIT:
                r0, r15 = txn.t_dbg_enter()
                r15_adj = 2 * 2 if is_dbgrq else 3 * 2
            else:
                r0, r15 = txn.a_dbg_enter()
                r15_adj = 2 * 4 if is_dbgrq else 3 * 4
            txn.a_mrs_cpsr(0)
            cpsr = txn.a_str(0) # with T bit cleared
            # get User/System mode registers
            txn.a_msr_cpsr_c(0xc0 | M_sys)
            regs_sys = txn.a_stm(0, 0x7ffe)
            # get FIQ mode registers
            txn.a_msr_cpsr_c(0xc0 | M_fiq)
            txn.a_mrs_spsr(1)
            regs_fiq = txn.a_stm(0, 0x7f02)
            # get IRQ mode registers
            txn.a_msr_cpsr_c(0xc0 | M_irq)
            txn.a_mrs_spsr(1)
            regs_irq = txn.a_stm(0, 0x6002)
            # get Supervisor mode registers
            txn.a_msr_cpsr_c(0xc0 | M_svc)
            txn.a_mrs_spsr(1)
            regs_svc = txn.a_stm(0, 0x6002)
            # get Abort mode registers
            txn.a_msr_cpsr_c(0xc0 | M_abt)
            txn.a_mrs_spsr(1)
            regs_abt = txn.a_stm(0, 0x6002)
            # get Undefined mode registers
            txn.a_msr_cpsr_c(0xc0 | M_und)
            txn.a_mrs_spsr(1)
            regs_und = txn.a_stm(0, 0x6002)
            # restore CPSR
            txn.a_msr_cpsr_fsxc(0)
        self._context = DebugARM7Context(
            int(cpsr) | (0x20 if dbgsta.TBIT else 0),
            int(r0), *map(int, regs_sys), int(r15 - r15_adj),
            *map(int, regs_fiq[1:]), int(regs_fiq[0]),
            *map(int, regs_irq[1:]), int(regs_irq[0]),
            *map(int, regs_svc[1:]), int(regs_svc[0]),
            *map(int, regs_abt[1:]), int(regs_abt[0]),
            *map(int, regs_und[1:]), int(regs_und[0]),
        )
        if self._logger.isEnabledFor(self._level):
            for line in str(self._context).splitlines():
                self._log("  %s", line)

    async def _debug_exit(self):
        assert self._is_halted
        self._log("debug exit")
        if self._logger.isEnabledFor(self._level):
            for line in str(self._context).splitlines():
                self._log("  %s", line)
        async with self.queue() as txn:
            ctx = self._context
            # set Undefined mode registers
            txn.a_msr_cpsr_c(0xc0 | M_und)
            txn.a_ldm(0, 0x6001, [ctx.spsr_und, ctx.r13_und, ctx.r14_und])
            txn.a_msr_spsr_fsxc(0)
            # set Abort mode registers
            txn.a_msr_cpsr_c(0xc0 | M_abt)
            txn.a_ldm(0, 0x6001, [ctx.spsr_abt, ctx.r13_abt, ctx.r14_abt])
            txn.a_msr_spsr_fsxc(0)
            # set Supervisor mode registers
            txn.a_msr_cpsr_c(0xc0 | M_svc)
            txn.a_ldm(0, 0x6001, [ctx.spsr_svc, ctx.r13_svc, ctx.r14_svc])
            txn.a_msr_spsr_fsxc(0)
            # set IRQ mode registers
            txn.a_msr_cpsr_c(0xc0 | M_irq)
            txn.a_ldm(0, 0x6001, [ctx.spsr_irq, ctx.r13_irq, ctx.r14_irq])
            txn.a_msr_spsr_fsxc(0)
            # set FIQ mode registers
            txn.a_msr_cpsr_c(0xc0 | M_fiq)
            txn.a_ldm(0, 0x7f01, [
                ctx.spsr_fiq, ctx.r8_fiq,  ctx.r9_fiq,  ctx.r10_fiq,
                ctx.r11_fiq,  ctx.r12_fiq, ctx.r13_fiq, ctx.r14_fiq
            ])
            txn.a_msr_spsr_fsxc(0)
            # set User/System mode registers
            txn.a_msr_cpsr_c(0xc0 | M_sys)
            txn.a_ldm(0, 0x7ffe, [
                ctx.r1,      ctx.r2,      ctx.r3,      ctx.r4,
                ctx.r5,      ctx.r6,      ctx.r7,      ctx.r8_usr,
                ctx.r9_usr,  ctx.r10_usr, ctx.r11_usr, ctx.r12_usr,
                ctx.r13_usr, ctx.r14_usr
            ])
            # set R0, R15, CPSR
            txn.a_ldr(0, ctx.cpsr & ~0x20) # mask off T bit
            txn.a_msr_cpsr_fsxc(0)
            if ctx.cpsr & 0x20:
                txn.t_dbg_exit(ctx.r0, ctx.r15)
            else:
                txn.a_dbg_exit(ctx.r0, ctx.r15)
            txn.eice_set(EICE_Reg.DBGCTL, 0)
        # It is possible that the core will re-enter debug mode immediately (on the very next
        # cycle), e.g. if a watchpoint triggers on the next instruction to execute. We cannot
        # distinguish between DBGACK set because the core re-entered debug mode due to such
        # a condition, and DBGACK set because the core failed to exit debug mode. Fortunately,
        # the latter should only happen due to silicon errata (which we have workarounds for)
        # and debug probe implementation errors.
        self._context = None

    async def _debug_resume(self):
        assert self._is_halted
        await self._apply_watchpts()
        await self._debug_exit()

    # Public API / GDB remote implementation

    def gdb_log(self, level, message, *args):
        self._logger.log(level, "GDB: " + message, *args)

    def target_word_size(self):
        return 4

    def target_endianness(self):
        return self._endian

    def target_triple(self):
        return "armv4t-none-eabi"

    def target_features(self) -> dict[str, bytes]:
        return {
            "target.xml": b"""
                <?xml version="1.0"?>
                <!DOCTYPE target SYSTEM "gdb-target.dtd">
                <target version="1.0">
                    <architecture>armv4t</architecture>
                    <feature name="org.gnu.gdb.arm.core">
                        <reg name="r0" bitsize="32" type="uint32"/>
                        <reg name="r1" bitsize="32" type="uint32"/>
                        <reg name="r2" bitsize="32" type="uint32"/>
                        <reg name="r3" bitsize="32" type="uint32"/>
                        <reg name="r4" bitsize="32" type="uint32"/>
                        <reg name="r5" bitsize="32" type="uint32"/>
                        <reg name="r6" bitsize="32" type="uint32"/>
                        <reg name="r7" bitsize="32" type="uint32"/>
                        <reg name="r8" bitsize="32" type="uint32"/>
                        <reg name="r9" bitsize="32" type="uint32"/>
                        <reg name="r10" bitsize="32" type="uint32"/>
                        <reg name="r11" bitsize="32" type="uint32"/>
                        <reg name="r12" bitsize="32" type="uint32"/>
                        <reg name="sp" bitsize="32" type="data_ptr"/>
                        <reg name="lr" bitsize="32"/>
                        <reg name="pc" bitsize="32" type="code_ptr"/>
                        <reg name="cpsr" bitsize="32"/>
                    </feature>
                </target>
            """.strip()
        }

    def target_running(self) -> bool:
        return not self._is_halted

    @property
    def target_context(self) -> DebugARM7Context | None:
        return self._context

    async def target_stop(self):
        assert not self._is_halted
        async with self.queue() as txn:
            txn.watchpt_clear(0) # clear watchpoints first to avoid a TOCTTOU race below
            txn.watchpt_clear(1)
            dbgsta = txn.eice_get(EICE_Reg.DBGSTA)
        if dbgsta.DBGACK: # core halted on breakpoint already?
            await self._debug_enter(is_dbgrq=False)
        else: # no, request core to halt
            use_dbgrq = False # see note in `_debug_request()`
            await self._debug_request(use_dbgrq=use_dbgrq)
            await self._debug_enter(is_dbgrq=use_dbgrq)

    async def target_continue(self):
        await asyncio.shield(self._debug_resume())
        await self._debug_wait()
        await asyncio.shield(self._debug_enter(is_dbgrq=False))

    async def target_single_step(self):
        assert self._is_halted
        # ARM7TDMI has an erratum which causes a watchpoint unit that signals a breakpoint on two
        # consecutive cycles to not flag the second cycle correctly. (ARM7TDMI-S Errata List §5.1)
        # To work around this, we first set up watchpoint unit 1 to trigger on the current PC,
        # and then set up watchpoint unit 0 to trigger on anything but current PC. This makes
        # consecutive single stepping work, but could still fail if unit 1 was used to enter
        # debug mode prior to this call to `.target_single_step()`.
        async with self.queue() as txn:
            txn.watchpt_clear(0)
            txn.watchpt_fetch_addr(1, self._context.r15, 2 if self._context.cpsr & 0x20 else 4)
        await self._debug_exit()
        async with self.queue() as txn:
            txn.eice_poll()
        await self._debug_enter()
        # Now that the erratum is taken care of (hopefully at least), the actual implementation
        # of single stepping follows.
        async with self.queue() as txn:
            txn.watchpt_step(self._context.r15, 2 if self._context.cpsr & 0x20 else 4)
        await self._debug_exit()
        async with self.queue() as txn:
            txn.eice_poll()
            txn.watchpt_clear(0)
        await self._debug_enter()

    async def target_detach(self):
        assert self._is_halted
        await self._clear_all_breakpts()
        await self._debug_resume()

    class GDBRegister(enum.IntEnum):
        # Upsettingly, GDB has no conception of banked registers on this target. However, it
        # does re-fetch every register after changing the mode bits in CPSR.
        r0  =  0; r1  =  1; r2  =  2; r3  =  3; r4  =  4; r5  =  5; r6  =  6; r7  =  7
        r8  =  8; r9  =  9; r10 = 10; r11 = 11; r12 = 12; r13 = 13; r14 = 14; r15 = 15
        cpsr = 16

    async def target_get_registers(self) -> list[int]:
        assert self._is_halted
        return [
            getattr(self._context, self.GDBRegister(number).name)
            for number in range(max(self.GDBRegister) + 1)
        ]

    async def target_set_registers(self, values: list[int]):
        assert self._is_halted
        for number, value in enumerate(values):
            setattr(self._context, self.GDBRegister(number).name, value)

    async def target_get_register(self, number: int) -> int:
        assert self._is_halted
        return getattr(self._context, self.GDBRegister(number).name)

    async def target_set_register(self, number: int, value: int):
        assert self._is_halted
        setattr(self._context, self.GDBRegister(number).name, value)

    async def target_read_memory(self, address: int, length: int) -> bytes:
        assert self._is_halted
        # GDB server protocol doesn't require any particular access size or alignment, and notes
        # that the `mM` packets aren't usable for MMIO. People almost certainly rely on this anyway
        # so we attempt to use a "reasonable" size and alignment for aligned 1/2/4 byte transfers.
        # This is evident in GDB e.g. using eight 1-wide transfers for `x/8b`.
        if length in (1, 2, 4) and address & (length - 1) == 0:
            async with self.queue() as txn:
                txn.a_ldr(0, address)                   # ldr  r0, <address>
                match length:
                    case 1: txn.a_ldrb_sys(1, 0)        # ldrb r1, [r0]
                    case 2: txn.a_ldrh_sys(1, 0)        # ldrh r1, [r0]
                    case 4: txn.a_ldm_sys(0, 0x2)       # ldm  r0, {r1}
                data = txn.a_str(1)                     # str  <data>, r1
            mask = (1 << (length * 8)) - 1
            if data & ~mask:
                # Byte and halfword loads from invalid addresses may return architecturally
                # impossible results (not properly zero-extended).
                self._logger.warning("read of size %d at %#010x returned illegal value %#010x",
                    length, address, data)
            return (data & mask).to_bytes(length, byteorder=self._endian)
        elif length > 0:
            head_bytes = 4 - (address & 0x3) if address & 0x3 else 0
            tail_bytes = (length - head_bytes) & 0x3
            mid_words  = (length - head_bytes - tail_bytes) // 4
            async with self.queue() as txn:
                txn.a_ldr(0, address)                   # ldr  r0, <address>
                if head_bytes > 0:
                    with txn.repeat(head_bytes):
                        txn.a_ldrb_sys(1, 0, 1)         # ldrb r1, [r0], #1
                        txn.a_str(1)                    # str  <data>, r1
                if mid_words > 14:
                    with txn.repeat(mid_words // 14):
                        txn.a_ldm_sys(0, 0x7ffe, w=1)   # ldm  r0!, {r1-r14}
                        txn.a_stm(0, 0x7ffe)            # stm  <data>, {r1-r14}
                if mid_words > 0:
                    with txn.repeat(mid_words % 14):
                        txn.a_ldm_sys(0, 0x2, w=1)      # ldm  r0!, {r1}
                        txn.a_str(1)                    # str  <data>, r1
                if tail_bytes > 0:
                    with txn.repeat(tail_bytes):
                        txn.a_ldrb_sys(1, 0, 1)         # ldrb r1, [r0], #1
                        txn.a_str(1)                    # str  <data>, r1
            # See comment above re: byte loads.
            head_data = bytes([byte & 0xff for byte in txn.results[:head_bytes]])
            tail_data = bytes([byte & 0xff for byte in txn.results[head_bytes+mid_words:]])
            if self._endian != sys.byteorder:
                txn.results.byteswap()
            mid_data  = bytes(txn.results[head_bytes:head_bytes+mid_words])
            return head_data + mid_data + tail_data
        else:
            return bytes()

    async def target_write_memory(self, address: int, data: bytes):
        assert self._is_halted
        # See comment in `target_read_memory()`.
        if len(data) in (1, 2, 4) and address & (len(data) - 1) == 0:
            word = int.from_bytes(data, byteorder=self._endian)
            async with self.queue() as txn:
                txn.a_ldr(0, address)                   # ldr  r0, <address>
                txn.a_ldr(1, word)                      # ldr  r1, <word>
                match len(data):
                    case 1: txn.a_strb_sys(1, 0)        # strb r1, [r0]
                    case 2: txn.a_strh_sys(1, 0)        # strh r1, [r0]
                    case 4: txn.a_stm_sys(0, 0x2)       # stm  r0, {r1}
        else:
            head_bytes = 4 - (address & 0x3) if address & 0x3 else 0
            tail_bytes = (len(data) - head_bytes) & 0x3
            mid_bytes  = (len(data) - head_bytes - tail_bytes)
            head_data  = data[:head_bytes]
            tail_data  = data[head_bytes+mid_bytes:]
            mid_words   = array.array("I")
            mid_words.frombytes(data[head_bytes:head_bytes+mid_bytes])
            if self._endian != sys.byteorder:
                mid_words.byteswap()
            async with self.queue() as txn:
                txn.a_ldr(0, address)                   # ldr  r0, <address>
                for byte in head_data:
                    txn.a_ldr(1, byte)                  # ldr  r1, <byte>
                    txn.a_strb_sys(1, 0, 1)             # strb r1, [r0], #1
                index = 0
                while index + 14 < len(mid_words):
                    chunk = mid_words[index:index + 14]
                    txn.a_ldm(0, 0x7ffe, chunk)         # ldm  <chunk>, {r1-r14}
                    txn.a_stm_sys(0, 0x7ffe, w=1)       # stm  r0!, {r1-r14}
                    index += 14
                while index < len(mid_words):
                    txn.a_ldr(1, mid_words[index])      # ldr  r1, <word>
                    txn.a_stm_sys(0, 0x2, w=1)          # stm  r0!, {r1}
                    index += 1
                for byte in tail_data:
                    txn.a_ldr(1, byte)                  # ldr  r1, <byte>
                    txn.a_strb_sys(1, 0, 1)             # strb r1, [r0], #1

    @staticmethod
    def _collect_watchpts(breakpts):
        watchpts = set()
        for breakpt_address, breakpt_kind in breakpts:
            if breakpt_kind.is_soft:
                watchpts.add((breakpt_kind, None))
            else:
                watchpts.add((breakpt_kind, breakpt_address))
        return watchpts

    async def _apply_watchpts(self):
        async with self.queue() as txn:
            for unit in range(2):
                txn.watchpt_clear(unit)
            for unit, watchpt in enumerate(self._collect_watchpts(self._breakpts)):
                match watchpt:
                    case (self._BreakpointKind.HARD_ARM, address):
                        txn.watchpt_fetch_addr(unit, address, 4)
                    case (self._BreakpointKind.HARD_THUMB, address):
                        txn.watchpt_fetch_addr(unit, address, 2)
                    case (self._BreakpointKind.SOFT_ARM, None):
                        txn.watchpt_fetch_data(unit, A_BKPT(0), 4)
                    case (self._BreakpointKind.SOFT_THUMB, None):
                        txn.watchpt_fetch_data(unit, T_BKPT(0), 2)

    async def _replace_code(self, address: int, code: bytes, action: str) -> bool:
        await self.target_write_memory(address, code)
        actual_code = await self.target_read_memory(address, len(code))
        if actual_code != code:
            self._logger.error("failed to %s breakpoint at %#010x: written <%s>, read <%s>",
                action, address, code.hex(), actual_code.hex())
            return False
        return True

    async def _set_breakpt(self, address: int, kind: _BreakpointKind):
        assert self._is_halted
        self._log("breakpoint set at=%08x kind=%s", address, kind.name)
        if (address, kind) in self._breakpts:
            return # already set, nothing to do
        new_watchpts = self._collect_watchpts({*self._breakpts, (address, kind)})
        if len(new_watchpts) > 2:
            raise GDBRemoteError(f"cannot set a {kind.name} breakpoint: out of watchpoint units")
        if kind.is_soft:
            if kind.is_thumb:
                breakpt_save = await self.target_read_memory(address, 2)
                await self._replace_code(address, T_BKPT(0).to_bytes(2, self._endian), action="set")
            else:
                breakpt_save = await self.target_read_memory(address, 4)
                await self._replace_code(address, A_BKPT(0).to_bytes(4, self._endian), action="set")
        else:
            breakpt_save = None
        self._breakpts[address, kind] = breakpt_save

    async def _clear_breakpt(self, address: int, kind: _BreakpointKind):
        assert self._is_halted
        self._log("breakpoint clear at=%08x kind=%s", address, kind.name)
        for (breakpt_address, breakpt_kind), breakpt_save in self._breakpts.items():
            if (breakpt_address, breakpt_kind) == (address, kind):
                break
        else:
            raise GDBRemoteError(f"cannot clear a {kind.name} breakpoint at {address:#010x}: "
                                 f"breakpoint does not exist")
        if breakpt_kind.is_soft:
            await self._replace_code(breakpt_address, breakpt_save, action="clear")
        del self._breakpts[(breakpt_address, breakpt_kind)]

    async def _clear_all_breakpts(self):
        assert self._is_halted
        self._log("breakpoint clear all")
        for (breakpt_address, breakpt_kind), breakpt_save in self._breakpts.items():
            if breakpt_kind.is_soft:
                await self._replace_code(breakpt_address, breakpt_save, action="clear")
        self._breakpts.clear()

    async def target_set_software_breakpt(self, address: int, kind: int):
        match kind:
            case 4: await self._set_breakpt(address, self._BreakpointKind.SOFT_ARM)
            case 2: await self._set_breakpt(address, self._BreakpointKind.SOFT_THUMB)
            case _: raise NotImplementedError(f"unsupported breakpoint kind {kind}")

    async def target_clear_software_breakpt(self, address: int, kind: int):
        match kind:
            case 4: await self._clear_breakpt(address, self._BreakpointKind.SOFT_ARM)
            case 2: await self._clear_breakpt(address, self._BreakpointKind.SOFT_THUMB)
            case _: raise NotImplementedError(f"unsupported breakpoint kind {kind}")

    async def target_set_instr_breakpt(self, address: int, kind: int):
        match kind:
            case 4: await self._set_breakpt(address, self._BreakpointKind.HARD_ARM)
            case 2: await self._set_breakpt(address, self._BreakpointKind.HARD_THUMB)
            case _: raise NotImplementedError(f"unsupported breakpoint kind {kind}")

    async def target_clear_instr_breakpt(self, address: int, kind: int):
        match kind:
            case 4: await self._clear_breakpt(address, self._BreakpointKind.HARD_ARM)
            case 2: await self._clear_breakpt(address, self._BreakpointKind.HARD_THUMB)
            case _: raise NotImplementedError(f"unsupported breakpoint kind {kind}")


class DebugARM7Applet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "debug ARM7TDMI processors via JTAG"
    description = """
    Debug ARM7TDMI processors via the JTAG interface.

    This applet supports displaying CPU state, dumping a memory region, and running a GDB remote
    protocol server for a debugger. All debugger features are implemented except for memory
    watchpoints. (This processor has errata that makes watchpoints essentially unusable, as well
    as impacting breakpoints.)

    The applet should work on all big-endian and little-endian ARM7TDMI CPUs, and has been tested
    on a big-endian SoC (Yamaha SWLL).

    The CPU must be the only TAP in the JTAG chain.
    """
    required_revision = "C0"

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "tck", default=True)
        access.add_pins_argument(parser, "tms", default=True)
        access.add_pins_argument(parser, "tdo", default=True)
        access.add_pins_argument(parser, "tdi", default=True)
        access.add_pins_argument(parser, "trst")
        parser.add_argument(
            "-e", "--endian", metavar="ENDIAN", choices=("big", "little"), default="little",
            help="target endianness (default: %(default)s)")

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.arm_iface = DebugARM7Interface(self.logger, self.assembly,
                tck =args.tck,
                tms =args.tms,
                tdo =args.tdo,
                tdi =args.tdi,
                trst=args.trst,
                endian=args.endian)

    @classmethod
    def add_setup_arguments(cls, parser):
        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=1000,
            help="set TCK frequency to FREQ kHz (default: %(default)s)")

    async def setup(self, args):
        await self.arm_iface.set_tck_freq(args.frequency * 1000)

        idcode = await self.arm_iface.identify()
        self.logger.info("detected TAP with IDCODE=%08x", idcode.to_int())
        mfg_name = jedec_mfg_name_from_bank_num(idcode.mfg_id >> 7, idcode.mfg_id & 0x7f)
        self.logger.info("manufacturer=%#05x (%s) part=%#06x version=%#03x",
            idcode.mfg_id, mfg_name or "unknown", idcode.part_id, idcode.version)

    @classmethod
    def add_run_arguments(cls, parser):
        def address(arg):
            return int(arg, 0)
        def length(arg):
            return int(arg, 0)

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

        p_dump_state = p_operation.add_parser(
            "dump-state", help="dump CPU state")

        p_dump_memory = p_operation.add_parser(
            "dump-memory", help="dump memory range")
        p_dump_memory.add_argument(
            "address", metavar="ADDRESS", type=address,
            help="start at ADDRESS")
        p_dump_memory.add_argument(
            "length", metavar="LENGTH", type=length,
            help="dump LENGTH bytes")
        p_dump_memory.add_argument(
            "-f", "--file", metavar="FILENAME", type=argparse.FileType("wb"),
            help="dump contents to FILENAME")

        p_gdb = p_operation.add_parser(
            "gdb", help="start a GDB remote protocol server")
        ServerEndpoint.add_argument(p_gdb, "gdb_endpoint", default="tcp::1234")

    async def run(self, args):
        match args.operation:
            case "dump-state":
                await self.arm_iface.target_stop()
                print(self.arm_iface.target_context)
                await self.arm_iface.target_detach()

            case "dump-memory":
                await self.arm_iface.target_stop()
                data = await self.arm_iface.target_read_memory(args.address, args.length)
                await self.arm_iface.target_detach()
                if args.file:
                    args.file.write(data)
                else:
                    print(data.hex())

            case "gdb":
                endpoint = await ServerEndpoint("GDB socket", self.logger, args.gdb_endpoint)
                while True:
                    await self.arm_iface.gdb_run(endpoint)
                    if not self.arm_iface.target_running():
                        await self.arm_iface.target_detach()

    async def repl(self, args):
        await super().repl(args)

        if not self.arm_iface.target_running():
            await self.arm_iface.target_detach()

    @classmethod
    def tests(cls):
        from . import test
        return test.DebugARM7AppletTestCase
