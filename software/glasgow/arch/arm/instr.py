# Ref: ARM® Architecture Reference Manual ARMv7-A and ARMv7-R edition
# Document Number: DDI 0406C
# Accession: G00094

__all__ = [
    # Thumb instructions
    "T_MOV",
    "T_EOR",
    "T_LDR_LIT",
    "T_STR",
    "T_B",
    "T_BX",
    "T_BKPT",

    # ARM instructions
    "A_MOV",
    "A_STR",
    "A_STRH",
    "A_STRB",
    "A_LDR",
    "A_LDRH",
    "A_LDRB",
    "A_STM",
    "A_LDM",
    "A_B",
    "A_BX",
    "A_MRS",
    "A_MSR_REG",
    "A_MSR_LIT",
    "A_BKPT",

    # PSR mode fields
    "M_usr",
    "M_fiq",
    "M_irq",
    "M_svc",
    "M_abt",
    "M_und",
    "M_sys",
]


# Thumb instructions

def T_EOR(rdn, rm):
    return 0x4040 | ((rm & 0x7) << 3) | (rdn & 0x7)

def T_MOV(rd, rm):
    return 0x4600 | (((rd) & 0x8) << 4) | (((rm) & 0xf) << 3) | ((rd) & 0x7)

def T_LDR_LIT(rt, imm):
    return 0x4800 | ((rt & 0x7) << 8) | (imm & 0xff)

def T_STR(rt, rn, imm=0):
    return 0x6000 | ((imm & 0x1f) << 6) | ((rn & 0x7) << 3) | (rt & 0x7)

def T_B(imm):
    return 0xe000 | (imm & 0x7ff)

def T_BX(rm):
    return 0x4700 | ((rm & 0xf) << 3)

def T_BKPT(imm):
    return 0xbe00 | (imm & 0xff)


# ARM instructions

def A_MOV(rd, rm):
    return 0xe1a00000 | ((rd & 0xf) << 12) | (rm & 0xf)

def A_STR(rt, rn, imm=0, *, w=0):
    return 0xe5800000 | ((w & 1) << 21) | ((rn & 0xf) << 16) | ((rt & 0xf) << 12) | (imm & 0xfff)

def A_STRH(rt, rn, imm=0, *, p=0, w=0):
    assert not (p == 0 and w == 1)
    return 0xe0c000b0 | ((p & 1) << 24) | ((w & 1) << 21) | \
        ((rn & 0xf) << 16) | ((rt & 0xf) << 12) | ((imm & 0xf0) << 4) | (imm & 0xf)

def A_STRB(rt, rn, imm=0, *, p=0, w=0):
    assert not (p == 0 and w == 1)
    return 0xe4c00000 | ((p & 1) << 24) | ((w & 1) << 21) | \
        ((rn & 0xf) << 16) | ((rt & 0xf) << 12) | (imm & 0xfff)

def A_LDR(rt, rn, imm=0, *, w=0):
    return 0xe5900000 | ((w & 1) << 21) | ((rn & 0xf) << 16) | ((rt & 0xf) << 12) | (imm & 0xfff)

def A_LDRH(rt, rn, imm=0, *, p=0, w=0):
    assert not (p == 0 and w == 1)
    return 0xe0d000b0 | ((p & 1) << 24) | ((w & 1) << 21) | \
        ((rn & 0xf) << 16) | ((rt & 0xf) << 12) | ((imm & 0xf0) << 4) | (imm & 0xf)

def A_LDRB(rt, rn, imm=0, *, p=0, w=0):
    assert not (p == 0 and w == 1)
    return 0xe4d00000 | ((p & 1) << 24) | ((w & 1) << 21) | \
        ((rn & 0xf) << 16) | ((rt & 0xf) << 12) | (imm & 0xfff)

def A_STM(rn, lst, *, w=0):
    return 0xe8800000 | ((w & 1) << 21) | ((rn & 0xf) << 16) | (lst & 0xffff)

def A_LDM(rn, lst, *, w=0):
    return 0xe8900000 | ((w & 1) << 21) | ((rn & 0xf) << 16) | (lst & 0xffff)

def A_B(imm):
    return 0xea000000 | (imm & 0xffffff)

def A_BX(rm):
    return 0xe12fff10 | (rm & 0xf)

def A_MRS(rd, r):
    return 0xe10f0000 | ((r & 1) << 22) | ((rd & 0xf) << 12)

def A_MSR_REG(r, mask, rn):
    return 0xe120f000 | ((r & 1) << 22) | ((mask & 0xf) << 16) | (rn & 0xf)

def A_MSR_LIT(r, mask, imm):
    return 0xe320f000 | ((r & 1) << 22) | ((mask & 0xf) << 16) | (imm & 0xfff)

def A_BKPT(imm):
    return 0xe1200070 | ((imm & 0xfff0) << 4) | (imm & 0xf)


# xPSR mode field

M_usr = 0b10000
M_fiq = 0b10001
M_irq = 0b10010
M_svc = 0b10011
M_abt = 0b10111
M_und = 0b11011
M_sys = 0b11111
