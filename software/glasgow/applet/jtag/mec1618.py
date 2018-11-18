# Ref: Microchip MEC1618/MEC1618i Low Power 32-bit Microcontroller with Embedded Flash
# Document Number: DS00002339A

import logging
import argparse
import struct

from .arc import JTAGARCApplet
from .. import *
from ...support.aobject import *
from ...pyrepl import *
from ...arch.arc import *


FIRMWARE_SIZE = 0x30_000


class JTAGMEC1618Interface(aobject):
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
        self._logger.log(self._level, "MEC1618: " + message, *args)

    async def read_firmware(self):
        words = []
        for offset in range(0, FIRMWARE_SIZE, 4):
            self._log("read firmware offset=%05x", offset)
            words.append(await self.lower.read(offset, space="memory"))
        return words


class JTAGMEC1618Applet(JTAGARCApplet, name="jtag-mec1618"):
    preview = True
    logger = logging.getLogger(__name__)
    help = "debug Microchip MEC1618 embedded controller via JTAG"
    description = """
    Debug Microchip MEC1618/MEC1618i embedded controller via the JTAG interface.
    """

    async def run(self, device, args):
        arc_iface = await super().run(device, args)
        return await JTAGMEC1618Interface(arc_iface, self.logger)

    @classmethod
    def add_interact_arguments(cls, parser):
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION")

        p_read_firmware = p_operation.add_parser(
            "read-firmware", help="read EC firmware")
        p_read_firmware.add_argument(
            "file", metavar="FILE", type=argparse.FileType("wb"),
            help="write EC firmware to FILE")

        p_repl = p_operation.add_parser(
            "repl", help="drop into Python shell; use `mec_iface` to communicate")

    async def interact(self, device, args, mec_iface):
        if args.operation == "read-firmware":
            for word in await mec_iface.read_firmware():
                args.file.write(struct.pack("<L", word))

        if args.operation == "repl":
            await AsyncInteractiveConsole(locals={"mec_iface":mec_iface}).interact()
