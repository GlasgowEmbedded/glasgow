import logging
from collections import defaultdict
from bitarray import bitarray

from . import JTAGApplet
from .. import *
from ...support.bits import *
from ...support.aobject import *


IR_IMPCODE    = bitarray("11000", endian="little")
IR_ADDRESS    = bitarray("00010", endian="little")
IR_DATA       = bitarray("10010", endian="little")
IR_CONTROL    = bitarray("01010", endian="little")
IR_ALL        = bitarray("11010", endian="little")
IR_EJTAGBOOT  = bitarray("00110", endian="little")
IR_NORMALBOOT = bitarray("10110", endian="little")
IR_FASTDATA   = bitarray("01110", endian="little")
IR_PCSAMPLE   = bitarray("00101", endian="little")
IR_FDC        = bitarray("11101", endian="little")


EJTAGver_values = defaultdict(lambda: "reserved", {
    0: "1/2.0",
    1: "2.5",
    2: "2.6",
    3: "3.1",
    4: "4.0",
    5: "5.0",
})


IMPCODE = Bitfield("IMPCODE", 4, [
    ("MIPS32_64",  1),
    ("TypeInfo",  10),
    ("Type",       2),
    ("NoDMA",      1),
    (None,         1),
    ("MIPS16",     1),
    (None,         3),
    ("ASID_Size",  2),
    (None,         1),
    ("DINT_sup",   1),
    (None,         3),
    ("R4k_R3k",    1),
    ("EJTAGver",   3),
])


class EJTAGInterface(aobject):
    async def __init__(self, interface, logger):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        self._impcode = await self.read_impcode()
        self.is64      = self._impcode.MIPS32_64
        self.cpunum    = self._impcode.TypeInfo
        self.ejtag_ver = EJTAGver_values[self._impcode.EJTAGver]

        self._log("IMPCODE %s", self._impcode._bits_repr_())

    def _log(self, message, *args):
        self._logger.log(self._level, "EJTAG: " + message, *args)

    async def read_impcode(self):
        await self.lower.write_ir(IR_IMPCODE)
        return IMPCODE.from_bitarray(await self.lower.read_dr(32))


class JTAGMIPSApplet(JTAGApplet, name="jtag-mips"):
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
            self.logger.error("cannot select TAP #%d" % args.tap_index)
            return

        return await EJTAGInterface(jtag_iface, self.logger)

    @classmethod
    def add_interact_arguments(cls, parser):
        pass

    async def interact(self, device, args, ejtag_iface):
        self.logger.info("found MIPS%d CPU %#x (EJTAG version %s)",
                         64 if ejtag_iface.is64 else 32,
                         ejtag_iface.cpunum, ejtag_iface.ejtag_ver)
