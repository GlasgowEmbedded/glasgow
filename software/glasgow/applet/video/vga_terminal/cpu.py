# Encoding the entire DEC VT10x state machine in gateware is possible, but our FPGA isn't very
# large and is not fast at all. So, instead of doing that, we define a boneless CPU architecture
# and use that to control the terminal.
#
# Architecture description:
#   * Four explicit 16-bit registers, A, B, C, and P.
#   * One implicit register, PC.
#   * All jumps are relative.
#   * Character and attribute memory indexed by P.
#
# Instruction set:
#   * NOP            ≡  ø
#   * LDI  imm       ≡  A ← signext(imm)
#   * LDIH imm       ≡  A[8:16] ← imm
#   * LDB            ≡  A ← B
#   * LDC            ≡  A ← C
#   * LDP            ≡  A ← P
#   * STB            ≡  B ← A
#   * STC            ≡  C ← A
#   * STP            ≡  P ← A
#   * LDMC           ≡  A[0:8]  ← char[P]
#   * LDMA           ≡  A[8:16] ← attr[P]
#   * STMC           ≡  char[P] ← A[0:8]
#   * STMA           ≡  attr[P] ← A[8:16]
#   * LDF            ≡  wait(FIFO); A ← signext(FIFO)
#   * INV            ≡  A ← ~A
#   * ADDI imm       ≡  A ← A + signext(imm)
#   * ADDB           ≡  A ← A + B
#   * ADJ            ≡  P ← P + signext(imm)
#   * J    off       ≡  PC ← PC + signext(off)
#   * JE   off, imm  ≡  if(A = signext(imm)) PC ← PC + signext(off)
#   * JL   off, imm  ≡  if(A < signext(imm)) PC ← PC + signext(off)
#   * JN   off       ≡  if(A < 0) PC ← PC + signext(off)
#   * HLT            ≡  halt

from nmigen.compat import *


__all__ = [
    "BonelessCPU",
    "L",
    "LDI", "LDIH", "LDIW",
    "LDB", "LDC", "LDP", "LDMC", "LDMA",
    "STB", "STC", "STP", "STMC", "STMA",
    "LDF",
    "INV", "ADDI", "ADDB", "NEG", "ADJ",
    "J", "JE", "JL", "JN",
    "NOP", "HLT"
]


INSTR_NOP  = 0b0000_0000
INSTR_LDI  = 0b0000_0001
INSTR_LDIH = 0b0000_0010
INSTR_LDB  = 0b0001_0000
INSTR_LDC  = 0b0001_0001
INSTR_LDP  = 0b0001_0010
INSTR_STB  = 0b0001_1000
INSTR_STC  = 0b0001_1001
INSTR_STP  = 0b0001_1010
INSTR_LDMC = 0b0010_0000
INSTR_LDMA = 0b0010_0001
INSTR_STMC = 0b0010_1000
INSTR_STMA = 0b0010_1001
INSTR_LDF  = 0b0011_0000
INSTR_INV  = 0b0100_0000
INSTR_ADDI = 0b0100_0001
INSTR_ADDB = 0b0100_0010
INSTR_ADJ  = 0b0100_0011
INSTR_J    = 0b1000_0000
INSTR_JE   = 0b1000_0001
INSTR_JL   = 0b1000_0010
INSTR_JN   = 0b1000_0011
INSTR_HLT  = 0b1000_1111


def L(lbl):         return lbl
def NOP():          return [INSTR_NOP]
def LDI(imm):       return [INSTR_LDI,  imm & 0xff]
def LDIH(imm):      return [INSTR_LDIH, imm & 0xff]
def LDIW(imm16):    return LDI(imm16) + LDIH(imm16 >> 8)
def LDB():          return [INSTR_LDB]
def LDC():          return [INSTR_LDC]
def LDP():          return [INSTR_LDP]
def STB():          return [INSTR_STB]
def STC():          return [INSTR_STC]
def STP():          return [INSTR_STP]
def LDMC():         return [INSTR_LDMC]
def LDMA():         return [INSTR_LDMA]
def STMC():         return [INSTR_STMC]
def STMA():         return [INSTR_STMA]
def LDF():          return [INSTR_LDF]
def INV():          return [INSTR_INV]
def ADDI(imm):      return [INSTR_ADDI, imm & 0xff]
def ADDB():         return [INSTR_ADDB]
def ADJ(imm):       return [INSTR_ADJ,  imm & 0xff]
def NEG():          return INV() + ADDI(1)
def J(lbl):         return [INSTR_J,                lbl]
def JE(imm, lbl):   return [INSTR_JE,   imm & 0xff, lbl]
def JL(imm, lbl):   return [INSTR_JL,   imm & 0xff, lbl]
def JN(lbl):        return [INSTR_JN,               lbl]
def HLT():          return [INSTR_HLT]


