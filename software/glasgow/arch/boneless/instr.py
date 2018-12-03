import types

from .opcode import *


__all__ = [
    "R0", "R1", "R2", "R3", "R4", "R5", "R6", "R7",
    "ADD", "ADDI", "AND", "CMP", "J", "JAL", "JC", "JE", "JNC", "JNE", "JNO", "JNS", "JNZ", "JO",
    "JR", "JS", "JSGE", "JSGT", "JSLE", "JSLT", "JUGE", "JUGT", "JULE", "JULT", "JZ", "LD", "LDI",
    "LDX", "MOV", "MOVA", "MOVH", "MOVI", "MOVL", "NOP", "OR", "ROT", "SLL", "SRA", "SRL", "ST",
    "STI", "STX", "SUB", "SUBI", "XOR",
    "L", "assemble",
]


def A_FORMAT(opcode, optype, rd, ra, rb):
    assert rd in range(8) and ra in range(8) and rb in range(8)
    return (((opcode & 0b11111) << 11) |
            ((    rd &   0b111) <<  8) |
            ((    ra &   0b111) <<  5) |
            ((    rb &   0b111) <<  2) |
            ((optype &    0b11) <<  0))

def S_FORMAT(opcode, optype, rd, ra, amt):
    assert rd in range(8) and ra in range(8) and amt in range(16)
    return (((opcode & 0b11111) << 11) |
            ((    rd &   0b111) <<  8) |
            ((    ra &   0b111) <<  5) |
            ((   amt &  0b1111) <<  1) |
            ((optype &     0b1) <<  0))

def M_FORMAT(opcode, rsd, ra, off):
    assert rsd in range(8) and ra in range(8)
    if isinstance(off, str):
        return lambda resolve: M_FORMAT(opcode, rsd, ra, resolve(off))
    assert -16 <= off <= 15
    return (((opcode & 0b11111) << 11) |
            ((   rsd &   0b111) <<  8) |
            ((    ra &   0b111) <<  5) |
            ((   off & 0b11111) <<  0))

def I_FORMAT(opcode, rsd, imm, u=False):
    assert rsd in range(8)
    if isinstance(imm, str):
        return lambda resolve: I_FORMAT(opcode, rst, resolve(imm), u)
    assert ((not u and -128 <= imm <= 127) or
            (u and imm in range(256)))
    return (((opcode & 0b11111) << 11) |
            ((   rsd &   0b111) <<  8) |
            ((   imm &    0xff) <<  0))

def C_FORMAT(opcode, off):
    if isinstance(off, str):
        return lambda resolve: C_FORMAT(opcode, resolve(off))
    assert -1024 <= off <= 1023
    return (((opcode & 0b11111) << 11) |
            ((   off &   0x7ff) <<  0))


R0, R1, R2, R3, R4, R5, R6, R7 = range(8)


def NOP ():            return [A_FORMAT(OPCODE_LOGIC,   OPTYPE_AND,  0,  0,  0)]

def AND (rd, ra, rb):  return [A_FORMAT(OPCODE_LOGIC,   OPTYPE_AND, rd, ra, rb)]
def OR  (rd, ra, rb):  return [A_FORMAT(OPCODE_LOGIC,   OPTYPE_OR,  rd, ra, rb)]
def XOR (rd, ra, rb):  return [A_FORMAT(OPCODE_LOGIC,   OPTYPE_XOR, rd, ra, rb)]

def ADD (rd, ra, rb):  return [A_FORMAT(OPCODE_ARITH,   OPTYPE_ADD, rd, ra, rb)]
def SUB (rd, ra, rb):  return [A_FORMAT(OPCODE_ARITH,   OPTYPE_SUB, rd, ra, rb)]
def CMP (    rb, ra):  return [A_FORMAT(OPCODE_ARITH,   OPTYPE_CMP,  0, ra, rb)]

