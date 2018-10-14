import struct
import logging
from collections import defaultdict
from bitarray import bitarray

from . import JTAGApplet
from .. import *
from ...support.bits import *
from ...support.aobject import *
from ...pyrepl import *


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
    0: "1.x/2.0",
    1: "2.5",
    2: "2.6",
    3: "3.1",
    4: "4.0",
    5: "5.0",
})


DR_IMPCODE = Bitfield("DR_IMPCODE", 4, [
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


DR_CONTROL = Bitfield("DR_CONTROL", 4, [
    (None,         3),
    ("DM",         1),
    (None,         1),
    ("DLock",      1), # Undocumented, EJTAG 1.x/2.0 specific
    (None,         1),
    ("Dsz",        2), # Undocumented, EJTAG 1.x/2.0 specific
    ("DRWn",       1), # Undocumented, EJTAG 1.x/2.0 specific
    ("DErr",       1), # Undocumented, EJTAG 1.x/2.0 specific
    ("DStrt",      1), # Undocumented, EJTAG 1.x/2.0 specific
    ("EjtagBrk",   1),
    ("ISAOnDebug", 1),
    ("ProbTrap",   1),
    ("ProbEn",     1),
    ("PrRst",      1),
    ("DMAAcc",     1), # Undocumented, EJTAG 1.x/2.0 specific
    ("PrAcc",      1),
    ("PRnW",       1),
    ("PerRst",     1),
    ("Halt",       1),
    ("Doze",       1),
    ("VPED",       1),
    (None,         5),
    ("Psz",        2),
    ("Rocc",       1),
])


DRSEG_addr     = 0xffff_ffff_ff30_0000
DRSEG_DCR_addr = DRSEG_addr + 0x0000


class EJTAGInterface(aobject):
    async def __init__(self, interface, logger):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        self._control = DR_CONTROL()

        await self._probe()

    def _log(self, message, *args):
        self._logger.log(self._level, "EJTAG: " + message, *args)

    async def _probe(self):
        await self._read_impcode()
        await self._scan_address_length()
        await self._enable_probe()

        self.bits      = 64 if self._impcode.MIPS32_64 else 32
        self.cpunum    = self._impcode.TypeInfo
        self.ejtag_ver = EJTAGver_values[self._impcode.EJTAGver]

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
        # Sign-extend the address, so that the kseg addresses are compatible between 32-bit
        # and 64-bit processors. (Yes, kseg addresses are intended to be negative.)
        address_bits.extend(address_bits[-1:] * (64 - self._address_length))
        address, = struct.unpack("<q", address_bits.tobytes())
        self._log("read ADDRESS %#018x", address & 0xffff_ffff_ffff_ffff)
        return address

    async def _write_address(self, address):
        # See _read_address. NB: ADDRESS is only writable in EJTAG v1.x/2.0.
        self._log("write ADDRESS %#018x", address & 0xffff_ffff_ffff_ffff)
        address_bits = bitarray(endian="little")
        address_bits.frombytes(struct.pack("<Q", address & 0xffff_ffff_ffff_ffff))
        await self.lower.write_ir(IR_ADDRESS)
        await self.lower.write_dr(address_bits[:self._address_length])

    async def _read_data(self):
        await self.lower.write_ir(IR_DATA)
        data_bits = await self.lower.read_dr(self.bits)
        if self.bits == 32:
            data, = struct.unpack("<L", data_bits.tobytes())
        elif self.bits == 64:
            data, = struct.unpack("<Q", data_bits.tobytes())
        self._log("read DATA %#0.*x", self.bits // 4, data)
        return data

    async def _write_data(self, data):
        self._log("write DATA %#0.*x", self.bits // 4, data)
        await self.lower.write_ir(IR_DATA)
        data_bits = bitarray(endian="little")
        if self.bits == 32:
            data_bits.frombytes(struct.pack("<L", data))
        elif self.bits == 64:
            data_bits.frombytes(struct.pack("<Q", data))
        await self.lower.write_dr(data_bits)

    async def _dma_read(self, address, size):
        self._log("DMA: read address=%#018x size=%d", address, size)
        await self._write_address(address)
        await self._exchange_control(DMAAcc=1, DRWn=1, Dsz=size, DStrt=1)
        for _ in range(3):
            control = await self._exchange_control(DMAAcc=1)
            if not control.DStrt: break
        else:
            raise GlasgowAppletError("DMA: read hang")
        if control.DErr:
            raise GlasgowAppletError("DMA: read error address=%#018x size=%d" %
                                     (address, size))
        data = await self._read_data()
        self._log("DMA: data=%#0.*x", self.bits // 4, data)
        await self._exchange_control(DMAAcc=0)
        return data

    async def _dma_write(self, address, size, data):
        self._log("DMA: write address=%#018x size=%d data=%#0.*x",
                  address, size, self.bits // 4, data)
        await self._write_address(address)
        await self._write_data(data)
        await self._exchange_control(DMAAcc=1, DRWn=0, Dsz=size, DStrt=1)
        for _ in range(3):
            control = await self._exchange_control(DMAAcc=1)
            if not control.DStrt: break
        else:
            raise GlasgowAppletError("DMA: write hang")
        if control.DErr:
            raise GlasgowAppletError("DMA: write error address=%#018x size=%d" %
                                     (address, size))
        await self._exchange_control(DMAAcc=0)

    async def debug_break(self):
        if self.ejtag_ver == "1.x/2.0":
            self._logger.warning("found cursed EJTAG 1.x/2.0 CPU, using undocumented "
                                 "DCR.MP workaround")
            # Undocumented sequence to disable memory protection for dmseg. The bit 2 is
            # documented as NMIpend, but on EJTAG 1.x/2.0 it is actually MP. It is only possible
            # to clear it via DMAAcc because PrAcc requires debug mode to already work.
            dcr  = await self._dma_read(DRSEG_DCR_addr, 2)
            dcr &= ~(1<<2)
            await self._dma_write(DRSEG_DCR_addr, 2, dcr)

        await self._exchange_control(EjtagBrk=1)
        control = await self._exchange_control()
        if control.EjtagBrk:
            raise GlasgowAppletError("failed to enter debug mode")


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
            raise GlasgowAppletError("cannot select TAP #%d" % args.tap_index)

        return await EJTAGInterface(tap_iface, self.logger)

    @classmethod
    def add_interact_arguments(cls, parser):
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION")

        p_repl = p_operation.add_parser(
            "repl", help="drop into Python shell; use `ejtag_iface` to communicate")

    async def interact(self, device, args, ejtag_iface):
        self.logger.info("found MIPS%d CPU %#x (EJTAG version %s)",
                         ejtag_iface.bits, ejtag_iface.cpunum, ejtag_iface.ejtag_ver)

        if args.operation == "repl":
            await AsyncInteractiveConsole(locals={"ejtag_iface":ejtag_iface}).interact()
