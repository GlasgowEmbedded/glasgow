from migen import *
from migen.fhdl.bitcontainer import value_bits_sign
from migen.fhdl.specials import _MemoryPort
from migen.genlib.fsm import *

from ..arch.boneless.opcode import *


__all__ = ["BonelessCore"]


def SignExtend(v, w):
    v_nbits, v_sign = value_bits_sign(v)
    if v_nbits > w.nbits:
        return v
    else:
        return Cat(v, Replicate(v[v_nbits - 1], w.nbits - v_nbits))


class BonelessCore(Module):
    def __init__(self, reset_addr, mem_port, ext_port=None, simulation=False):
        if ext_port is None:
            ext_port = _MemoryPort(adr=Signal(16),
                dat_r=Signal(16), re=Signal(),
                dat_w=Signal(16), we=Signal())

        r_insn  = Signal(16)
        r_pc    = Signal(mem_port.adr.nbits, reset=reset_addr)
        r_win   = Signal(max(mem_port.adr.nbits - 3, 1))
        r_z     = Signal()
        r_s     = Signal()
        r_c     = Signal()
        r_o     = Signal()

        r_opA   = Signal(16)
        s_opB   = Signal(16)

        r_opS   = Signal(16)
        r_shift = Signal(5)

        s_res   = Signal(17)

        s_insn  = Signal(16)
        i_type1 = s_insn[0:1]
        i_type2 = s_insn[0:2]
        i_shift = s_insn[1:5]
        i_imm5  = s_insn[0:5]
        i_imm7  = s_insn[0:8]
        i_imm11 = s_insn[0:11]
        i_regX  = s_insn[2:5]
        i_regY  = s_insn[5:8]
        i_regZ  = s_insn[8:11]
        i_code1 = s_insn[11:12]
        i_code2 = s_insn[11:13]
        i_code3 = s_insn[11:14]
        i_code5 = s_insn[11:16]
        i_flag  = s_insn[11]
        i_cond  = s_insn[12:15]

        i_clsA  = i_code5[1:5] == OPCLASS_A
        i_clsS  = i_code5[1:5] == OPCLASS_S
        i_clsM  = i_code5[2:5] == OPCLASS_M
        i_clsI  = i_code5[3:5] == OPCLASS_I
        i_clsC  = i_code5[4:5] == OPCLASS_C

        s_cond  = Signal()
        self.comb += [
            Case(Cat(i_cond, C(1, 1)), {
                OPCODE_F_0:     s_cond.eq(0),
                OPCODE_F_Z:     s_cond.eq(r_z),
                OPCODE_F_S:     s_cond.eq(r_s),
                OPCODE_F_O:     s_cond.eq(r_o),
                OPCODE_F_C:     s_cond.eq(r_c),
                OPCODE_F_CoZ:   s_cond.eq(r_c | r_o),
                OPCODE_F_SxO:   s_cond.eq(r_s ^ r_o),
                OPCODE_F_SxOoZ: s_cond.eq((r_s ^ r_o) | r_z),
            })
        ]

        s_sub   = Signal()
        s_cmp   = Signal()
        c_flags = Signal()
        self.sync += [
            If(c_flags,
                r_z.eq(s_res == 0),
                r_s.eq(s_res[15]),
                r_c.eq(s_res[16]),
                # http://teaching.idallen.com/cst8214/08w/notes/overflow.txt
                Case(Cat(s_sub | s_cmp, r_opA[15], s_opB[15], s_res[15]), {
                    0b0001: r_o.eq(1),
                    0b0110: r_o.eq(1),
                    0b1011: r_o.eq(1),
                    0b1100: r_o.eq(1),
                    "default": r_o.eq(0),
                })
            )
        ]

        self.submodules.fsm = FSM(reset_state="FETCH")
        self.comb += [
            s_insn.eq(Mux(self.fsm.ongoing("LOAD/JUMP"), mem_port.dat_r, r_insn))
        ]
        self.fsm.act("FETCH",
            mem_port.adr.eq(r_pc),
            mem_port.re.eq(1),
            NextValue(r_pc, r_pc + 1),
            NextState("LOAD/JUMP")
        )
        self.fsm.act("LOAD/JUMP",
            NextValue(r_insn, mem_port.dat_r),
            If(i_clsA,
                mem_port.adr.eq(Cat(i_regX, r_win)),
                mem_port.re.eq(1),
                NextState("LOAD-A")
            ).Elif(i_clsS,
                mem_port.adr.eq(Cat(i_regY, r_win)),
                mem_port.re.eq(1),
                NextState("LOAD-S")
            # ).Elif(i_clsM,
            #     mem_port.adr.eq(Cat(i_regY, r_win)),
            #     mem_port.re.eq(1),
            #     NextState("?-M")
            # ).Elif(i_clsI,
            #     mem_port.adr.eq(Cat(i_regZ, r_win)),
            #     mem_port.re.eq(1),
            #     NextState("?-I")
            ).Elif(i_clsC,
                If(s_cond == i_flag,
                    NextValue(r_pc, r_pc + SignExtend(i_imm11, r_pc))
                ),
                NextState("FETCH"),
                If(simulation & (i_imm11 == 0x400),
                    NextState("HALT")
                )
            )
        )
        self.fsm.act("LOAD-A",
            mem_port.adr.eq(Cat(i_regY, r_win)),
            mem_port.re.eq(1),
            NextValue(r_opA, mem_port.dat_r),
            NextState("EXECUTE-A")
        )
        self.fsm.act("EXECUTE-A",
            s_opB.eq(mem_port.dat_r),
            Case(Cat(i_code1, C(OPCLASS_A, 4)), {
                OPCODE_LOGIC: Case(i_type2, {
                    OPTYPE_AND:  s_res.eq(r_opA & s_opB),
                    OPTYPE_OR:   s_res.eq(r_opA | s_opB),
                    OPTYPE_XOR:  s_res.eq(r_opA ^ s_opB),
                }),
                OPCODE_ARITH: Case(i_type2, {
                    OPTYPE_ADD:  s_res.eq(r_opA + s_opB),
                    OPTYPE_SUB: [s_res.eq(r_opA - s_opB), s_sub.eq(1)],
                    OPTYPE_CMP: [s_res.eq(r_opA - s_opB), s_cmp.eq(1)],
                })
            }),
            mem_port.adr.eq(Cat(i_regZ, r_win)),
            mem_port.dat_w.eq(s_res),
            mem_port.we.eq(~s_cmp),
            c_flags.eq(1),
            NextState("FETCH")
        )
        self.fsm.act("LOAD-S",
            NextValue(r_opS, mem_port.dat_r),
            NextValue(r_shift, i_shift),
            NextState("EXECUTE-S")
        )
        self.fsm.act("EXECUTE-S",
            s_res.eq(r_opS),
            mem_port.adr.eq(Cat(i_regZ, r_win)),
            mem_port.dat_w.eq(s_res),
            mem_port.we.eq(1),
            c_flags.eq(1),
            Case(Cat(i_code1, C(OPCLASS_S, 4)), {
                OPCODE_SHIFT_L: Case(i_type1, {
                    OPTYPE_SLL: NextValue(r_opS, Cat(C(0, 1),   r_opS[:-1])),
                    OPTYPE_ROT: NextValue(r_opS, Cat(r_opS[-1], r_opS[:-1])),
                }),
                OPCODE_SHIFT_R: Case(i_type1, {
                    OPTYPE_SRL: NextValue(r_opS, Cat(r_opS[1:], C(0, 1))),
                    OPTYPE_SRA: NextValue(r_opS, Cat(r_opS[1:], r_opS[-1])),
                })
            }),
            NextValue(r_shift, r_shift - 1),
            If(r_shift == 0,
                NextState("FETCH")
            )
        )
        self.fsm.act("HALT",
            NextState("HALT")
        )

