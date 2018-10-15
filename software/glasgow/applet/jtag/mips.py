# Ref: MIPS® EJTAG Specification
# Document Number: MD00047 Revision 6.10

import struct
import logging
import asyncio
from bitarray import bitarray

from . import JTAGApplet
from .. import *
from ...support.aobject import *
from ...support.endpoint import *
from ...pyrepl import *
from ...arch.mips import *
from ...arch.mips_ejtag import *
from ...protocol.gdb_remote import *


class EJTAGInterface(aobject, GDBRemote):
    async def __init__(self, interface, logger):
        self.lower    = interface
        self._logger  = logger
        self._level   = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._cursed  = False

        self._control = DR_CONTROL()
        self._state   = "Probe"
        await self._probe()

    def _log(self, message, *args):
        self._logger.log(self._level, "EJTAG: " + message, *args)

    def _check_state(self, action, *states):
        if self._state not in states:
            raise GlasgowAppletError("cannot %s: not in %s state" %
                                     (action, ", ".join(states)))

    def _change_state(self, state):
        self._log("set state %s", state)
        self._state = state

    # Low-level register manipulation

    async def _read_impcode(self):
        await self.lower.write_ir(IR_IMPCODE)
        impcode_bits = await self.lower.read_dr(32)
        self._impcode = DR_IMPCODE.from_bitarray(impcode_bits)
        self._log("read IMPCODE %s", self._impcode.bits_repr())

    async def _exchange_control(self, **fields):
        field_desc = " ".join("{}={:b}".format(field, value)
                              for field, value in fields.items())
        self._log("write CONTROL %s", field_desc)

        control = self._control.copy()
        control.Rocc  = 1
        control.PrAcc = 1
        for field, value in fields.items():
            setattr(control, field, value)
        control_bits = control.to_bitarray()
        await self.lower.write_ir(IR_CONTROL)

        control_bits = await self.lower.exchange_dr(control_bits)
        control = DR_CONTROL.from_bitarray(control_bits)
        self._log("read CONTROL %s", control.bits_repr(omit_zero=True))

        return control

    async def _enable_probe(self):
        self._control.ProbEn   = 1
        self._control.ProbTrap = 1
        for _ in range(3):
            control = await self._exchange_control()
            if control.ProbEn and control.ProbTrap: break
        else:
            raise GlasgowAppletError("ProbTrap/ProbEn stuck low")

    async def _scan_address_length(self):
        await self.lower.write_ir(IR_ADDRESS)
        self._address_length = await self.lower.scan_dr_length(max_length=64)
        assert self._address_length is not None

    async def _read_address(self):
        await self.lower.write_ir(IR_ADDRESS)
        address_bits = await self.lower.read_dr(self._address_length)
        address_bits.extend(address_bits[-1:] * (64 - self._address_length))
        address, = struct.unpack("<q", address_bits.tobytes())
        address &= self._mask
        self._log("read ADDRESS %#0.*x", self._prec, address)
        return address

    async def _write_address(self, address):
        # See _read_address. NB: ADDRESS is only writable in EJTAG v1.x/2.0 with DMAAcc.
        self._log("write ADDRESS %#0.*x", self._prec, address)
        address_bits = bitarray(endian="little")
        address_bits.frombytes(struct.pack("<Q", address))
        await self.lower.write_ir(IR_ADDRESS)
        await self.lower.write_dr(address_bits[:self._address_length])

    async def _read_data(self):
        await self.lower.write_ir(IR_DATA)
        data_bits = await self.lower.read_dr(self.bits)
        if self.bits == 32:
            data, = struct.unpack("<L", data_bits.tobytes())
        elif self.bits == 64:
            data, = struct.unpack("<Q", data_bits.tobytes())
        self._log("read DATA %#0.*x", self._prec, data)
        return data

    async def _write_data(self, data):
        self._log("write DATA %#0.*x", self._prec, data)
        await self.lower.write_ir(IR_DATA)
        data_bits = bitarray(endian="little")
        if self.bits == 32:
            data_bits.frombytes(struct.pack("<L", data))
        elif self.bits == 64:
            data_bits.frombytes(struct.pack("<Q", data))
        await self.lower.write_dr(data_bits)

    async def _dmaacc_read(self, address, size):
        self._log("DMAAcc: read address=%#0.*x size=%d", self._prec, address, size)
        await self._write_address(address)
        await self._exchange_control(DMAAcc=1, DRWn=1, Dsz=size, DStrt=1)
        for _ in range(3):
            control = await self._exchange_control(DMAAcc=1)
            if not control.DStrt: break
        else:
            raise GlasgowAppletError("DMAAcc: read hang")
        if control.DErr:
            raise GlasgowAppletError("DMAAcc: read error address=%#0.*x size=%d" %
                                     (self._prec, address, size))
        data = await self._read_data()
        self._log("DMAAcc: data=%#0.*x", self._prec, data)
        await self._exchange_control(DMAAcc=0)
        return data

    async def _dma_accwrite(self, address, size, data):
        self._log("DMAAcc: write address=%#0.*x size=%d data=%#0.*x",
                  self._prec, address, size, self._prec, data)
        await self._write_address(address)
        await self._write_data(data)
        await self._exchange_control(DMAAcc=1, DRWn=0, Dsz=size, DStrt=1)
        for _ in range(3):
            control = await self._exchange_control(DMAAcc=1)
            if not control.DStrt: break
        else:
            raise GlasgowAppletError("DMAAcc: write hang")
        if control.DErr:
            raise GlasgowAppletError("DMAAcc: write error address=%#0.*x size=%d" %
                                     (self._prec, address, size))
        await self._exchange_control(DMAAcc=0)

    # Target state management

    async def _probe(self):
        self._check_state("probe", "Probe")

        await self._read_impcode()
        await self._scan_address_length()
        await self._enable_probe()

        self.bits      = 64 if self._impcode.MIPS32_64 else 32
        self._prec     = self.bits // 4
        self._ws       = self.bits // 8
        self._mask     = ((1 << self.bits) - 1)
        self.cpunum    = self._impcode.TypeInfo
        self.ejtag_ver = EJTAGver_values[self._impcode.EJTAGver]

        control = await self._exchange_control()
        if control.DM:
            raise GlasgowAppletError("target already in debug mode")
        else:
            self._change_state("Running")

    async def _ejtag_debug_interrupt(self):
        self._check_state("assert debug interrupt", "Running")

        if self.ejtag_ver == "1.x/2.0":
            if not self._cursed:
                self._cursed = True
                self._logger.warning("found cursed EJTAG 1.x/2.0 CPU, using undocumented "
                                     "DCR.MP workaround")
            # Undocumented sequence to disable memory protection for dmseg. The bit 2 is
            # documented as NMIpend, but on EJTAG 1.x/2.0 it is actually MP. It is only possible
            # to clear it via DMAAcc because PrAcc requires debug mode to already work.
            dcr  = await self._dmaacc_read(DRSEG_DCR_addr, 2)
            dcr &= ~(1<<2)
            await self._dma_accwrite(DRSEG_DCR_addr, 2, dcr)

        await self._exchange_control(EjtagBrk=1)
        control = await self._exchange_control()
        if control.EjtagBrk:
            raise GlasgowAppletError("failed to enter debug mode")

        self._change_state("Interrupted")

    async def _exec_pracc(self, code, data=[], max_steps=1024, state="Stopped"):
        self._check_state("execute PrAcc", state)
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
                    raise GlasgowAppletError("PrAcc: DM low on entry")
                elif not control.DM:
                    self._log("PrAcc: debug return")
                    self._change_state("Running")
                    return
                elif control.PrAcc:
                    break
            else:
                raise GlasgowAppletError("PrAcc: PrAcc stuck low")

            address = await self._read_address()
            if step > 0 and address == code_beg:
                self._log("PrAcc: debug suspend")
                self._change_state("Stopped")
                break

            if address in range(code_beg, code_end):
                area, area_beg, area_wr, area_name = code, code_beg, False, "code"
            elif address in range(temp_beg, temp_end):
                area, area_beg, area_wr, area_name = temp, temp_beg, True,  "temp"
            elif address in range(data_beg, data_end):
                area, area_beg, area_wr, area_name = data, data_beg, True,  "data"
            else:
                raise GlasgowAppletError("PrAcc: address %#0.*x out of range" %
                                         (self._prec, address))

            area_off = (address - area_beg) // 4
            if control.PRnW:
                if not area_wr:
                    raise GlasgowAppletError("PrAcc: write access to %s at %#0.*x" %
                                             (area_name, self._prec, address))

                word = await self._read_data()
                self._log("PrAcc: write %s [%#06x] = %#0.*x",
                          area_name, address & 0xffff, self._prec, word)
                area[area_off] = word
            else:
                self._log("PrAcc: read %s [%#06x] = %#0.*x",
                          area_name, address & 0xffff, self._prec, area[area_off])
                await self._write_data(area[area_off])

            await self._exchange_control(PrAcc=0)

        else:
            raise GlasgowAppletError("PrAcc: step limit exceeded")

        return data

    # PrAcc fragment runners

    async def _pracc_prologue(self):
        Rdata, *_ = range(1, 32)
        await self._exec_pracc(state="Interrupted", code=[
            MTC0 (Rdata, *CP0_DESAVE_addr),
            LUI  (Rdata, 0xff20),
            ORI  (Rdata, Rdata, 0x1200),
            B    (-4),
            NOP  (),
            NOP  (),
        ])

    async def _pracc_epilogue(self):
        Rdata, *_ = range(1, 32)
        await self._exec_pracc(code=[
            MFC0 (Rdata, *CP0_DESAVE_addr),
            DERET(),
            NOP  (),
            NOP  (),
            NOP  (),
        ])

    async def _pracc_read_regs(self):
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
            B    (-47),
            NOP  (),
            NOP  (),
        ], data=[0] * 38)

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
            B    (-10),
            NOP  (),
            NOP  (),
        ], data=[value]))[0]

    async def _pracc_read_word(self, address):
        return await self._pracc_copy_word(address, value=0, is_read=True)

    async def _pracc_write_word(self, address, value):
        return await self._pracc_copy_word(address, value, is_read=False)

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
            LBU  (Racc, 0, Rsrc),
            ADDI (Rsrc, Rsrc, 1),
            SW   (Racc, 0, Rdst),
            ADDI (Rdst, Rdst, 4),
            ADDI (Rlen, Rlen, -1),
            BGTZ (Rlen, -6),
            NOP  (),
            LW   (Racc, self._ws * -4, Rdata),
            LW   (Rlen, self._ws * -3, Rdata),
            LW   (Rsrc, self._ws * -2, Rdata),
            LW   (Rdst, self._ws * -1, Rdata),
            NOP  (),
            B    (-22),
            NOP  (),
            NOP  (),
        ], data=data)

    async def _pracc_read_memory(self, address, length):
        data = await self._pracc_copy_memory(address, length, data=[0] * length, is_read=True)
        return bytes(data)

    async def _pracc_write_memory(self, address, data):
        await self._pracc_copy_memory(address, len(data), [*data], is_read=False)

    # Public API / GDB remote implementation

    def gdb_log(self, level, message, *args):
        self._logger.log(level, "GDB: " + message, *args)

    def target_word_size(self):
        return self._ws

    def target_endianness(self):
        return "big"

    def target_triple(self):
        return "mipsel-unknown-none"

    def target_register_names(self):
        reg_names  = ["${}".format(reg) for reg in range(32)]
        reg_names += ["sr", "lo", "hi", "bad", "cause", "pc"]
        return reg_names

    def target_running(self):
        return self._state == "Running"

    async def target_stop(self):
        self._check_state("stop", "Running")
        await self._ejtag_debug_interrupt()
        await self._pracc_prologue()

    async def target_resume(self):
        self._check_state("resume", "Stopped")
        await self._pracc_epilogue()

    async def target_get_all_registers(self):
        self._check_state("get all registers", "Stopped")
        return await self._pracc_read_regs()

    async def target_read_memory(self, address, length):
        self._check_state("read memory", "Stopped")
        return await self._pracc_read_memory(address, length)


