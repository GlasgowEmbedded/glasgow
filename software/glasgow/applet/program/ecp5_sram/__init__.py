import argparse
import asyncio
import logging
import struct
from bitarray import bitarray
from nmigen.compat import *

from ....arch.jtag import *
from ....support.bits import *
from ....support.logging import *
from ....protocol.jtag_svf import *
from ....database.jedec import *
from ... import *
from ...interface.jtag_probe import JTAGProbeApplet, JTAGProbeStateTransitionError

READ_ID =             bits.from_int(0xE0,8)
LSC_READ_STATUS =     bits.from_int(0x3C,8)
ISC_ENABLE =          bits.from_int(0xC6,8)
ISC_DISABLE =         bits.from_int(0x26,8)
ISC_ERASE =           bits.from_int(0x0E,8)
LSC_BITSTREAM_BURST = bits.from_int(0x7A,8)


ECP5_FAMILY_IDCODES = {
	0x21111043 : "LFE5U-12"   ,
	0x41111043 : "LFE5U-25"   ,
	0x41112043 : "LFE5U-45"   ,
	0x41113043 : "LFE5U-85"   ,
	0x01111043 : "LFE5UM-25"  ,
	0x01112043 : "LFE5UM-45"  ,
	0x01113043 : "LFE5UM-85"  ,
	0x81111043 : "LFE5UM5G-25",
	0x81112043 : "LFE5UM5G-45",
	0x81113043 : "LFE5UM5G-85"
}

