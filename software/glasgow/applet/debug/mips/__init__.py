# Ref: MIPS® EJTAG Specification
# Document Number: MD00047 Revision 6.10
# Accession: G00007

import struct
import logging
import asyncio

from ....support.aobject import *
from ....support.endpoint import *
from ....support.bits import *
from ....support.arepl import *
from ....arch.mips import *
from ....protocol.gdb_remote import *
from ...interface.jtag_probe import JTAGProbeApplet
from ... import *


class EJTAGError(GlasgowAppletError):
    pass


class EJTAGDebugInterface(aobject, GDBRemote):
    async def __init__(self, interface, logger):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        self._control = DR_CONTROL()
        self._state   = "Probe"
        await self._probe()

        self._pracc_probed = False
        self._cp0_config   = None
        self._cp0_config1  = None
        self._cp0_debug    = None
        self._instr_brkpts = []
        self._softw_brkpts = {}

    def _log(self, message, *args):
        self._logger.log(self._level, "EJTAG: " + message, *args)

    def _check_state(self, action, *states):
        if self._state not in states:
            raise EJTAGError("cannot %s: not in %s state" %
                             (action, ", ".join(states)))

    def _change_state(self, state):
        self._log("set state %s", state)
        self._state = state

    # Low-level register manipulation

    async def _read_impcode(self):
        await self.lower.write_ir(IR_IMPCODE)
        impcode_bits = await self.lower.read_dr(32)
        self._impcode = DR_IMPCODE.from_bits(impcode_bits)
        self._log("read IMPCODE %s", self._impcode.bits_repr())

    async def _exchange_control(self, **fields):
        control = self._control.copy()
        control.PrAcc = 1
        if self._impcode.EJTAGver > 0:
            # Some (but not all) EJTAG 1.x/2.0 cores implement Rocc handshaking. We ignore it,
            # since there's no easy way to tell which one it is (on some Lexra cores, Rocc appears
            # to be R/W, which breaks the handshaking mechanism.)
            control.Rocc = 1
        for field, value in fields.items():
            setattr(control, field, value)

        self._log("write CONTROL %s", control.bits_repr(omit_zero=True))
        control_bits = control.to_bits()
        await self.lower.write_ir(IR_CONTROL)

        control_bits = await self.lower.exchange_dr(control_bits)
        new_control = DR_CONTROL.from_bits(control_bits)
        self._log("read CONTROL %s", new_control.bits_repr(omit_zero=True))

        if self._impcode.EJTAGver > 0 and control.Rocc and new_control.Rocc:
            raise EJTAGError("target has been unexpectedly reset")

        return new_control

    async def _enable_probe(self):
        self._control.ProbEn   = 1
        self._control.ProbTrap = 1
        for _ in range(3):
            control = await self._exchange_control()
            if control.ProbEn and control.ProbTrap: break
        else:
            raise EJTAGError("ProbTrap/ProbEn stuck low")

    async def _scan_address_length(self):
        await self.lower.write_ir(IR_ADDRESS)
        self._address_length = await self.lower.scan_dr_length(max_length=64)
        assert self._address_length is not None
        self._log("scan ADDRESS length=%d", self._address_length)

    async def _read_address(self):
        await self.lower.write_ir(IR_ADDRESS)
        address_bits = await self.lower.read_dr(self._address_length)
        address_bits = address_bits + address_bits[-1:] * (64 - self._address_length)
        address = int(address_bits) & self._mask
        self._log("read ADDRESS %#0.*x", self._prec, address)
        return address

    async def _write_address(self, address):
        # See _read_address. NB: ADDRESS is only writable in EJTAG v1.x/2.0 with DMAAcc.
        self._log("write ADDRESS %#0.*x", self._prec, address)
        address_bits = bits(address, self._address_length)
        await self.lower.write_ir(IR_ADDRESS)
        await self.lower.write_dr(address_bits)

    async def _read_data(self):
        await self.lower.write_ir(IR_DATA)
        data_bits = await self.lower.read_dr(self.bits)
        data = int(data_bits)
        self._log("read DATA %#0.*x", self._prec, data)
        return data

    async def _write_data(self, data):
        self._log("write DATA %#0.*x", self._prec, data)
        await self.lower.write_ir(IR_DATA)
        data_bits = bits(data, self.bits)
        await self.lower.write_dr(data_bits)

    # DMAAcc memory read/write

    async def _dmaacc_read(self, address, size):
        self._log("DMAAcc: read address=%#0.*x size=%d", self._prec, address, size)
        # Make sure DMAAcc is set, or ADDRESS DR is not writable.
        await self._exchange_control(DMAAcc=1)
        await self._write_address(address)
        await self._exchange_control(DMAAcc=1, DRWn=1, Dsz=size, DStrt=1)
        for _ in range(3):
            control = await self._exchange_control(DMAAcc=1)
            if not control.DStrt: break
        else:
            raise EJTAGError("DMAAcc: read hang")
        if control.DErr:
            raise EJTAGError("DMAAcc: read error address=%#0.*x size=%d" %
                             (self._prec, address, size))
        data = await self._read_data()
        self._log("DMAAcc: data=%#0.*x", self._prec, data)
        await self._exchange_control(DMAAcc=0)
        return data

    async def _dmaacc_write(self, address, size, data):
        self._log("DMAAcc: write address=%#0.*x size=%d data=%#0.*x",
                  self._prec, address, size, self._prec, data)
        # Make sure DMAAcc is set, or ADDRESS DR is not writable.
        await self._exchange_control(DMAAcc=1)
        await self._write_address(address)
        await self._write_data(data)
        await self._exchange_control(DMAAcc=1, DRWn=0, Dsz=size, DStrt=1)
        for _ in range(3):
            control = await self._exchange_control(DMAAcc=1)
            if not control.DStrt: break
        else:
            raise EJTAGError("DMAAcc: write hang")
        if control.DErr:
            raise EJTAGError("DMAAcc: write error address=%#0.*x size=%d" %
                             (self._prec, address, size))
        await self._exchange_control(DMAAcc=0)

    # PrAcc state management

    async def _probe(self):
        self._check_state("probe", "Probe")

        await self._read_impcode()
        self._logger.info("found CPU with IMPCODE=%#010x", self._impcode.to_int())

        await self._scan_address_length()

        self.bits      = 64 if self._impcode.MIPS32_64 else 32
        self._prec     = self.bits // 4
        self._ws       = self.bits // 8
        self._mask     = ((1 << self.bits) - 1)

        self._logger.info("found MIPS%d CPU %#x (EJTAG version %s)",
                          self.bits, self._impcode.TypeInfo,
                          DR_IMPCODE_EJTAGver_values[self._impcode.EJTAGver])

        if self._impcode.EJTAGver == 0:
            self._DRSEG_IBS_addr  = DRSEG_IBS_addr_v1
            self._DRSEG_DBS_addr  = DRSEG_DBS_addr_v1
            self._DRSEG_IBAn_addr = DRSEG_IBAn_addr_v1
            self._DRSEG_IBCn_addr = DRSEG_IBCn_addr_v1
            self._DRSEG_IBMn_addr = DRSEG_IBMn_addr_v1
            self._DRSEG_DBAn_addr = DRSEG_DBAn_addr_v1
            self._DRSEG_DBCn_addr = DRSEG_DBCn_addr_v1
            self._DRSEG_DBMn_addr = DRSEG_DBMn_addr_v1
            self._DRSEG_DBVn_addr = DRSEG_DBVn_addr_v1
        else:
            self._DRSEG_IBS_addr  = DRSEG_IBS_addr
            self._DRSEG_DBS_addr  = DRSEG_DBS_addr
            self._DRSEG_IBAn_addr = DRSEG_IBAn_addr
            self._DRSEG_IBCn_addr = DRSEG_IBCn_addr
            self._DRSEG_IBMn_addr = DRSEG_IBMn_addr
            self._DRSEG_DBAn_addr = DRSEG_DBAn_addr
            self._DRSEG_DBCn_addr = DRSEG_DBCn_addr
            self._DRSEG_DBMn_addr = DRSEG_DBMn_addr
            self._DRSEG_DBVn_addr = DRSEG_DBVn_addr

        # Start by acknowledging any reset.
        control = await self._exchange_control(Rocc=0)
        if control.DM:
            raise EJTAGError("target already in debug mode")

        if self._impcode.EJTAGver == 0:
            self._logger.warning("found cursed EJTAG 1.x/2.0 CPU, using undocumented "
                                 "DCR.MP bit to enable PrAcc")
            # Undocumented sequence to disable memory protection for dmseg. The bit 2 is
            # documented as NMIpend, but on EJTAG 1.x/2.0 it is actually MP. It is only possible
            # to clear it via DMAAcc because PrAcc requires debug mode to already work.
            dcr  = await self._dmaacc_read(DRSEG_DCR_addr, 2)
            dcr &= ~(1<<2)
            await self._dmaacc_write(DRSEG_DCR_addr, 2, dcr)

        await self._enable_probe()
        self._change_state("Running")

    async def _ejtag_debug_interrupt(self):
        self._check_state("assert debug interrupt", "Running")
        await self._exchange_control(EjtagBrk=1)
        control = await self._exchange_control()
        if control.EjtagBrk:
            raise EJTAGError("failed to enter debug mode")

    async def _check_for_debug_interrupt(self):
        self._check_state("check for debug interrupt", "Running")
        control = await self._exchange_control()
        if control.DM:
            self._change_state("Interrupted")
        return control.DM

    async def _exec_pracc_bare(self, code, data=[], max_steps=1024,
                               entry_state="Stopped", suspend_state="Stopped"):
        self._check_state("execute PrAcc", entry_state)
        self._change_state("PrAcc")

        temp     = [0] * 0x80

        code_beg = (DMSEG_addr + 0x0200)  & self._mask
        code_end = code_beg   + len(code) * 4
        temp_beg = (DMSEG_addr + 0x1000)  & self._mask
        temp_end = temp_beg   + len(temp) * 4
        data_beg = (DMSEG_addr + 0x1200)  & self._mask
        data_end = data_beg   + len(data) * 4

        for step in range(max_steps):
            for _ in range(3):
                control = await self._exchange_control()
                if step == 0 and not control.DM:
                    raise EJTAGError("Exec_PrAcc: DM low on entry")
                elif not control.DM:
                    self._log("Exec_PrAcc: debug return")
                    self._change_state("Running")
                    return
                elif control.PrAcc:
                    break
            else:
                raise EJTAGError("Exec_PrAcc: PrAcc stuck low")

            address = await self._read_address()
            if step > 0 and address == code_beg:
                self._log("Exec_PrAcc: debug suspend")
                self._change_state(suspend_state)
                break

            if address in range(code_beg, code_end):
                area, area_beg, area_wr, area_name = code, code_beg, False, "code"
            elif address in range(temp_beg, temp_end):
                area, area_beg, area_wr, area_name = temp, temp_beg, True,  "temp"
            elif address in range(data_beg, data_end):
                area, area_beg, area_wr, area_name = data, data_beg, True,  "data"
            else:
                raise EJTAGError("Exec_PrAcc: address %#0.*x out of range" %
                                 (self._prec, address))

            area_off = (address - area_beg) // 4
            if control.PRnW:
                if not area_wr:
                    raise EJTAGError("Exec_PrAcc: write access to %s at %#0.*x" %
                                     (area_name, self._prec, address))

                word = await self._read_data()
                self._log("Exec_PrAcc: write %s [%#06x] = %#0.*x",
                          area_name, address & 0xffff, self._prec, word)
                area[area_off] = word
            else:
                self._log("Exec_PrAcc: read %s [%#06x] = %#0.*x",
                          area_name, address & 0xffff, self._prec, area[area_off])
                await self._write_data(area[area_off])

            await self._exchange_control(PrAcc=0)

        else:
            raise EJTAGError("Exec_PrAcc: step limit exceeded")

        return data

    async def _exec_pracc(self, code, *args, **kwargs):
        code = [
            *code,
            B    (-len(code)-1),
            NOP  (),
            NOP  (),
        ]
        return await self._exec_pracc_bare(code=code, *args, **kwargs)

    # PrAcc control flow management

    async def _pracc_debug_enter(self):
        self._log("PrAcc: debug enter")

        Rdata, *_ = range(1, 32)
        await self._exec_pracc(code=[
            MTC0 (Rdata, *CP0_DESAVE_addr),
            LUI  (Rdata, 0xff20),
            ORI  (Rdata, Rdata, 0x1200),
        ], entry_state="Interrupted")

        # We can't probe some target capabilities before we stop for the first time,
        # so do it now, if necessary.
        await self._pracc_probe()

    async def _pracc_debug_return(self):
        self._log("PrAcc: debug return")

        Rdata, *_ = range(1, 32)
        await self._exec_pracc_bare(code=[
            MFC0 (Rdata, *CP0_DESAVE_addr),
            DERET(),
            NOP  (),
            NOP  (),
            NOP  (),
        ], suspend_state="Interrupted")

    async def _pracc_single_step(self):
        self._log("PrAcc: single step")

        Racc, *_ = range(1, 32)
        await self._exec_pracc_bare(code=[
            MFC0 (Racc, *CP0_Debug_addr),
            ORI  (Racc, Racc, 0x0100), # set SSt
            MTC0 (Racc, *CP0_Debug_addr),
            MFC0 (Racc, *CP0_DESAVE_addr),
            DERET(),
            NOP  (),
            NOP  (),
            NOP  (),
        ])
        await self._exec_pracc(code=[
            MTC0 (Racc, *CP0_DESAVE_addr),
            MFC0 (Racc, *CP0_Debug_addr),
            ORI  (Racc, Racc, 0x0100),
            XORI (Racc, Racc, 0x0100), # clear SSt
            MTC0 (Racc, *CP0_Debug_addr),
            LUI  (Racc, 0xff20),
            ORI  (Racc, Racc, 0x1200),
        ])

    async def _pracc_read_cp0(self, address):
        Rdata, Racc, *_ = range(1, 32)
        value, = await self._exec_pracc(code=[
            SW   (Racc, self._ws * -1, Rdata),
            MFC0 (Racc, *address),
            SW   (Racc, 0, Rdata),
            LW   (Racc, self._ws * -1, Rdata),
            NOP  (),
        ], data=[0])

        self._log("PrAcc: read CP0 %s = %#.*x", address, self._prec, value)
        return value

    async def _pracc_write_cp0(self, address, value):
        self._log("PrAcc: write CP0 %s = %#.*x", address, self._prec, value)

        Rdata, Racc, *_ = range(1, 32)
        await self._exec_pracc(code=[
            SW   (Racc, self._ws * -1, Rdata),
            LW   (Racc, 0, Rdata),
            MTC0 (Racc, *address),
            LW   (Racc, self._ws * -1, Rdata),
            NOP  (),
        ], data=[value])

    async def _pracc_probe(self):
        if self._pracc_probed:
            return

        self._cp0_config = CP0_Config.from_int(await self._pracc_read_cp0(CP0_Config_addr))
        self._log("CP0.Config %s", self._cp0_config.bits_repr(omit_zero=True))
        self._logger.info("target is a %s %s %s endian CPU with %s MMU",
                          CP0_Config_AT_values[self._cp0_config.AT],
                          CP0_Config_AR_values[self._cp0_config.AR],
                          CP0_Config_BE_values[self._cp0_config.BE],
                          CP0_Config_MT_values[self._cp0_config.MT])
        self._logger.info("KUSEG cache policy: %s",   CP0_Config_Kx_values[self._cp0_config.KU])
        self._logger.info("KSEG0 cache policy: %s",   CP0_Config_Kx_values[self._cp0_config.K0])
        self._logger.info("KSEG2/3 cache policy: %s", CP0_Config_Kx_values[self._cp0_config.K23])

        self._cp0_config1 = CP0_Config1.from_int(await self._pracc_read_cp0(CP0_Config1_addr))
        self._log("CP0.Config1 %s", self._cp0_config1.bits_repr(omit_zero=True))
        for cache_side, way_enc, line_enc, sets_enc in [
            ("I", self._cp0_config1.IA, self._cp0_config1.IL, self._cp0_config1.IS),
            ("D", self._cp0_config1.DA, self._cp0_config1.DL, self._cp0_config1.DS),
        ]:
            way_count  = 1 + way_enc
            line_size  = 2 << (1 + line_enc)
            set_count  = 2 << (5 + sets_enc) if sets_enc != 7 else 32
            cache_size = line_size * set_count * way_count
            if line_enc == 0:
                self._logger.info("%s-cache is absent",
                                  cache_side)
            elif way_count == 0:
                self._logger.info("%s-cache is %d KiB direct-mapped",
                                  cache_side, cache_size / 1024)
            else:
                self._logger.info("%s-cache is %d KiB %d-way set-associative",
                                  cache_side, cache_size / 1024, way_count)

        self._cp0_config1 = CP0_Config1.from_int(await self._pracc_read_cp0(CP0_Config1_addr))
        self._log("CP0.Config1 %s", self._cp0_config1.bits_repr(omit_zero=True))

        self._cp0_debug = CP0_Debug.from_int(await self._pracc_read_cp0(CP0_Debug_addr))
        self._log("CP0.Debug %s", self._cp0_debug.bits_repr(omit_zero=True))
        if self._cp0_debug.NoSSt:
            self._logger.warning("target does not support single-stepping")

        ibs = DRSEG_IBS.from_int(await self._pracc_read_word(self._DRSEG_IBS_addr))
        self._log("IBS %s", self._cp0_config.bits_repr(omit_zero=True))
        self._instr_brkpts = [None] * ibs.BCN
        self._logger.info("target has %d instruction breakpoints", len(self._instr_brkpts))

        self._pracc_probed = True

    async def _pracc_get_registers(self):
        self._log("PrAcc: get registers")

        Rdata, Racc, *_ = range(1, 32)
        return await self._exec_pracc(code=[
            SW   (Racc, self._ws *  2, Rdata),
            MFC0 (Racc, *CP0_DESAVE_addr),
            SW   (Racc, self._ws *  1, Rdata),
            *[SW (Rn,   self._ws * Rn, 1) for Rn in range(3, 32)],
            MFC0 (Racc, *CP0_SR_addr),
            SW   (Racc, self._ws * 32, Rdata),
            MFLO (Racc),
            SW   (Racc, self._ws * 33, Rdata),
            MFHI (Racc),
            SW   (Racc, self._ws * 34, Rdata),
            MFC0 (Racc, *CP0_BadVAddr_addr),
            SW   (Racc, self._ws * 35, Rdata),
            MFC0 (Racc, *CP0_Cause_addr),
            SW   (Racc, self._ws * 36, Rdata),
            MFC0 (Racc, *CP0_DEPC_addr),
            SW   (Racc, self._ws * 37, Rdata),
            LW   (Racc, self._ws *  2, Rdata),
            NOP  (),
        ], data=[0] * 38)

    async def _pracc_set_registers(self, registers):
        self._log("PrAcc: set registers")

        Rdata, Racc, *_ = range(1, 32)
        await self._exec_pracc(code=[
            SW   (Racc, self._ws *  2, Rdata),
            LW   (Racc, self._ws *  1, Rdata),
            MTC0 (Racc, *CP0_DESAVE_addr),
            *[LW (Rn,   self._ws * Rn, 1) for Rn in range(3, 32)],
            LW   (Racc, self._ws * 32, Rdata),
            MTC0 (Racc, *CP0_SR_addr),
            LW   (Racc, self._ws * 33, Rdata),
            MTLO (Racc),
            LW   (Racc, self._ws * 34, Rdata),
            MTHI (Racc),
            LW   (Racc, self._ws * 35, Rdata),
            MTC0 (Racc, *CP0_BadVAddr_addr),
            LW   (Racc, self._ws * 36, Rdata),
            MTC0 (Racc, *CP0_Cause_addr),
            LW   (Racc, self._ws * 37, Rdata),
            MTC0 (Racc, *CP0_DEPC_addr),
            LW   (Racc, self._ws *  2, Rdata),
            NOP  (),
        ], data=registers)

    async def _pracc_get_gpr(self, number):
        Rdata, Racc, *_ = range(1, 32)
        if number != Rdata:
            value, = await self._exec_pracc(code=[
                SW   (number, 0, Rdata),
                NOP  ()
            ], data=[0])
        else:
            value, = await self._exec_pracc(code=[
                SW   (Racc, self._ws * -1, Rdata),
                MFC0 (Racc, *CP0_DESAVE_addr),
                SW   (Racc, 0, Rdata),
                LW   (Racc, self._ws * -1, Rdata),
                NOP  ()
            ], data=[0])

        self._log("PrAcc: get $%d = %.*x", number, self._prec, value)
        return value

    async def _pracc_set_gpr(self, number, value):
        self._log("PrAcc: set $%d = %.*x", number, self._prec, value)

        Rdata, Racc, *_ = range(1, 32)
        if number != Rdata:
            return await self._exec_pracc(code=[
                LW   (number, 0, Rdata),
                NOP  ()
            ], data=[value])
        else:
            return await self._exec_pracc(code=[
                SW   (Racc, self._ws * -1, Rdata),
                LW   (Racc, 0, Rdata),
                MTC0 (Racc, *CP0_DESAVE_addr),
                LW   (Racc, self._ws * -1, Rdata),
                NOP  ()
            ], data=[value])

    # PrAcc memory read/write

    async def _pracc_copy_word(self, address, value, is_read):
        Rdata, Raddr, Racc, *_ = range(1, 32)
        return (await self._exec_pracc(code=[
            SW   (Raddr, self._ws * -1, Rdata),
            SW   (Racc,  self._ws * -2, Rdata),
            LUI  (Raddr, address >> 16),
            ORI  (Raddr, Raddr, address),
            LW   (Racc,  0, Raddr if is_read else Rdata),
            SW   (Racc,  0, Rdata if is_read else Raddr),
            LW   (Racc,  self._ws * -2, Rdata),
            LW   (Raddr, self._ws * -1, Rdata),
            NOP  (),
        ], data=[value]))[0]

    async def _pracc_read_word(self, address):
        value = await self._pracc_copy_word(address, value=0, is_read=True)
        self._log("PrAcc: read [%#.*x] = %#.*x", self._prec, address, self._prec, value)
        return value

    async def _pracc_write_word(self, address, value):
        self._log("PrAcc: write [%#.*x] = %#.*x", self._prec, address, self._prec, value)
        await self._pracc_copy_word(address, value, is_read=False)

    async def _pracc_copy_memory(self, address, length, data, is_read):
        assert length <= 0x200

        # This really isn't efficient at all, but unaligned accesses to dmseg are currently
        # not handled correctly, and endianness is a nightmare. This should instead use
        # word-size transfers, and ideally also the FASTDATA channel, but the implementation
        # below works as a proof of concept.
        Rdata, Rdst, Rsrc, Rlen, Racc, *_ = range(1, 32)
        return await self._exec_pracc(code=[
            SW   (Rdst, self._ws * -1, Rdata),
            SW   (Rsrc, self._ws * -2, Rdata),
            SW   (Rlen, self._ws * -3, Rdata),
            SW   (Racc, self._ws * -4, Rdata),
            LUI  (Racc, address >> 16),
            ORI  (Racc, Racc, address),
            OR   (Rdst, 0, Rdata if is_read else Racc),
            OR   (Rsrc, 0, Racc  if is_read else Rdata),
            ORI  (Rlen, 0, length),
            LBU  (Racc, 0, Rsrc) if is_read else LW   (Racc, 0, Rsrc),
            ADDI (Rsrc, Rsrc,  1 if is_read else 4),
            SW   (Racc, 0, Rdst) if is_read else SB   (Racc, 0, Rdst),
            ADDI (Rdst, Rdst,  4 if is_read else 1),
            ADDI (Rlen, Rlen, -1),
            BGTZ (Rlen, -6),
            NOP  (),
            LW   (Racc, self._ws * -4, Rdata),
            LW   (Rlen, self._ws * -3, Rdata),
            LW   (Rsrc, self._ws * -2, Rdata),
            LW   (Rdst, self._ws * -1, Rdata),
            NOP  (),
        ], data=data)

    async def _pracc_read_memory(self, address, length):
        data = await self._pracc_copy_memory(address, length, data=[0] * length, is_read=True)
        return bytes(data)

    async def _pracc_write_memory(self, address, data):
        await self._pracc_copy_memory(address, len(data), [*data], is_read=False)

    # PrAcc cache operations

    async def _pracc_sync_icache_r1(self, address):
        Rdata, Raddr, *_ = range(1, 32)
        return (await self._exec_pracc(code=[
            SW   (Raddr, self._ws * -1, Rdata),
            LUI  (Raddr, address >> 16),
            CACHE(0b110_01, address, Raddr), # D_HIT_WRITEBACK
            CACHE(0b100_00, address, Raddr), # I_HIT_INVALIDATE
            SYNC (),
            LW   (Raddr, self._ws * -1, Rdata),
            NOP  (),
        ]))

    async def _pracc_sync_icache_r2(self, address):
        Rdata, Raddr, *_ = range(1, 32)
        return (await self._exec_pracc(code=[
            SW   (Raddr, self._ws * -1, Rdata),
            LUI  (Raddr, address >> 16),
            SYNCI(address, Raddr),
            SYNC (),
            LW   (Raddr, self._ws * -1, Rdata),
            NOP  (),
        ]))

    async def _pracc_sync_icache(self, address):
        if (address & DMSEG_mask) == DMSEG_addr & self._mask:
            policy = 2
        elif (address & KSEGx_mask) == KUSEG_addr & self._mask:
            policy = self._cp0_config.KU
        elif (address & KSEGx_mask) == KSEG0_addr & self._mask:
            policy = self._cp0_config.K0
        elif (address & KSEGx_mask) == KSEG1_addr & self._mask:
            policy = 2 # uncached
        elif (address & KSEGx_mask) in (KSEG2_addr & self._mask,
                                        KSEG3_addr & self._mask):
            policy = self._cp0_config.K23
        else:
            print(address & KSEGx_mask,
                  DMSEG_addr,
                  KUSEG_addr,
                  KSEG0_addr,
                  KSEG1_addr,
                  KSEG2_addr,
                  KSEG3_addr)
            assert False

        if policy == 2:
            return # Uncached, we're fine.

        if self._cp0_config.AR == 0: # R1
            self._log("PrAcc: MIPS R1 I-cache sync")
            await self._pracc_sync_icache_r1(address)
        elif self._cp0_config.AR == 1: # R2
            self._log("PrAcc: MIPS R2 I-cache sync")
            await self._pracc_sync_icache_r2(address)
        else:
            raise EJTAGError("cannot sync I-cache on unknown architecture release")

    # Public API / GDB remote implementation

    def gdb_log(self, level, message, *args):
        self._logger.log(level, "GDB: " + message, *args)

    def target_word_size(self):
        return self._ws

    def target_endianness(self):
        return "big"

    def target_triple(self):
        if self.target_endianness() == "big":
            return "mips-unknown-none"
        elif self.target_endianness() == "little":
            return "mipsel-unknown-none"
        else:
            assert False

    def target_register_names(self):
        reg_names  = ["${}".format(reg) for reg in range(32)]
        reg_names += ["sr", "lo", "hi", "bad", "cause", "pc"]
        return reg_names

    def target_running(self):
        return self._state == "Running"

    def target_attached(self):
        return not self.target_running() or any(self._instr_brkpts) or self._softw_brkpts

    async def target_stop(self):
        self._check_state("stop", "Running")
        await self._ejtag_debug_interrupt()
        await self._check_for_debug_interrupt()
        await self._pracc_debug_enter()

    async def target_continue(self):
        self._check_state("continue", "Stopped")
        await self._pracc_debug_return()
        if self._state == "Interrupted":
            await self._pracc_debug_enter()
            return

        while self._state == "Running":
            await asyncio.sleep(0.5)
            if await self._check_for_debug_interrupt():
                await self._pracc_debug_enter()

    async def target_single_step(self):
        self._check_state("single step", "Stopped")
        if self._cp0_debug.NoSSt:
            raise EJTAGError("target does not support single stepping")
        await self._pracc_single_step()

    async def target_detach(self):
        if self._state == "Running":
            await self.target_stop()
        for index, address in enumerate(self._instr_brkpts):
            if address is not None:
                await self._pracc_write_word(self._DRSEG_IBCn_addr(index), 0)
                self._instr_brkpts[index] = None
        for address, saved_instr in self._softw_brkpts.items():
            await self._pracc_write_word(address, self._softw_brkpts[address])
            await self._pracc_sync_icache(address)
        self._softw_brkpts = {}
        await self._pracc_debug_return()

    async def target_set_software_breakpt(self, address):
        self._check_state("set software breakpoint", "Stopped")
        if address in self._softw_brkpts:
            saved_instr = self._softw_brkpts[address]
        else:
            saved_instr = await self._pracc_read_word(address)
        await self._pracc_write_word(address, SDBBP())
        if await self._pracc_read_word(address) == SDBBP():
            await self._pracc_sync_icache(address)
            self._softw_brkpts[address] = saved_instr
            return True
        else:
            return False

    async def target_clear_software_breakpt(self, address):
        self._check_state("clear software breakpoint", "Stopped")
        if address in self._softw_brkpts:
            await self._pracc_write_word(address, self._softw_brkpts[address])
            await self._pracc_sync_icache(address)
            del self._softw_brkpts[address]
            return True
        else:
            return False

    async def target_set_instr_breakpt(self, address):
        self._check_state("set instruction breakpoint", "Stopped")
        for index in range(len(self._instr_brkpts)):
            if self._instr_brkpts[index] is None:
                await self._pracc_write_word(self._DRSEG_IBAn_addr(index), address)
                await self._pracc_write_word(self._DRSEG_IBMn_addr(index), 0)
                await self._pracc_write_word(self._DRSEG_IBCn_addr(index), DRSEG_IBC(1).to_int())
                self._instr_brkpts[index] = address
                return True
        else:
            return False

    async def target_clear_instr_breakpt(self, address):
        self._check_state("clear instruction breakpoint", "Stopped")
        for index in range(len(self._instr_brkpts)):
            if self._instr_brkpts[index] == address:
                await self._pracc_write_word(self._DRSEG_IBCn_addr(index), 0)
                self._instr_brkpts[index] = None
                return True
        else:
            return False

    async def target_get_registers(self):
        self._check_state("get registers", "Stopped")
        return await self._pracc_get_registers()

    async def target_set_registers(self, registers):
        self._check_state("get registers", "Stopped")
        await self._pracc_set_registers(registers)

    async def target_get_register(self, number):
        self._check_state("get register", "Stopped")
        if number in range(0, 32):
            return await self._pracc_get_gpr(number)
        elif number == 37:
            return await self._pracc_read_cp0(CP0_DEPC_addr)
        else:
            raise EJTAGError("getting register %d not supported" % number)

    async def target_set_register(self, number, value):
        self._check_state("set register", "Stopped")
        if number in range(0, 32):
            await self._pracc_set_gpr(number, value)
        elif number == 37:
            await self._pracc_write_cp0(CP0_DEPC_addr, value)
        else:
            raise EJTAGError("setting register %d not supported" % number)

    async def target_read_memory(self, address, length):
        self._check_state("read memory", "Stopped")
        if address % self._ws == 0 and length == self._ws:
            return struct.pack("<L", await self._pracc_read_word(address))
        else:
            return await self._pracc_read_memory(address, length)

    async def target_write_memory(self, address, data):
        self._check_state("write memory", "Stopped")
        if address % self._ws == 0 and len(data) == self._ws:
            await self._pracc_write_word(address, *struct.unpack("<L", data))
        else:
            await self._pracc_write_memory(address, data)