class JTAGMIPSApplet(JTAGApplet, name="jtag-mips"):
    preview = True
    logger = logging.getLogger(__name__)
    help = "debug MIPS processors via EJTAG"
    description = """
    TBD
    """

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)

        parser.add_argument(
            "tap_index", metavar="INDEX", type=int, default=0, nargs="?",
            help="select TAP #INDEX for communication (default: %(default)s)")

    async def run(self, device, args):
        jtag_iface = await super().run(device, args)
        await jtag_iface.pulse_trst()

        tap_iface = await jtag_iface.select_tap(args.tap_index)
        if not tap_iface:
            raise GlasgowAppletError("cannot select TAP #%d" % args.tap_index)

        return await EJTAGInterface(tap_iface, self.logger)

    @classmethod
    def add_interact_arguments(cls, parser):
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION")

        p_registers = p_operation.add_parser(
            "registers", help="dump registers")

        p_gdb = p_operation.add_parser(
            "gdb", help="start a GDB remote protocol server")
        ServerEndpoint.add_argument(p_gdb, "gdb_endpoint", default="tcp::1234")

        p_repl = p_operation.add_parser(
            "repl", help="drop into Python shell; use `ejtag_iface` to communicate")

    async def interact(self, device, args, ejtag_iface):
        self.logger.info("found MIPS%d CPU %#x (EJTAG version %s)",
                         ejtag_iface.bits, ejtag_iface.cpunum, ejtag_iface.ejtag_ver)

        if args.operation == "registers":
            await ejtag_iface.target_stop()
            reg_values = await ejtag_iface.target_get_all_registers()
            await ejtag_iface.target_resume()

            reg_names = ejtag_iface.target_register_names()
            for name, value in zip(reg_names, reg_values):
                print("{:<3} = {:08x}".format(name, value))

        if args.operation == "gdb":
            endpoint = await ServerEndpoint("GDB socket", self.logger, args.gdb_endpoint)
            await ejtag_iface.gdb_run(endpoint)

        if args.operation == "repl":
            await AsyncInteractiveConsole(locals={"ejtag_iface":ejtag_iface}).interact()

        # Unless we resume the target here, we might not be able to re-enter the debug
        # mode, because EJTAG TAP reset appears to irreversibly destroy some state
        # necessary for PrAcc to continue working.
        if not ejtag_iface.target_running():
            await ejtag_iface.target_resume()
