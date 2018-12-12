# Introduction
# ------------
#
# _Boneless_ is a CPU architecture created specifically for Glasgow. It is designed for applet
# control plane, with the goals being minimal FPGA resource (logic and timing) consumption while
# still remaining easily programmable in hand-written assembly. It is not directly derived from
# any major CPU architecture, but borrows ideas from cores such as 8051, MIPS and AVR.
#
# This file is the primary document defining Boneless. Changing this file constitutes changing
# the authoritative definition of the architecture. Boneless should only be used outside of
# Glasgow if it is forked and renamed.
#
# Overview
# --------
#
# The major characteristics of the Boneless architecture are:
#   * Radical von Neumann architecture; registers, instructions and data share address space.
#   * Registers defined as an aligned, movable window into common address space.
#   * Unified 16-bit register, instruction and data word size; word-addressable only.
#   * Unified PC-relative memory addressing for code and data offsets.
#   * Five instruction classes:
#     - A-class, for ALU operations.
#     - S-class, for shift operations.
#     - M-class, for load-store operations. 5-bit single-extended offset.
#     - I-class, for operations with immediates. 8-bit sign-extended immediate.
#     - C-class, for control transfers. 11-bit sign-extended offset.
#   * Four flags: Z (zero), S (sign), C (carry), O (overflow).
#   * Secondary address space for special-purpose registers.
#
# As a result, Boneless can be efficiently implemented with a single 16-bit wide single-port
# block RAM primitive, e.g. on iCE40UP5K, this could be one 16Kx16 SPRAM or one 256x16 BRAM.
#
# Instruction format
# ------------------
#
# Instruction classes are laid out as follows:
#
#             +---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+
#             | F | E | D | C | B | A | 9 | 8 | 7 | 6 | 5 | 4 | 3 | 2 | 1 | 0 |
#             +---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+
#     A-class | 0 | 0 | 0 | 0 | c |   R-dst   |   R-opa   |   R-opb   | type  |
#             +---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+
#     S-class | 0 | 0 | 0 | 1 | c |   R-dst   |   R-opa   |    amount     | t |
#             +---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+
#     M-class | 0 | 0 | 1 | code  | R-src/dst |   R-adr   |       offset      |
#             +---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+
#     I-class | 0 | 1 |  opcode   | R-src/dst |           immediate           |
#             +---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+
#     C-class | 1 | condition | F |                 offset                    |
#             +---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+
#
# Instruction decoding
# --------------------
#
# The instruction opcodes are structured as a prefix code optimized for fast decoding. Decoding
# proceeds as follows for instructions starting with...
#   * 0000x (A-class): load R-opb, load R-opa, and store R-dst;
#   * 0001x (S-class): load R-opa, and store R-dst;
#   * 001x0 (M-class LD): load R-adr, load memory, and store R-dst;
#   * 001x1 (M-class ST): load R-adr, load R-src, and store memory;
#   * 0100x (I-class r-m-w): load R-src/dst, and store R-src/dst.
#   * 0101x (I-class w): store R-dst.
#   * 01100 (I-class LD): load memory, and store R-dst.
#   * 01101 (I-class ST): load R-src, and store memory.
#   * 01110 (I-class JAL): store R-dst, and jump.
#   * 01111 (I-class JR): load R-src, and jump.
#   * 1xxxx (C-class): jump.
#
# As a result, Boneless instruction decoding can be implemented with approximately 10 4-LUTs.
#
# Instruction set omissions
# -------------------------
#
# The following instructions were deliberately omitted because of the limited opcode space and
# less importance than other instructions:
#   * Add/subtract with carry; shift with carry; rotate through carry.
#     Can be emulated in software with JC/JNC.
#   * Move with immediate that preserves register contents.
#     Loads of 16-bit immediates can be expanded into MOVH and ADDI, with the immediate in MOVH
#     being adjusted for sign extension performed in ADDI.
#   * Return from interrupt.
#     Interrupts are not currently supported.
#
# Instruction set summary
# -----------------------
#
# * class=A
#   - code=0 (logic)
#     + type=00 AND
#     + type=01 OR
#     + type=10 XOR
#     + type=11 (1 unassigned)
#   - code=1 (arithmetic)
#     + type=00 ADD
#     + type=01 SUB
#     + type=10 CMP
#     + type=11 (1 unassigned)
# * class=S
#   - code=0
#     + type=0 SLL, MOV
#     + type=1 ROT
#   - code=1
#     + type=0 SRL
#     + type=1 SRA
# * class=M
#   - code=00 LD
#   - code=01 ST
#   - code=10 LDX
#   - code=11 STX
# * class=I
#   - code=000 MOVL
#   - code=001 MOVH
#   - code=010 MOVA
#   - code=011 ADDI/SUBI
#   - code=100 LDI
#   - code=101 STI
#   - code=110 JAL
#   - code=111 JR
# * class=C
#   - code=000
#     + flag=0 J
#     + flag=1 (1 unassigned)
#   - code=001 JNZ/JNE, JZ/JE
#   - code=010 JNS, JS
#   - code=011 JNO, JO
#   - code=100 JNC/JUGE, JC/JULT
#   - code=101 JUGT, JULE
#   - code=110 JSGE, JSLT
#   - code=111 JSGT, JSLE
#
# Move instructions
# -----------------
#
# Mnemonic:  MOV  Rd, Ra
# Operation: Rd ← Ra
#
# Mnemonic:  MOVL Rd, imm
# Operation: Rd[15:8] ← 0,   Rd[7:0] ← imm
#
# Mnemonic:  MOVH Rd, imm
# Operation: Rd[15:8] ← imm, Rd[7:0] ← 0
#
# Mnemonic:  MOVI Rd, imm (pseudo)
# Operation: Rd ← imm
#
# Mnemonic:  MOVA Rd, ±off
# Operation: Rd ← PC+1+off
#
# Logic instructions
# ------------------
#
# Mnemonic:  AND  Rd, Ra, Rb
#            OR   Rd, Ra, Rb
#            XOR  Rd, Ra, Rb
# Operation: Rd ← Ra · Rb
#            ZS ← flags(Rd)
#            CO ← undefined
#
# Arithmetic instructions
# -----------------------
#
# Mnemonic:  ADD  Rd, Ra, Rb
#            SUB  Rd, Ra, Rb
# Operation: Rd ← Ra · Rb
#            ZSCO ← flags(Rd)
#
# Mnemonic:  ADDI Rd, ±imm
#            SUBI Rd, ±imm (pseudo)
# Operation: Rd ← Rd + imm
#            ZSCO ← flags(Rd)
#
# Mnemonic:  CMP  Ra, Rb
# Operation: t  ← Ra - Rb
#            ZSCO ← flags(t)
#
# Shift instructions
# ------------------
#
# Mnemonic:  SLL  Rd, Ra, amt
# Operation: Rd ← {Ra[15-amt:0],   amt{0}}
#            ZS ← flags(Rd)
#            CO ← undefined
#
# Mnemonic:  ROT  Rd, Ra, amt
#            ROL  Rd, Ra, amt (alias)
#            ROR  Rd, Ra, amt (pseudo)
# Operation: Rd ← {Ra[15-amt:0],   Ra[15:15-amt]}
#            ZS ← flags(Rd)
#            CO ← undefined
#
# Mnemonic:  SRL  Rd, Ra, amt
# Operation: Rd ← {15-amt{0},      Ra[15:amt]}
#            ZS ← flags(Rd)
#            CO ← undefined
#
# Mnemonic:  SRA  Rd, Ra, amt
# Operation: Rd ← {15-amt{Ra[15]}, Ra[15:amt]}
#            ZS ← flags(Rd)
#            CO ← undefined
#
# Memory instructions
# -------------------
#
# Mnemonic:  LD   Rd, Ra, off
# Operation: Rd ← mem[Ra+off]
#
# Mnemonic:  LDI  Rd, ±off
# Operation: Rd ← mem[PC+off]
#
# Mnemonic:  LDX  Rd, Ra, off
# Operation: Rd ← ext[Ra+off]
#
# Mnemonic:  ST   Rs, Ra, off
# Operation: mem[Ra+off] ← Rs
#
# Mnemonic:  STI  Rs, ±off
# Operation: mem[PC+off] ← Rs
#
# Mnemonic:  STX  Rs, Ra, off
# Operation: ext[Ra+off] ← Rs
#
# Control instructions
# --------------------
#
# Mnemonic:  J    ±off
# Operation: PC ← PC+1+off
#
# Mnemonic:  JAL  Rd, ±off
# Operation: Rd ← PC+1
#            PC ← PC+1+off
#
# Mnemonic:  JR   Rs, ±off
# Operation: PC ← Rs+off
#
# Mnemonic:  JNZ  ±off (F=0)
#            JZ   ±off (F=1)
#            JNE  ±off (F=0)
#            JE   ±off (F=1)
# Operation: if(Z = F)
#              PC ← PC+1+off
#
# Mnemonic:  JNC  ±off (F=0)
#            JC   ±off (F=1)
#            JULT ±off (F=0)
#            JUGE ±off (F=1)
# Operation: if(C = F)
#              PC ← PC+1+off
#
# Mnemonic:  JULE ±off (F=0)
#            JUGT ±off (F=1)
# Operation: if((~C or Z) = F)
#              PC ← PC+1+off
#
# Mnemonic:  JSGE ±off (F=0)
#            JSLT ±off (F=1)
# Operation: if((S xor O) = F)
#              PC ← PC+1+off
#
# Mnemonic:  JSGT ±off (F=0)
#            JSLE ±off (F=1)
# Operation: if(((S xor O) or Z) = F)
#              PC ← PC+1+off
