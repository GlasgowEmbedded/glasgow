# Ref: MIPS® Architecture for Programmers Volume II-A: The MIPS32® Instruction Set Manual
# Document Number: MD00086 Revision 6.05
# Accession: G00021

__all__ = [
    # R-format
    "SLL", "SRL", "SRA", "JR", "JALR", "MFHI", "MTHI", "MFLO", "MTLO", "DIV", "DIVU", "MULT",
    "MULTU", "ADD", "ADDU", "SUB", "SUBU", "AND", "OR", "XOR", "NOR", "SLT", "SLTU",
    # J-format
    "J", "JAL",
    # I-format
    "BEQ", "BNE", "BLEZ", "BGTZ", "ADDI", "ADDIU", "SLTI", "SLTIU", "ANDI", "ORI", "XORI",
    "LUI", "LB", "LH", "LW", "LBU", "LHU", "SB", "SH", "SW",
    # Misc
    "MFC0", "MTC0", "DERET", "SDBBP", "SYNC", "SYNCI", "CACHE",
    # Pseudo
    "NOP", "B",
]

# Instruction formats

def R_FORMAT(op, rs, rt, rd, sa, fn):
    return (((op &  0b111111) << 26) |
            ((rs &   0b11111) << 21) |
            ((rt &   0b11111) << 16) |
            ((rd &   0b11111) << 11) |
            ((sa &   0b11111) <<  6) |
            ((fn &  0b111111) <<  0))

def I_FORMAT(op, rs, rt, im):
    return (((op &  0b111111) << 26) |
            ((rs &   0b11111) << 21) |
            ((rt &   0b11111) << 16) |
            ((im &    0xffff) <<  0))

def J_FORMAT(op, tg):
    return (((op &  0b111111) << 26) |
            ((tg & 0x3ffffff) <<  0))

# R-instructions

def SLL  (rd, rt, sa):    return R_FORMAT(op=0x00, rs= 0, rt=rt, rd=rd, sa=sa, fn=0x00)
def SRL  (rd, rt, sa):    return R_FORMAT(op=0x00, rs= 0, rt=rt, rd=rd, sa=sa, fn=0x02)
def SRA  (rd, rt, sa):    return R_FORMAT(op=0x00, rs= 0, rt=rt, rd=rd, sa=sa, fn=0x03)

def JR   (rs):            return R_FORMAT(op=0x00, rs=rs, rt= 0, rd= 0, sa=0,  fn=0x08)
def JALR (rd, rs):        return R_FORMAT(op=0x00, rs=rs, rt= 0, rd=rd, sa=0,  fn=0x09)

def MFHI (rd):            return R_FORMAT(op=0x00, rs= 0, rt= 0, rd=rd, sa=0,  fn=0x10)
def MTHI (rd):            return R_FORMAT(op=0x00, rs= 0, rt= 0, rd=rd, sa=0,  fn=0x11)
def MFLO (rs):            return R_FORMAT(op=0x00, rs=rs, rt= 0, rd= 0, sa=0,  fn=0x12)
def MTLO (rs):            return R_FORMAT(op=0x00, rs=rs, rt= 0, rd= 0, sa=0,  fn=0x13)

def DIV  (rs, rt):        return R_FORMAT(op=0x00, rs=rs, rt=rt, rd= 0, sa=0,  fn=0x1A)
def DIVU (rs, rt):        return R_FORMAT(op=0x00, rs=rs, rt=rt, rd= 0, sa=0,  fn=0x1B)
def MULT (rs, rt):        return R_FORMAT(op=0x00, rs=rs, rt=rt, rd= 0, sa=0,  fn=0x18)
def MULTU(rs, rt):        return R_FORMAT(op=0x00, rs=rs, rt=rt, rd= 0, sa=0,  fn=0x19)

def ADD  (rd, rs, rt):    return R_FORMAT(op=0x00, rs=rs, rt=rt, rd=rd, sa=0,  fn=0x20)
def ADDU (rd, rs, rt):    return R_FORMAT(op=0x00, rs=rs, rt=rt, rd=rd, sa=0,  fn=0x21)
def SUB  (rd, rs, rt):    return R_FORMAT(op=0x00, rs=rs, rt=rt, rd=rd, sa=0,  fn=0x22)
def SUBU (rd, rs, rt):    return R_FORMAT(op=0x00, rs=rs, rt=rt, rd=rd, sa=0,  fn=0x23)

