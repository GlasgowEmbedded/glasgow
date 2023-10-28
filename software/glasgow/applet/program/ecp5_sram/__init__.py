# XXX: where is JTAG programming described?

import sys
import logging
import argparse

from ....arch.jtag import *
from ....arch.lattice.ecp5 import *
from ....support.bits import *
from ....support.logging import *
from ....database.jedec import *
from ....database.lattice.ecp5 import *
from ... import *
from ...interface.jtag_probe import JTAGProbeApplet


class ECP5JTAGError(GlasgowAppletError):
    pass


class ECP5JTAGInterface:
    def __init__(self, interface, logger):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

    def _log(self, message, *args):
        self._logger.log(self._level, f"ECP5: " + message, *args)

    async def identify(self):
        await self.lower.test_reset()
        await self.lower.write_ir(IR_IDCODE)
        idcode = DR_IDCODE.from_bits(await self.lower.read_dr(32))
        self._log("read id mfg-id=%03x part-id=%04x version=%01x",
                  idcode.mfg_id, idcode.part_id, idcode.version)
        return idcode, devices_by_idcode[idcode.to_int()]

    async def read_status(self):
        await self.lower.write_ir(IR_LSC_READ_STATUS)
        status = LSC_Status.from_bits(await self.lower.read_dr(32))
        self._log("status %s", status.bits_repr())
        return status

    async def programming_enable(self):
        self._log("programming enable")
        await self.lower.write_ir(IR_ISC_ENABLE)
        await self.lower.run_test_idle(10) # XXX verify timing

    async def programming_disable(self):
        self._log("programing disable")
        await self.lower.write_ir(IR_ISC_DISABLE)
        await self.lower.run_test_idle(10) # XXX verify timing

    async def load_bitstream(self, bitstream,
                             callback=lambda done, total: None):
        bitstream = bits(bitstream)
        self._log("load bitstream bit-length=%d", len(bitstream) * 8)

        # The FPGA expects bitstream bytes to be shifted in MSB-first.
        bitstream = bitstream.byte_reversed()

        # Enter bitstream burst load mode.
        await self.lower.write_ir(IR_LSC_BITSTREAM_BURST)

        # Send bitstream in medium sized chunks. This is faster because the JTAG probe currently
        # doesn't optimize the case of sending very large `bits` values well.
        await self.lower.enter_shift_dr()
        chunk_size = 4096
        for chunk_start in range(0, len(bitstream), chunk_size):
            callback(chunk_start, len(bitstream))
            await self.lower.shift_tdi(bitstream[chunk_start:chunk_start + chunk_size], last=False)
            await self.lower.flush()
        callback(len(bitstream), len(bitstream))
        await self.lower.shift_tdi(bits("00000000"), last=True) # dummy write to exit Shift-DR
        await self.lower.enter_update_dr()

    async def program_bitstream(self, bitstream,
                                callback=lambda done, total: None):
        await self.programming_enable()
        await self.load_bitstream(bitstream, callback=callback)
        await self.programming_disable()

        status = await self.read_status()
        if status.DONE:
            self._logger.info("FPGA successfully configured")
        else:
            error_code = BSE_Error_Code(status.BSE_Error_Code).explanation
            raise GlasgowAppletError(f"FPGA failed to configure: {error_code}")


class ProgramECP5SRAMApplet(JTAGProbeApplet):
    logger = logging.getLogger(__name__)
    help = "Program SRAM of ECP5 FPGAs via JTAG"
    description = """
    Program the volatile configuration memory of ECP5 FPGAs.
    """

    @staticmethod
    def _show_progress(done, total):
        if sys.stdout.isatty():
            sys.stdout.write("\r\033[0K")
            if done < total:
                sys.stdout.write(f"{done / total * 100:.0f}% complete")
            sys.stdout.flush()

    @classmethod
    def add_interact_arguments(cls, parser):
        parser.add_argument(
            "bitstream", metavar="BITSTREAM", type=argparse.FileType("rb"),
            help="bitstream file")

    async def run(self, device, args):
        jtag_iface = await self.run_lower(ProgramECP5SRAMApplet, device, args)
        return ECP5JTAGInterface(jtag_iface, self.logger)

    async def interact(self, device, args, ecp5_iface):
        idcode, ecp5_device = await ecp5_iface.identify()
        if ecp5_device is None:
            raise ECP5JTAGError("cannot operate on unknown device with IDCODE={:#10x}"
                                .format(idcode.to_int()))
        self.logger.info("found device %s", ecp5_device.name)

        await ecp5_iface.program_bitstream(args.bitstream.read(), callback=self._show_progress)

    @classmethod
    def tests(cls):
        from . import test
        return test.ProgramECP5SRAMAppletTestCase