class DebugMIPSApplet(JTAGProbeApplet, name="debug-mips"):
    preview = True
    logger = logging.getLogger(__name__)
    help = "debug MIPS processors via EJTAG"
    description = """
    Debug MIPS processors via the EJTAG interface.

    This applet supports dumping CPU state, which is also useful to check if the CPU is recognized
    correctly, and running a GDB remote protocol server for a debugger. The supported debugger
    features are:

        * Starting, stopping and single-stepping.
        * Hardware and software breakpoints.
        * Register and memory reads and writes.

    Notable omissions include:

        * Floating point.
        * Tracepoints and watchpoints.

    The applet has been written with 32- and 64-bit CPUs with EJTAG 1.x-5.x in mind, but has only
    been tested with the following configurations:

        * MIPS32 R1 big endian with EJTAG 1.x/2.0 (Broadcom BCM6358);
        * MIPS32 R1 big endian with EJTAG 2.6 (Infineon ADM5120).

    Other configurations might or might not work. In particular, it certainly does not currently
    work on little-endian CPUs. Sorry about that.
    """

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)
        super().add_run_tap_arguments(parser)

    async def run(self, device, args):
        tap_iface = await self.run_tap(DebugMIPSApplet, device, args)
        return await EJTAGDebugInterface(tap_iface, self.logger)

    @classmethod
    def add_interact_arguments(cls, parser):
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

        p_dump_state = p_operation.add_parser(
            "dump-state", help="dump CPU state")

        p_gdb = p_operation.add_parser(
            "gdb", help="start a GDB remote protocol server")
        p_gdb.add_argument(
            "-1", "--once", default=False, action="store_true",
            help="exit when the remote client disconnects")
        ServerEndpoint.add_argument(p_gdb, "gdb_endpoint", default="tcp::1234")

        p_repl = p_operation.add_parser(
            "repl", help="drop into Python REPL and detach before exit")

    async def interact(self, device, args, ejtag_iface):
        if args.operation == "dump-state":
            await ejtag_iface.target_stop()
            reg_values = await ejtag_iface.target_get_registers()
            await ejtag_iface.target_detach()

            reg_names = ejtag_iface.target_register_names()
            for name, value in zip(reg_names, reg_values):
                print("{:<3} = {:08x}".format(name, value))

        if args.operation == "gdb":
            endpoint = await ServerEndpoint("GDB socket", self.logger, args.gdb_endpoint)
            while not args.once:
                await ejtag_iface.gdb_run(endpoint)

                # Unless we detach from the target here, we might not be able to re-enter
                # the debug mode, because EJTAG TAP reset appears to irreversibly destroy
                # some state necessary for PrAcc to continue working.
                if ejtag_iface.target_attached():
                    await ejtag_iface.target_detach()

    async def repl(self, device, args, ejtag_iface):
        await super().repl(device, args, ejtag_iface)

        # Same reason as above.
        if ejtag_iface.target_attached():
            await ejtag_iface.target_detach()
