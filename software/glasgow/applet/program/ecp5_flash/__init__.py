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
from ..ecp5_sram import ProgramECP5SRAMInterface
from ....applet.memory._25x import Memory25xInterface, Memory25xApplet, Memory25xSFDPParser


class ProgramECP5FLASHInterface(Memory25xInterface, ProgramECP5SRAMInterface):
    def __init__(self, interface, logger):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

    # Overwrite _command, to direct bits out into a JTAG-DR. 
    # The ECP5 then takes care of outputing data over SPI
    async def _command(self, cmd, arg=[], dummy=0, ret=0):
        arg = bytes(arg)

        self._log("cmd=%02X arg=<%s> dummy=%d ret=%d", cmd, dump_hex(arg), dummy, ret)

        # CS will remain LOW while we are in SHIFT_DR state 
        await self.lower.enter_shift_dr()

        input_bytes = bytearray([cmd, *arg, *[0 for _ in range(dummy)]])
        bits_to_send = bits()
        for b in input_bytes:
            bits_to_send += bits.from_int(b, 8).reversed()

        await self.lower.shift_tdi(bits_to_send, last=(ret == 0))

        if ret > 0:
            tdo_bits = await self.lower.shift_tdo(ret*8)
        
        # Release CS pin
        await self.lower.enter_pause_dr()

        # Reverse bits in every byte to fix LSB bit order of JTAG
        if ret > 0:
            tdo_bytes = [tdo_bits[i:i + 8] for i in range(0, len(tdo_bits), 8)]
            result = []

            for b in tdo_bytes:
                result.append(b.reversed().to_int())

            self._log("result=<%s>", dump_hex(result))

            return bytearray(result)
        return None

    async def _enter_spi_background_mode(self):
        # Erase currently configured bitstream
        await self.lower.write_ir(IR_ISC_ENABLE)
        await self.lower.run_test_idle(100)

        await self.lower.write_ir(IR_ISC_ERASE)
        await self.lower.write_dr(bits.from_int(0,8))
        await self.lower.run_test_idle(100)

        await self.lower.write_ir(IR_ISC_DISABLE)
        await self.lower.run_test_idle(100)

        # Enable background SPI
        await self.lower.write_ir(IR_LSC_BACKGROUD_SPI)
        await self.lower.write_dr(bits.from_int(0x68FE,16))
        await self.lower.run_test_idle(100)


class ProgramECP5FLASHApplet(JTAGProbeApplet, name="program-ecp5-flash"):
    logger = logging.getLogger(__name__)
    help = "Program ECP5 configuration SPI FLASH via JTAG"
    description = """
    Program the non-volatile configuration memory of a SPI FLASH chip connected to a ECP5 FPGAs
    """

    @classmethod
    def add_interact_arguments(cls, parser):
        Memory25xApplet.add_interact_arguments(parser)

        # TODO:: Add options for SRAM erase before programming, toggle REFRESH ofter complete, check status, etc.

    async def run(self, device, args):
        ecp5_iface = await self.run_lower(ProgramECP5FLASHApplet, device, args)
        return ProgramECP5FLASHInterface(ecp5_iface, self.logger)

    async def interact(self, device, args, ecp5_iface):
        #bitstream = args.bitstream.read()
        await ecp5_iface.identify()
        await ecp5_iface._enter_spi_background_mode()
        await Memory25xApplet().interact(device, args, ecp5_iface)