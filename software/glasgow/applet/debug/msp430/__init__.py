# Ref: MSP430™ Programming With the JTAG Interface
# Accession: G00038

# Bit order
# ---------
#
# For unknown reasons, DR values and captured IR value are bit reversed. However, IR opcodes are
# not bit reversed. This is quite confusing.
#
# Chip revisions
# --------------
#
# MSP430 has JTAG ID (one of: 0x89 0x91 0x98 0x99), "core" (one of: 430 430X 430Xv2), and
# "family" (one of: 1xx/2xx/4xx 5xx/6xx). None of these exactly correspond to each other, but
# knowing them is required to interact with the chip correctly.
#
# The JTAG IDs correspond to chip families as follows:
#   * JTAG ID 0x89: MSP430F1xx, MSP430F2xx, MSP430F4xx, MSP430Gxx, MSP430ixx
#   * JTAG ID 0x91: MSP430F5xx, MSP430F6xx, CC430, MSP430FR57xx
#   * JTAG ID 0x98: MSP430FR2xxx, MSP430FR41xx, MSP430FR50xx
#   * JTAG ID 0x99: MSP430FR58xx, MSP430FR59xx, MSP430FR6xxx
#
# All cores with JTAG IDs 0x91, 0x98, and 0x99 are "family 5xx/6xx" and "core 430Xv2". These cores
# have detailed device ID at word 0x1A04.
# Cores with JTAG ID 0x89 are "family 1xx/2xx/4xx" and "core 430" or "core 430X". These cores have
# detailed device ID at word 0x0FF0, and this allows distinguishing "core 430" and "core 430X".
#
# Chip detection
# --------------
#
# The DR CNTRL_SIG changes its layout depending on core version, with "core 430" and "core 430X"
# (aka "family 1xx/2xx/4xx") having one layout, and "core 430Xv2" having a different one. This
# register is required to do anything at all, so "family" is detected from JTAG ID. After this,
# the ReadMem command is enabled, and chip ID is read from memory. This information is sufficient
# to determine "core", which is then used to enable all commands including SetPC.

import logging
import asyncio
import struct

from ....support.aobject import *
from ....support.bits import *
from ....arch.msp430.jtag import *
from ...interface.jtag_probe import JTAGProbeApplet
from ...interface.sbw_probe import SpyBiWireProbeApplet
from ... import *


class MSP430DebugError(GlasgowAppletError):
    pass