def AND  (rd, rs, rt):    return R_FORMAT(op=0x00, rs=rs, rt=rt, rd=rd, sa=0,  fn=0x24)
def OR   (rd, rs, rt):    return R_FORMAT(op=0x00, rs=rs, rt=rt, rd=rd, sa=0,  fn=0x25)
def XOR  (rd, rs, rt):    return R_FORMAT(op=0x00, rs=rs, rt=rt, rd=rd, sa=0,  fn=0x26)
def NOR  (rd, rs, rt):    return R_FORMAT(op=0x00, rs=rs, rt=rt, rd=rd, sa=0,  fn=0x27)

def SLT  (rd, rs, rt):    return R_FORMAT(op=0x00, rs=rs, rt=rt, rd=rd, sa=0,  fn=0x2A)
def SLTU (rd, rs, rt):    return R_FORMAT(op=0x00, rs=rs, rt=rt, rd=rd, sa=0,  fn=0x2B)

# J-instructions

def J    (tg):            return J_FORMAT(op=0x02, tg=tg)
def JAL  (tg):            return J_FORMAT(op=0x03, tg=tg)

# I-instructions

def BEQ  (rs, rt, im):    return I_FORMAT(op=0x04, rs=rs, rt=rt, im=im)
def BNE  (rs, rt, im):    return I_FORMAT(op=0x05, rs=rs, rt=rt, im=im)
def BLEZ (rs,     im):    return I_FORMAT(op=0x06, rs=rs, rt= 0, im=im)
def BGTZ (rs,     im):    return I_FORMAT(op=0x07, rs=rs, rt= 0, im=im)

def ADDI (rt, rs, im):    return I_FORMAT(op=0x08, rs=rs, rt=rt, im=im)
def ADDIU(rt, rs, im):    return I_FORMAT(op=0x09, rs=rs, rt=rt, im=im)

def SLTI (rt, rs, im):    return I_FORMAT(op=0x0A, rs=rs, rt=rt, im=im)
def SLTIU(rt, rs, im):    return I_FORMAT(op=0x0B, rs=rs, rt=rt, im=im)

def ANDI (rt, rs, im):    return I_FORMAT(op=0x0C, rs=rs, rt=rt, im=im)
def ORI  (rt, rs, im):    return I_FORMAT(op=0x0D, rs=rs, rt=rt, im=im)
def XORI (rt, rs, im):    return I_FORMAT(op=0x0E, rs=rs, rt=rt, im=im)

def LUI  (rt, im):        return I_FORMAT(op=0x0F, rs= 0, rt=rt, im=im)

def LB   (rt, im, rs):    return I_FORMAT(op=0x20, rs=rs, rt=rt, im=im)
def LH   (rt, im, rs):    return I_FORMAT(op=0x21, rs=rs, rt=rt, im=im)
def LW   (rt, im, rs):    return I_FORMAT(op=0x23, rs=rs, rt=rt, im=im)
def LBU  (rt, im, rs):    return I_FORMAT(op=0x24, rs=rs, rt=rt, im=im)
def LHU  (rt, im, rs):    return I_FORMAT(op=0x25, rs=rs, rt=rt, im=im)

def SB   (rt, im, rs):    return I_FORMAT(op=0x28, rs=rs, rt=rt, im=im)
def SH   (rt, im, rs):    return I_FORMAT(op=0x29, rs=rs, rt=rt, im=im)
def SW   (rt, im, rs):    return I_FORMAT(op=0x2B, rs=rs, rt=rt, im=im)

# Misc instructions

def MFC0 (rt, rd, sel=0): return R_FORMAT(op=0x10, rs=0x00, rt=rt,   rd=rd, sa=0, fn=sel & 0b111)
def MTC0 (rt, rd, sel=0): return R_FORMAT(op=0x10, rs=0x04, rt=rt,   rd=rd, sa=0, fn=sel & 0b111)

def DERET():              return R_FORMAT(op=0x10, rs=0x10, rt=0x00, rd= 0, sa=0, fn=0x1f)
def SDBBP():              return R_FORMAT(op=0x1c, rs=0x00, rt=0x00, rd= 0, sa=0, fn=0x3f)

def SYNC ():              return R_FORMAT(op=0x00, rs=0x00, rt=0x00, rd= 0, sa=0, fn=0x0f)
def SYNCI(im, rs):        return I_FORMAT(op=0x01, rs=rs,   rt=0x1f, im=im)
def CACHE(op, im, rs):    return I_FORMAT(op=0x2f, rs=rs,   rt=op,   im=im)

# Pseudo-instructions

def NOP  ():              return SLL(0, 0,  0)
def B    (im):            return BEQ(0, 0, im)
