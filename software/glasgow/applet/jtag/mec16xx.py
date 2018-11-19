# Ref: Microchip MEC1618 Low Power 32-bit Microcontroller with Embedded Flash
# Document Number: DS00002339A
# Ref: Microchip MEC1609 Mixed Signal Mobile Embedded Flash ARC EC BC-Link/VLPC Base Component
# Document Number: DS00002485A

import logging
import argparse
import struct

from .arc import JTAGARCApplet
from .. import *
from ...support.aobject import *
from ...pyrepl import *
from ...arch.arc import *
from ...arch.arc.mec16xx import *


FIRMWARE_SIZE = 0x30_000


class JTAGMEC16xxInterface(aobject):
    async def __init__(self, interface, logger):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        idcode, device = await self.lower.identify()
        if device is None or device.name != "ARC6xx":
            raise GlasgowAppletError("cannot operate on unknown device IDCODE=%08x"
                                     % idcode.to_int())

        self._log("halting CPU")
        await self.lower.set_halted(True)

    def _log(self, message, *args):
        self._logger.log(self._level, "MEC16xx: " + message, *args)

    async def read_firmware_mapped(self, size):
        words = []
        for offset in range(0, size, 4):
            self._log("read firmware mapped offset=%05x", offset)
            words.append(await self.lower.read(offset, space="memory"))
        return words

    async def emergency_flash_erase(self):
        tap_iface = self.lower.lower

        await tap_iface.write_ir(IR_RESET_TEST)
        dr_reset_test = DR_RESET_TEST(POR_EN=1)
        await tap_iface.write_dr(dr_reset_test.to_bitarray())
        dr_reset_test.VTR_POR = 1
        await tap_iface.write_dr(dr_reset_test.to_bitarray())
        dr_reset_test.ME = 1
        await tap_iface.write_dr(dr_reset_test.to_bitarray())
        dr_reset_test.VTR_POR = 0
        await tap_iface.write_dr(dr_reset_test.to_bitarray())


class JTAGMEC16xxApplet(JTAGARCApplet, name="jtag-mec16xx"):
    preview = True
    logger = logging.getLogger(__name__)
    help = "debug Microchip MEC16xx embedded controller via JTAG"
    description = """
    Debug Microchip MEC16xx/MEC16xxi embedded controller via the JTAG interface.
    """

    async def run(self, device, args):
        arc_iface = await super().run(device, args)
        return await JTAGMEC16xxInterface(arc_iface, self.logger)

    @classmethod
    def add_interact_arguments(cls, parser):
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION")

        p_emergency_erase = p_operation.add_parser(
            "emergency-erase", help="emergency erase firmware")

        p_read_firmware = p_operation.add_parser(
            "read-firmware", help="read EC firmware")
        p_read_firmware.add_argument(
            "file", metavar="FILE", type=argparse.FileType("wb"),
            help="write EC firmware to FILE")

        p_repl = p_operation.add_parser(
            "repl", help="drop into Python shell; use `mec_iface` to communicate")

    async def interact(self, device, args, mec_iface):
        if args.operation == "emergency-erase":
            await mec_iface.emergency_flash_erase()

        if args.operation == "read-firmware":
            for word in await mec_iface.read_firmware_mapped(size=FIRMWARE_SIZE):
                args.file.write(struct.pack("<L", word))

        if args.operation == "repl":
            await AsyncInteractiveConsole(locals={"mec_iface":mec_iface}).interact()
