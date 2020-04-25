import argparse
import asyncio
import logging
import struct

from ....arch.jtag import *
from ....arch.lattice.ecp5 import *
from ....support.bits import *
from ....support.logging import *
from ....database.jedec import *
from ....database.lattice.ecp5 import *
from ... import *
from ...interface.jtag_probe import JTAGProbeApplet, JTAGProbeStateTransitionError


class ProgramECP5SRAMInterface:
    def __init__(self, interface, logger, frequency):
        self.lower   = interface
        self.logger = logger
        self._level  = logging.DEBUG if self.logger.name == __name__ else logging.TRACE

    async def _read_IDCODE(self):
        await self.lower.test_reset()
        await self.lower.write_ir(IR_READ_ID)
        raw_bits = await self.lower.read_dr(32)
        idcode = struct.unpack("<I", raw_bits.to_bytes())[0]
        return idcode
        
    async def _read_STATUS(self):
        await self.lower.write_ir(IR_LSC_READ_STATUS)
        raw_bits = await self.lower.read_dr(32)
        status_value = struct.unpack("<I", raw_bits.to_bytes())[0]
        status = LSC_Status.from_int(status_value)
        return status

    async def identify(self):
        idcode_value = await self._read_IDCODE()
        idcode   = DR_IDCODE.from_int(idcode_value)
        mfg_name = jedec_mfg_name_from_bank_num(idcode.mfg_id >> 7,
                                                idcode.mfg_id & 0x7f) or \
                        "unknown"
        self.logger.info("manufacturer=%#05x (%s) part=%#06x version=%#03x",
                            idcode.mfg_id, mfg_name, idcode.part_id, idcode.version)
        # Decode to actual ECP5 devices 
        try:
            device = devices_by_idcode[idcode_value]
            self.logger.info("Found Device: %s", device)
        except:
            self.logger.error("IDCODE 0x%08X does not mtach ECP5 device", idcode_value)


    async def check_STATUS(self, status):
        self.logger.info("Status Register: 0x%08X", status.to_int())
        self.logger.info(" %s", status)
    

    def reverse(self, a,size):
        b = 0
        for i in range(size):
            b <<= 1
            b |= a >> i & 1
        return b

    async def program(self, bitstream):
        await self.identify()

        # perform programming
        await self.lower.write_ir(IR_ISC_ENABLE)
        await self.lower.run_test_idle(10)
        await self.lower.write_ir(IR_LSC_BITSTREAM_BURST)

        # Send entire bitstream data into DR,
        # Bytes are expected MSB by the ECP5, so need to be reversed
        await self.lower.enter_shift_dr()
        for b in bitstream:
            b = self.reverse(b, 8) 
            await self.lower.shift_tdi(bits.from_int(b, 8), last=False)
        await self.lower.enter_update_dr()
        
        
        await self.lower.write_ir(IR_ISC_DISABLE)
        await self.lower.run_test_idle(10)

        # Check status
        # Note ECP5 will not release until STATUS is read
        status = await self._read_STATUS()

        if status.DONE:
            self.logger.info("Configuration Done")
        else:
            self.check_STATUS(status)

        


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