class ProgramECP5SRAMInterface:
    def __init__(self, interface, logger, frequency):
        self.lower   = interface
        self.logger = logger
        self._level  = logging.DEBUG if self.logger.name == __name__ else logging.TRACE

    async def read_IDCODE(self):
        await self.lower.test_reset()
        await self.lower.write_ir(READ_ID)
        raw_bits = await self.lower.read_dr(32)
        idcode = struct.unpack("<I", raw_bits.to_bytes())[0]
        return idcode
        
    async def check_IDCODE(self):
        idcode_value = await self.read_IDCODE()
        idcode   = DR_IDCODE.from_int(idcode_value)
        mfg_name = jedec_mfg_name_from_bank_num(idcode.mfg_id >> 7,
                                                idcode.mfg_id & 0x7f) or \
                        "unknown"
        self.logger.info("manufacturer=%#05x (%s) part=%#06x version=%#03x",
                            idcode.mfg_id, mfg_name, idcode.part_id, idcode.version)
        # Decode to actual ECP5 devices 
        try:
            device = ECP5_FAMILY_IDCODES[idcode_value]
            self.logger.info("Found Device: %s", device)
        except:
            self.logger.error("IDCODE 0x%08X does not mtach ECP5 device", idcode_value)



    async def read_STATUS(self):
        await self.lower.write_ir(LSC_READ_STATUS)
        raw_bits = await self.lower.read_dr(32)
        status = struct.unpack("<I", raw_bits.to_bytes())[0]
        return status

    async def check_STATUS(self):
        status = await self.read_STATUS()
        self.logger.info("Status Register: 0x%08X", status)
        self.logger.debug("  Transparent Mode:   %s", {True : "Yes", False : "No"}[status & (1 << 0)] )
        self.logger.debug("  Config Target:      %s", {True : "eFuse"   , False : "SRAM"}[(status & (7 << 1)) > 0])
        self.logger.debug("  Read Enable:        %s", {True : "Readable", False : "Not Readable"}[status & (1 << 11) != 0] )
        self.logger.debug("  Write Enable:       %s", {True : "Writable", False : "Not Writable"}[status & (1 << 10) != 0] )
        self.logger.debug("  JTAG Active:        %s", {True: "Yes", False: "No"}[status & (1 << 4)  != 0] )
        self.logger.debug("  PWD Protection:     %s", {True: "Yes", False: "No"}[status & (1 << 5)  != 0] )
        self.logger.debug("  Decrypt Enable:     %s", {True: "Yes", False: "No"}[status & (1 << 7)  != 0] )
        self.logger.debug("  DONE:               %s", {True: "Yes", False: "No"}[status & (1 << 8)  != 0] )
        self.logger.debug("  ISC Enable:         %s", {True: "Yes", False: "No"}[status & (1 << 9)  != 0] )
        self.logger.debug("  Busy Flag:          %s", {True: "Yes", False: "No"}[status & (1 << 12) != 0] )
        self.logger.debug("  Fail Flag:          %s", {True: "Yes", False: "No"}[status & (1 << 13) != 0] )
        self.logger.debug("  Feature OTP:        %s", {True: "Yes", False: "No"}[status & (1 << 14) != 0] )
        self.logger.debug("  Decrypt Only:       %s", {True: "Yes", False: "No"}[status & (1 << 15) != 0] )
        self.logger.debug("  PWD Enable:         %s", {True: "Yes", False: "No"}[status & (1 << 16) != 0] )
        self.logger.debug("  Encrypt Preamble:   %s", {True: "Yes", False: "No"}[status & (1 << 20) != 0] )
        self.logger.debug("  Std Preamble:       %s", {True: "Yes", False: "No"}[status & (1 << 21) != 0] )
        self.logger.debug("  SPIm Fail 1:        %s", {True: "Yes", False: "No"}[status & (1 << 22) != 0] )
        self.logger.debug("  Execution Error:    %s", {True: "Yes", False: "No"}[status & (1 << 26) != 0] )
        self.logger.debug("  ID Error:           %s", {True: "Yes", False: "No"}[status & (1 << 27) != 0] )
        self.logger.debug("  Invalid Command:    %s", {True: "Yes", False: "No"}[status & (1 << 28) != 0] )
        self.logger.debug("  SED Error:          %s", {True: "Yes", False: "No"}[status & (1 << 29) != 0] )
        self.logger.debug("  Bypass Mode:        %s", {True: "Yes", False: "No"}[status & (1 << 30) != 0] )
        self.logger.debug("  Flow Through Mode:  %s", {True: "Yes", False: "No"}[status & (1 << 31) != 0] )
		
        bse_error = (status & (7 << 23)) >> 23
        self.logger.debug("  Flow Through Mode:  %s",{
                0b000: "No Error (0b000)",
                0b001: "ID Error (0b001)",
                0b010: "CMD Error - illegal command (0b010)",
                0b011: "CRC Error (0b011)",
                0b100: "PRMB Error - preamble error (0b100)",
                0b101: "ABRT Error - configuration aborted by the user (0b101)",
                0b110: "OVFL Error - data overflow error (0b110)",
                0b111: "SDM Error - bitstream pass the size of SRAM array (0b111)",
            }[bse_error])

    def reverse(self, a,size):
        b = 0
        for i in range(size):
            b <<= 1
            b |= a >> i & 1
        return b

    async def program(self, bitstream):
        await self.check_IDCODE()
        await self.check_STATUS()

        # perform programming
        await self.lower.write_ir(ISC_ENABLE)
        await self.lower.run_test_idle(10)
        await self.lower.write_ir(LSC_BITSTREAM_BURST)

        # Send entire bitstream data into DR,
        # Bytes are expected MSB by the ECP5, so need to be reversed
        await self.lower.enter_shift_dr()
        for b in bitstream:
            b = self.reverse(b, 8) 
            await self.lower.shift_tdi(bits.from_int(b, 8), last=False)
        await self.lower.enter_update_dr()
        
        
        await self.lower.write_ir(ISC_DISABLE)
        await self.lower.run_test_idle(10)

        # Check status
        # Note ECP5 will not release until STATUS is read
        await self.check_STATUS()
        




class ProgramECP5SRAMApplet(JTAGProbeApplet, name="program-ecp5-sram"):
    logger = logging.getLogger(__name__)
    help = "Program ECP5 configuration sram via JTAG"
    description = """
    TODO
    """

    @classmethod
    def add_interact_arguments(cls, parser):
        parser.add_argument(
            "bitstream", metavar="BITSTREAM", type=argparse.FileType("rb"),
            help="bitstream file")

    async def run(self, device, args):
        jtag_iface = await self.run_lower(ProgramECP5SRAMApplet, device, args)
        return ProgramECP5SRAMInterface(jtag_iface, self.logger, args.frequency * 1000)

    async def interact(self, device, args, ecp5_iface):
        bitstream = args.bitstream.read()
        await ecp5_iface.program(bitstream)