class MSP430DebugInterface(aobject):
    async def __init__(self, interface, logger):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        self.jtag_id   = None
        self._family   = None
        self.device_id = None
        self._core     = None
        await self._probe_jtag()

    def _log(self, message, *args, level=None):
        self._logger.log(self._level if level is None else level, "MSP430: " + message, *args)

    async def _probe_jtag(self):
        await self.lower.test_reset()

        jtag_id_bits = await self.lower.read_ir(8)
        self.jtag_id = int(jtag_id_bits.reversed())
        if self.jtag_id not in (0x89, 0x91, 0x98, 0x99):
            raise MSP430DebugError("unknown JTAG ID {:#04x}".format(self.jtag_id))
        self._log("found core with JTAG ID %#04x", self.jtag_id,
                  level=logging.INFO)
        if self.jtag_id == 0x89:
            self._family = "124"
        else:
            self._family = "56"
        self._log("discover family=%s", self._family)
        # self._core will be set later, in target_stop().

    @property
    def _DR_CNTRL_SIG(self):
        if self._family == "124":
            return DR_CNTRL_SIG_124
        if self._family == "56":
            return DR_CNTRL_SIG_56
        assert False

    async def _write_control(self, **kwargs):
        if self._family == "124":
            cntrl_sig = self._DR_CNTRL_SIG(R_W=1, TAGFUNCSAT=1, TCE1=1)
        elif self._family == "56":
            raise NotImplementedError # FIXME
        else:
            assert False
        for arg, value in kwargs.items():
            setattr(cntrl_sig, arg, value)
        cntrl_sig_bits = cntrl_sig.to_bits()
        self._log("write CNTRL_SIG %s", cntrl_sig.bits_repr(omit_zero=True),
                  level=logging.TRACE)
        await self.lower.write_ir(IR_CNTRL_SIG_16BIT)
        await self.lower.write_dr(cntrl_sig_bits.reversed())

    async def _read_control(self):
        await self.lower.write_ir(IR_CNTRL_SIG_CAPTURE)
        cntrl_sig_bits = await self.lower.read_dr(16)
        cntrl_sig = self._DR_CNTRL_SIG.from_bits(cntrl_sig_bits.reversed())
        self._log("read CNTRL_SIG %s", cntrl_sig.bits_repr(omit_zero=True),
                  level=logging.TRACE)
        return cntrl_sig

    @property
    def _address_width(self):
        if self._family == "124":
            if self._core in (None, "430"):
                return 16
            if self.core in ("430X", "430Xv2"):
                return 20
        if self._family == "56":
            return 20
        assert False

    async def _write_address_dr(self, address):
        # FIXME: mangle address bits
        address_bits = bits(address & 0xfffff, self._address_width)
        await self.lower.write_dr(address_bits.reversed())

    async def _write_data_dr(self, data):
        data_bits = bits(data & 0xffff, 16)
        await self.lower.write_dr(data_bits.reversed())

    async def _read_data_dr(self):
        data_bits = await self.lower.read_dr(16)
        return int(data_bits.reversed())

    async def _ensure_instr_fetch(self):
        # Reference function: SetInstrFetch
        self._log("set mode=Instruction-Fetch")
        cntrl_sig = await self._read_control()
        attempts = 0
        while not cntrl_sig.INSTR_LOAD and attempts < 7:
            await self.lower.set_tclk(0)
            await self.lower.set_tclk(1)
            cntrl_sig = await self._read_control()
            attempts += 1
        if not cntrl_sig.INSTR_LOAD:
            # After a maximum of seven TCLK clocks, the CPU should be in the instruction-fetch
            # mode. If not (bit [INSTR_LOAD] = 1), a JTAG access error has occurred and a JTAG
            # reset is recommended.
            raise MSP430DebugError("target stuck in Instruction-Execute mode")

    async def _set_pc(self, pc_value):
        self._log("set pc=%#07x", pc_value)
        if self._core in ("430", "430X"):
            # Reference function: SetPC/SetPC_430X
            await self._ensure_instr_fetch()
            await self._write_control(RELEASE_LBYTE=1)
            await self._write_data_dr(0x4030) # FIXME
            await self.lower.set_tclk(0)
            await self.lower.set_tclk(1)
            await self._write_data_dr(pc_value)
            await self.lower.set_tclk(0)
            await self.lower.set_tclk(1)
            await self.lower.write_ir(IR_ADDR_CAPTURE)
            await self.lower.set_tclk(0)
            await self._write_control(RELEASE_LBYTE=0)
        elif self._core == "430Xv2":
            # Reference function: SetPC_430Xv2
            raise NotImplementedError # FIXME
        else:
            assert False

    async def _acquire_bus(self):
        # Reference function: HaltCPU
        assert self._family == "124"
        self._log("bus acquire")
        await self._ensure_instr_fetch()
        await self._write_data_dr(0x3FFF) # FIXME
        await self.lower.set_tclk(0)
        await self._write_control(HALT_JTAG=1)
        await self.lower.set_tclk(1)

    async def _release_bus(self):
        # Reference function: ReleaseCPU
        assert self._family == "124"
        self._log("bus release")
        await self.lower.set_tclk(0)
        await self._write_control()
        await self.lower.write_ir(IR_ADDR_CAPTURE)
        await self.lower.set_tclk(1)

    # Public API / GDB remote implementation

    def target_word_size(self):
        return 2

    def target_endianness(self):
        return "little"

    def target_triple(self):
        return "msp430"

    async def target_stop(self):
        self._log("target stop")
        if self._family == "124":
            # Reference function: GetDevice/GetDevice_430X
            await self._write_control(TCE1=1)
        elif self._family == "56":
            # Reference function: GetDevice_430Xv2
            raise NotImplementedError # FIXME
        else:
            assert False
        cntrl_sig = await self._read_control()
        if not cntrl_sig.TCE:
            raise MSP430DebugError("cannot stop target")
        if self.device_id is None:
            # And now we can determine which specific device it is.
            if self._family == "124":
                device_id_bytes = await self.target_read_memory(0x0ff0, 2)
            elif self._family == "56":
                device_id_bytes = await self.target_read_memory(0x1a04, 2)
            else:
                assert False
            self.device_id, = struct.unpack("<H", device_id_bytes)
            self._log("discover device-id=%#06x", self.device_id)
            if self._family == "124":
                self._core = "430" # FIXME
            elif self._family == "56":
                self._core = "430Xv2"
            else:
                assert False
            self._log("discover core=%s", self._core)
        self._log("attached to target %s (device ID %#06x, core %s)",
                  "???", self.device_id, self._core,
                  level=logging.INFO)

    async def target_reset(self):
        # Reference function: ExecutePOR
        self._log("target reset")
        await self._write_control(POR=1)
        await self._write_control(POR=0)
        await self.lower.set_tclk(0)
        await self.lower.set_tclk(1)
        await self.lower.set_tclk(0)
        await self.lower.set_tclk(1)
        await self.lower.set_tclk(0)
        await self.lower.write_ir(IR_ADDR_CAPTURE)
        await self.lower.set_tclk(1)

    async def target_detach(self, *, reset=False):
        if reset:
            self._log("target reset/detach")
        else:
            self._log("target detach")
        if self._family == "124":
            # Reference function: ReleaseDevice
            if reset:
                await self._write_control(POR=1)
                await self._write_control(POR=0)
            await self.lower.write_ir(IR_CNTRL_SIG_RELEASE)
            await self.lower.run_test_idle(0)
        elif self._family == "56":
            # Reference function: ReleaseDevice_430Xv2
            raise NotImplementedError # FIXME
        self._log("detached from target",
                  level=logging.INFO)

    async def target_read_memory(self, address, length):
        assert address % 2 == 0 and length % 2 == 0
        data = bytearray()
        if self._family == "124":
            # Reference function: ReadMem/ReadMem_430X
            await self._acquire_bus()
            await self.lower.set_tclk(0)
            await self._write_control(R_W=1, HALT_JTAG=1)
            offset = 0
            while offset < length:
                await self.lower.write_ir(IR_ADDR_16BIT)
                await self._write_address_dr(address + offset)
                await self.lower.write_ir(IR_DATA_TO_ADDR)
                await self.lower.set_tclk(1)
                await self.lower.set_tclk(0)
                data_word = await self._read_data_dr()
                self._log("read memory [%#07x]=%#06x", address + offset, data_word)
                data   += struct.pack("<H", data_word)
                offset += 2
            await self._release_bus()
        elif self._family == "56":
            # Reference function: ReadMem_430Xv2
            raise NotImplementedError # FIXME
        else:
            assert False
        return data

    async def target_write_memory(self, address, data):
        assert address % 2 == 0 and len(data) % 2 == 0
        if self._family == "124":
            # Reference function: WriteMem/WriteMem_430X
            await self._acquire_bus()
            await self.lower.set_tclk(0)
            await self._write_control(R_W=0, HALT_JTAG=1)
            offset = 0
            while offset < len(data):
                data_word = struct.unpack_from("<H", data, offset)
                self._log("write memory [%#07x]=%#06x", address + offset, data_word)
                await self.lower.set_tclk(0)
                await self.lower.write_ir(IR_ADDR_16BIT)
                await self._write_address_dr(address + offset)
                await self.lower.write_ir(IR_DATA_TO_ADDR)
                await self.lower.set_tclk(1)
                await self._write_data_dr(data_word)
                offset += 2
            await self._release_bus()
            return data
        elif self._family == "56":
            # Reference function: WriteMem_430Xv2
            raise NotImplementedError # FIXME
        else:
            assert False