def SLL (rd, ra, amt): return [S_FORMAT(OPCODE_SHIFT_L, OPTYPE_SLL, rd, ra, amt)]
def ROT (rd, ra, amt): return [S_FORMAT(OPCODE_SHIFT_L, OPTYPE_ROT, rd, ra, amt)]
def SRL (rd, ra, amt): return [S_FORMAT(OPCODE_SHIFT_R, OPTYPE_SRL, rd, ra, amt)]
def SRA (rd, ra, amt): return [S_FORMAT(OPCODE_SHIFT_R, OPTYPE_SRA, rd, ra, amt)]
def MOV (rd, rs):      return [S_FORMAT(OPCODE_SHIFT_L, OPTYPE_SLL, rd, rs,   0)]

def LD  (rd, ra, off): return [M_FORMAT(OPCODE_LD,   rd, ra, off)]
def ST  (rs, ra, off): return [M_FORMAT(OPCODE_ST,   rs, ra, off)]
def LDX (rd, ra, off): return [M_FORMAT(OPCODE_LDX,  rd, ra, off)]
def STX (rs, ra, off): return [M_FORMAT(OPCODE_STX,  rs, ra, off)]

def ADDI(rd, imm):     return [I_FORMAT(OPCODE_ADDI, rd, +imm)]
def SUBI(rd, imm):     return [I_FORMAT(OPCODE_ADDI, rd, -imm)]

def MOVL(rd, imm):     return [I_FORMAT(OPCODE_MOVL, rd, imm, u=True)]
def MOVH(rd, imm):     return [I_FORMAT(OPCODE_MOVH, rd, imm, u=True)]

def MOVA(rd, off):     return [I_FORMAT(OPCODE_MOVA, rd, off)]
def LDI (rd, off):     return [I_FORMAT(OPCODE_LDI,  rd, off)]
def STI (rs, off):     return [I_FORMAT(OPCODE_STI,  rs, off)]
def JAL (rd, off):     return [I_FORMAT(OPCODE_JAL,  rd, off)]
def JR  (rd, off):     return [I_FORMAT(OPCODE_JR,   rd, off)]

def J   (off):         return [C_FORMAT(OPCODE_J,    off)]

def JNZ (off):         return [C_FORMAT(OPCODE_JNZ,  off)]
def JZ  (off):         return [C_FORMAT(OPCODE_JZ,   off)]
def JNS (off):         return [C_FORMAT(OPCODE_JNS,  off)]
def JS  (off):         return [C_FORMAT(OPCODE_JS,   off)]
def JNC (off):         return [C_FORMAT(OPCODE_JNC,  off)]
def JC  (off):         return [C_FORMAT(OPCODE_JC,   off)]
def JNO (off):         return [C_FORMAT(OPCODE_JNO,  off)]
def JO  (off):         return [C_FORMAT(OPCODE_JO,   off)]

def JNE (off):         return [C_FORMAT(OPCODE_JNE,  off)]
def JE  (off):         return [C_FORMAT(OPCODE_JE,   off)]
def JUGE(off):         return [C_FORMAT(OPCODE_JUGE, off)]
def JULT(off):         return [C_FORMAT(OPCODE_JULT, off)]
def JUGT(off):         return [C_FORMAT(OPCODE_JUGT, off)]
def JULE(off):         return [C_FORMAT(OPCODE_JULE, off)]
def JSGE(off):         return [C_FORMAT(OPCODE_JSGE, off)]
def JSLT(off):         return [C_FORMAT(OPCODE_JSLT, off)]
def JSGT(off):         return [C_FORMAT(OPCODE_JSGT, off)]
def JSLE(off):         return [C_FORMAT(OPCODE_JSLE, off)]

def MOVI(rd, imm16):
    assert imm16 in range(65536)
    if imm16 in range(256):
        return MOVL(rd, imm16)
    else:
        return MOVH(rd, (imm16 >> 8) + ((imm16 >> 7) & 1)) + \
               I_FORMAT(OPCODE_ADDI, rd, imm16 & 0xff, u=True)


def L(label): return label

def assemble(code):
    flat_code = []
    labels    = {}
    for elem in code:
        if isinstance(elem, str):
            assert elem not in labels
            labels[elem] = len(flat_code)
        else:
            flat_code += elem
    for offset, elem in enumerate(flat_code):
        if isinstance(elem, types.LambdaType):
            flat_code[offset] = elem(lambda label: labels[label] - offset - 1)
    return flat_code