class BonelessCPU(Module):
    @staticmethod
    def resolve_labels(code):
        flat_code = []
        labels    = {}
        for elem in code:
            if isinstance(elem, str):
                assert elem not in labels
                labels[elem] = len(flat_code)
            else:
                flat_code += elem
        for offset, elem in enumerate(flat_code):
            if isinstance(elem, str):
                rel_offset = labels[elem] - offset - 1
                assert -128 <= rel_offset <= 127
                flat_code[offset] = rel_offset & 0xff
        return flat_code

    def __init__(self, char_mem, attr_mem, code_init, out_fifo):
        code_init = self.resolve_labels(code_init)
        print(bytes(code_init).hex())

        char_port = char_mem.get_port(has_re=True, write_capable=True)
        attr_port = attr_mem.get_port(has_re=True, write_capable=True)
        self.specials += [char_port, attr_port]

        code_mem = Memory(width=8, depth=len(code_init), init=code_init)
        self.specials += code_mem

        code_port = code_mem.get_port(has_re=True)
        self.specials += code_port
        self.comb += code_port.re.eq(1)

        c_adr = code_port.adr
        c_dat = code_port.dat_r

        r_pc  = Signal(max=code_mem.depth)
        r_a   = Signal(16)
        r_b   = Signal(16)
        r_c   = Signal(16)
        r_p   = Signal(16)
        self.comb += [
            char_port.adr.eq(r_p),
            char_port.re.eq(1),
            char_port.dat_w.eq(r_a[0:8]),
            attr_port.adr.eq(r_p),
            attr_port.re.eq(1),
            attr_port.dat_w.eq(r_a[8:16]),
        ]

        def signext(v, w=16): return Cat(v, Replicate(v[v.nbits - 1], w - v.nbits))

        self.submodules.fsm = FSM()
        self.fsm.act("FETCH",
            c_adr.eq(r_pc),
            NextValue(r_pc, r_pc + 1),
            NextState("EXECUTE")
        )
        self.fsm.act("EXECUTE",
            c_adr.eq(r_pc),
            NextState("FETCH"),
            Case(c_dat, {
                INSTR_LDI:  [
                    NextValue(r_pc, r_pc + 1),
                    NextState("EXECUTE-LDI")
                ],
                INSTR_LDIH: [
                    NextValue(r_pc, r_pc + 1),
                    NextState("EXECUTE-LDIH")
                ],
                INSTR_LDB:  NextValue(r_a, r_b),
                INSTR_LDC:  NextValue(r_a, r_c),
                INSTR_LDP:  NextValue(r_a, r_p),
                INSTR_STB:  NextValue(r_b, r_a),
                INSTR_STC:  NextValue(r_c, r_a),
                INSTR_STP:  NextValue(r_p, r_a),
                INSTR_LDMC: NextValue(r_a[0:8],  char_port.dat_r),
                INSTR_LDMA: NextValue(r_a[8:16], attr_port.dat_r),
                INSTR_STMC: char_port.we.eq(1),
                INSTR_STMA: attr_port.we.eq(1),
                INSTR_LDF:  NextState("EXECUTE-LDF"),
                INSTR_INV:  NextValue(r_a, ~r_a),
                INSTR_ADDI: [
                    NextValue(r_pc, r_pc + 1),
                    NextState("EXECUTE-ADDI")
                ],
                INSTR_ADDB: NextValue(r_a, r_a + r_b),
                INSTR_ADJ:  [
                    NextValue(r_pc, r_pc + 1),
                    NextState("EXECUTE-ADJ")
                ],
                INSTR_HLT:  NextState("EXECUTE-HLT"),
                INSTR_J: [
                    NextValue(r_pc, r_pc + 1),
                    NextState("EXECUTE-J")
                ],
                INSTR_JE: [
                    NextValue(r_pc, r_pc + 1),
                    NextState("EXECUTE-JE")
                ],
                INSTR_JL: [
                    NextValue(r_pc, r_pc + 1),
                    NextState("EXECUTE-JL")
                ],
                INSTR_JN: [
                    NextValue(r_pc, r_pc + 1),
                    If(r_a[r_a.nbits - 1],
                        NextState("EXECUTE-J")
                    )
                ],
            })
        )
        self.fsm.act("EXECUTE-LDI",
            NextValue(r_a, signext(c_dat)),
            NextState("FETCH")
        )
        self.fsm.act("EXECUTE-LDIH",
            NextValue(r_a[8:], c_dat),
            NextState("FETCH")
        )
        self.fsm.act("EXECUTE-LDF",
            NextValue(r_a, signext(out_fifo.dout)),
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextState("FETCH")
            )
        )
        self.fsm.act("EXECUTE-ADDI",
            NextValue(r_a, r_a + signext(c_dat)),
            NextState("FETCH")
        )
        self.fsm.act("EXECUTE-ADJ",
            NextValue(r_p, r_p + signext(c_dat)),
            NextState("FETCH")
        )
        self.fsm.act("EXECUTE-J",
            NextValue(r_pc, r_pc + signext(c_dat)),
            NextState("FETCH")
        )
        self.fsm.act("EXECUTE-JE",
            c_adr.eq(r_pc),
            NextValue(r_pc, r_pc + 1),
            If(r_a == signext(c_dat),
                NextState("EXECUTE-J")
            ).Else(
                NextState("FETCH")
            )
        )
        self.fsm.act("EXECUTE-JL",
            c_adr.eq(r_pc),
            NextValue(r_pc, r_pc + 1),
            If(r_a < signext(c_dat),
                NextState("EXECUTE-J")
            ).Else(
                NextState("FETCH")
            )
        )
        self.fsm.act("EXECUTE-HLT",
            NextState("EXECUTE-HLT")
        )