class DebugMSP430AppletMixin:
    preview = True
    description = "" # nothing to add for now

    async def interact(self, device, args, msp430_iface):
        await msp430_iface.target_stop()
        await msp430_iface.target_detach(reset=True)


# To work correctly, this applet needs a sideband extension to:
#  a) enable JTAG when it is co-present with SBW, and
#  b) toggle TDI while holding TCK high.
# This is left to future readers.
#
# class DebugMSP430JTAGApplet(DebugMSP430AppletMixin, JTAGProbeApplet, name="debug-msp430-jtag"):
#     logger = logging.getLogger(__name__)
#     help = "debug MSP430 processors via JTAG"
#     description = """
#     Debug Texas Instruments MSP430 processors via the 4-wire JTAG interface.
#     """ + DebugMSP430AppletMixin.description
#
#     async def run(self, device, args):
#         jtag_iface = await self.run_lower(DebugMSP430JTAGApplet, device, args)
#         return await MSP430DebugInterface(jtag_iface, self.logger)


class DebugMSP430SBWApplet(DebugMSP430AppletMixin, SpyBiWireProbeApplet, name="debug-msp430-sbw"):
    logger = logging.getLogger(__name__)
    help = "debug MSP430 processors via Spy-Bi-Wire"
    description = """
    Debug Texas Instruments MSP430 processors via the 2-wire Spy-Bi-Wire interface.
    """ + DebugMSP430AppletMixin.description

    async def run(self, device, args):
        jtag_iface = await self.run_lower(DebugMSP430SBWApplet, device, args)
        return await MSP430DebugInterface(jtag_iface, self.logger)