# -------------------------------------------------------------------------------------------------

import unittest

from . import simulation_test
from ..arch.boneless.instr import *


class BonelessTestbench(Module):
    def __init__(self):
        self.mem_init = []

    def do_finalize(self):
        self.mem = Memory(width=16, depth=len(self.mem_init), init=self.mem_init)
        self.specials += self.mem

        mem_port = self.mem.get_port(has_re=True, write_capable=True)
        self.specials += mem_port

        self.submodules.dut = BonelessCore(reset_addr=8, mem_port=mem_port, simulation=True)


class BonelessTestCase(unittest.TestCase):
    def setUp(self):
        self.tb = BonelessTestbench()

    def configure(self, tb, regs, code):
        tb.mem_init = [*regs, *[0] * (8 - len(regs))] + assemble(code + [J(-1024)])

    def dut_state(self, tb):
        return tb.dut.fsm.decoding[(yield tb.dut.fsm.state)]

    def run_core(self, tb):
        while (yield from self.dut_state(tb)) != "HALT":
            yield

    def assertMemory(self, tb, addr, value):
        self.assertEqual((yield tb.mem[addr]), value)

    @simulation_test(regs=[0xA5A5, 0xAA55],
                     code=[AND (R2, R1, R0)])
    def test_AND(self, tb):
        yield from self.run_core(tb)
        yield from self.assertMemory(tb, 0, 0xA5A5)
        yield from self.assertMemory(tb, 1, 0xAA55)
        yield from self.assertMemory(tb, 2, 0xA005)

    @simulation_test(regs=[0xA5A5, 0xAA55],
                     code=[OR  (R2, R1, R0)])
    def test_OR(self, tb):
        yield from self.run_core(tb)
        yield from self.assertMemory(tb, 0, 0xA5A5)
        yield from self.assertMemory(tb, 1, 0xAA55)
        yield from self.assertMemory(tb, 2, 0xAFF5)

    @simulation_test(regs=[0xA5A5, 0xAA55],
                     code=[XOR (R2, R1, R0)])
    def test_XOR(self, tb):
        yield from self.run_core(tb)
        yield from self.assertMemory(tb, 0, 0xA5A5)
        yield from self.assertMemory(tb, 1, 0xAA55)
        yield from self.assertMemory(tb, 2, 0x0FF0)

    @simulation_test(regs=[0x1234, 0x5678],
                     code=[ADD (R2, R1, R0)])
    def test_ADD(self, tb):
        yield from self.run_core(tb)
        yield from self.assertMemory(tb, 0, 0x1234)
        yield from self.assertMemory(tb, 1, 0x5678)
        yield from self.assertMemory(tb, 2, 0x68AC)

    @simulation_test(regs=[0x1234, 0x5678],
                     code=[SUB (R2, R1, R0)])
    def test_SUB(self, tb):
        yield from self.run_core(tb)
        yield from self.assertMemory(tb, 0, 0x1234)
        yield from self.assertMemory(tb, 1, 0x5678)
        yield from self.assertMemory(tb, 2, 0xBBBC)

    @simulation_test(regs=[0x1234, 0x5678],
                     code=[CMP (R0, R1)])
    def test_CMP(self, tb):
        yield from self.run_core(tb)
        yield from self.assertMemory(tb, 0, 0x1234)
        yield from self.assertMemory(tb, 1, 0x5678)
        yield from self.assertMemory(tb, 2, 0)

    @simulation_test(regs=[0x1012],
                     code=[SLL (R1, R0, 1),
                           SLL (R2, R0, 8)])
    def test_SLL(self, tb):
        yield from self.run_core(tb)
        yield from self.assertMemory(tb, 0, 0x1012)
        yield from self.assertMemory(tb, 1, 0x2024)
        yield from self.assertMemory(tb, 2, 0x1200)

    @simulation_test(regs=[0x1012],
                     code=[ROT (R1, R0, 1),
                           ROT (R2, R0, 8)])
    def test_ROT(self, tb):
        yield from self.run_core(tb)
        yield from self.assertMemory(tb, 0, 0x1012)
        yield from self.assertMemory(tb, 1, 0x2024)
        yield from self.assertMemory(tb, 2, 0x1210)

    @simulation_test(regs=[0x1234],
                     code=[MOV (R1, R0)])
    def test_MOV(self, tb):
        yield from self.run_core(tb)
        yield from self.assertMemory(tb, 0, 0x1234)
        yield from self.assertMemory(tb, 1, 0x1234)

    @simulation_test(regs=[0x1210, 0x9210],
                     code=[SRL (R2, R0, 1),
                           SRL (R3, R0, 8),
                           SRL (R4, R1, 1),
                           SRL (R5, R1, 8)])
    def test_SRL(self, tb):
        yield from self.run_core(tb)
        yield from self.assertMemory(tb, 0, 0x1210)
        yield from self.assertMemory(tb, 2, 0x0908)
        yield from self.assertMemory(tb, 3, 0x0012)
        yield from self.assertMemory(tb, 1, 0x9210)
        yield from self.assertMemory(tb, 4, 0x4908)
        yield from self.assertMemory(tb, 5, 0x0092)

    @simulation_test(regs=[0x1210, 0x9210],
                     code=[SRA (R2, R0, 1),
                           SRA (R3, R0, 8),
                           SRA (R4, R1, 1),
                           SRA (R5, R1, 8)])
    def test_SRA(self, tb):
        yield from self.run_core(tb)
        yield from self.assertMemory(tb, 0, 0x1210)
        yield from self.assertMemory(tb, 2, 0x0908)
        yield from self.assertMemory(tb, 3, 0x0012)
        yield from self.assertMemory(tb, 1, 0x9210)
        yield from self.assertMemory(tb, 4, 0xC908)
        yield from self.assertMemory(tb, 5, 0xFF92)
