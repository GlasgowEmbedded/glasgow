# Ref: Spartan-6 FPGA Configuration User Guide
# Document Number: UG380
# Accession: G00039

# Note: when polling INIT_B and DONE status, the IR shifted in should not be BYPASS to avoid race
# conditions. Shifting BYPASS in would activate the normal configuration logic, which can cause
# failure to program or even a corrupted bitstream (if a bitstream is loaded from memory on top
# of the one loaded from JTAG).

import logging
import argparse
from bitarray import bitarray
from nmigen.compat import *

from ... import *
from ....arch.jtag import *
from ....arch.xilinx.xc6s import *
from ....database.xilinx.xc6s import *
from ....support.bits import *
from ...interface.jtag_probe import JTAGProbeApplet


class XC6SJTAGError(GlasgowAppletError):
    pass


class XC6SJTAGInterface:
    def __init__(self, interface, logger):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

    def _log(self, message, *args):
        self._logger.log(self._level, "XC6S: " + message, *args)

    async def identify(self):
        await self.lower.test_reset()
        idcode = DR_IDCODE.from_bits(await self.lower.read_dr(32))
        self._log("read idcode mfg-id=%03x part-id=%04x", idcode.mfg_id, idcode.part_id)
        return idcode, devices_by_idcode[idcode.mfg_id, idcode.part_id]

    async def _status(self, ir=IR_BYPASS):
        status = IR_CAPTURE.from_bits(await self.lower.exchange_ir(ir))
        self._log("status %s", status.bits_repr())
        return status

    async def _poll(self, ir, limit):
        status = await self._status(ir)
        for attempt in range(limit):
            yield (await self._status(ir))

    async def reconfigure(self):
        self._log("reconfigure")
        await self.lower.write_ir(IR_JPROGRAM)
        async for status in self._poll(IR_CFG_IN, limit=16):
            if status.INIT_B:
                return
        raise GlasgowAppletError("configuration reset failed: {}".format(status.bits_repr()))

    async def load_bitstream(self, bitstream, *, byte_reverse=True):
        if byte_reverse:
            ba = bitarray()
            ba.frombytes(bitstream)
            ba.bytereverse()
            bitstream = bits(ba.tobytes(), len(ba))
        else:
            bitstream = bits(bitstream)
        self._log("load size=%d [bits]", len(bitstream))
        await self.lower.lower.write_ir(IR_CFG_IN)
        await self.lower.write_dr(bitstream)

    async def start(self):
        self._log("start")
        # Poll ISC_DONE, which corresponds to EOS, not DONE, which can be activated anywhere
        # during the configuration depending on the bitstream.
        async for status in self._poll(IR_JSTART, limit=4):
            await self.lower.run_test_idle(16)
            if status.ISC_DONE:
                return
        raise GlasgowAppletError("configuration start failed: {}".format(status.bits_repr()))


class ProgramXC6SApplet(JTAGProbeApplet, name="program-xc6s"):
    logger = logging.getLogger(__name__)
    help = "program Xilinx Spartan-6 FPGAs via JTAG"
    preview = True
    description = """
    Program Xilinx Spartan-6 FPGAs via the JTAG interface.
    """

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)
        super().add_run_tap_arguments(parser)

    async def run(self, device, args):
        tap_iface = await self.run_tap(ProgramXC6SApplet, device, args)
        return XC6SJTAGInterface(tap_iface, self.logger)

    @classmethod
    def add_interact_arguments(cls, parser):
        parser.add_argument(
            "bit_file", metavar="BIT-FILE", type=argparse.FileType("rb"), nargs="?",
            help="load bitstream from .bin file BIT-FILE")

    async def interact(self, device, args, xc6s_iface):
        idcode, xc6s_device = await xc6s_iface.identify()
        if xc6s_device is None:
            raise XC6SJTAGError("cannot operate on unknown device with IDCODE={:#10x}"
                                .format(idcode.to_int()))
        self.logger.info("found %s rev=%d", xc6s_device.name, idcode.version)

        if args.bit_file:
            self.logger.info("configuring from %r", args.bit_file.name)
            await xc6s_iface.reconfigure()
            await xc6s_iface.load_bitstream(args.bit_file.read())
            await xc6s_iface.start()
