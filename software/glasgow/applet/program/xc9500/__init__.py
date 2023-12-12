# Ref: https://prjunnamed.github.io/prjcombine/xc9500/index.html

import struct
import logging
import argparse
import math
import re
from enum import Enum, auto

from ....arch.jtag import *
from ....arch.xilinx.xc9500 import *
from ....support.bits import *
from ....support.logging import *
from ....database.xilinx.xc9500 import *
from ...interface.jtag_probe import JTAGProbeApplet
from ....protocol.jesd3 import *
from ... import *


class XC9500Bitstream:
    def __init__(self, device):
        self.device = device
        self.fbs = [
            [
                bytearray(0 for _ in range(BS_MAIN_COLS))
                for _ in range(BS_MAIN_ROWS)
            ]
            for _ in range(device.fbs)
        ]
        self.uim = [
            [
                [
                    bytearray(0 for _ in range(BS_UIM_COLS))
                    for _ in range(BS_UIM_ROWS)
                ]
                for _ in range(device.fbs)
            ]
            for _ in range(device.fbs)
        ]

    @classmethod
    def from_fuses(cls, fuses, device):
        self = cls(device)
        total_bits = BS_MAIN_ROWS * device.fbs * (9 * 8 + 6 * 6) + BS_UIM_ROWS * (8 + 4 * 7) * device.fbs * device.fbs
        if len(fuses) != total_bits:
            raise GlasgowAppletError(
                "JED file does not have the right fuse count (expected %d, got %d)"
                % (total_bits, len(fuses)))
        pos = 0
        for fb in range(device.fbs):
            for row in range(BS_MAIN_ROWS):
                for col in range(BS_MAIN_COLS):
                    sz = 8 if col < 9 else 6
                    byte = int(fuses[pos:pos+sz])
                    pos += sz
                    self.fbs[fb][row][col] = byte
            for sfb in range(device.fbs):
                for row in range(BS_UIM_ROWS):
                    for col in range(BS_UIM_COLS):
                        sz = 8 if col == 0 else 7
                        byte = int(fuses[pos:pos+sz])
                        pos += sz
                        self.uim[fb][sfb][row][col] = byte

        assert pos == total_bits
        return self

    def to_fuses(self):
        fuses = bitarray()
        for fb in range(self.device.fbs):
            for row in range(BS_MAIN_ROWS):
                for col in range(BS_MAIN_COLS):
                    sz = 8 if col < 9 else 6
                    fuses += bits(self.fbs[fb][row][col], sz)
            for sfb in range(self.device.fbs):
                for row in range(BS_UIM_ROWS):
                    for col in range(BS_UIM_COLS):
                        sz = 8 if col == 0 else 7
                        fuses += bits(self.uim[fb][sfb][row][col], sz)
        return fuses

    def clear_prot(self):
        """Clears the read/write protection bits from the bitstream."""
        for pbit in READ_PROT_BITS + [WRITE_PROT_BIT]:
            (row, col, bit) = pbit
            for fb in range(self.device.fbs):
                self.fbs[fb][row][col] |= 1 << bit

    def verify(self, other):
        assert self.device is other.device
        for fb in range(self.device.fbs):
            for row in range(BS_MAIN_ROWS):
                for col in range(BS_MAIN_COLS):
                    if self.fbs[fb][row][col] != other.fbs[fb][row][col]:
                        raise GlasgowAppletError(f"bitstream verification failed at FB={fb} row={row} col={col}")
        for fb in range(self.device.fbs):
            for sfb in range(self.device.fbs):
                for row in range(BS_UIM_ROWS):
                    for col in range(BS_UIM_COLS):
                        if self.uim[fb][sfb][row][col] != other.uim[fb][sfb][row][col]:
                            raise GlasgowAppletError(f"bitstream verification failed at UIM FB={fb} sFB={sfb} row={row} col={col}")

    def get_byte(self, coords):
        if coords[0] == "main":
            _, fb, row, col = coords
            return self.fbs[fb][row][col]
        else:
            _, fb, sfb, row, col = coords
            return self.uim[fb][sfb][row][col]

    def put_byte(self, coords, val):
        if coords[0] == "main":
            _, fb, row, col = coords
            self.fbs[fb][row][col] = val
        else:
            _, fb, sfb, row, col = coords
            self.uim[fb][sfb][row][col] = val


def device_addresses(device):
    for fb in range(device.fbs):
        for row in range(BS_MAIN_ROWS):
            for col in range(BS_MAIN_COLS):
                yield (bs_main_address(fb, row, col), ("main", fb, row, col))
        for sfb in range(device.fbs):
            for row in range(BS_UIM_ROWS):
                for col in range(BS_UIM_COLS):
                    yield (bs_uim_address(fb, sfb, row, col), ("uim", fb, sfb, row, col))


class XC9500Error(GlasgowAppletError):
    pass


class XC9500Interface:
    def __init__(self, interface, logger, frequency):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._frequency = frequency

    def _log(self, message, *args):
        self._logger.log(self._level, "XC9500: " + message, *args)

    async def identify(self):
        await self.lower.test_reset()
        idcode_bits = await self.lower.read_dr(32)
        idcode = DR_IDCODE.from_bits(idcode_bits)
        self._log("read idcode mfg-id=%03x part-id=%04x",
                  idcode.mfg_id, idcode.part_id)
        device = devices_by_idcode[idcode.mfg_id, idcode.part_id]
        if device is None:
            xc95xx_iface = None
        else:
            xc95xx_iface = XC95xxInterface(self.lower, self._logger, self._frequency, device)
        return idcode, device, xc95xx_iface

    async def read_usercode(self):
        await self.lower.write_ir(IR_USERCODE)
        usercode_bits = await self.lower.read_dr(32)
        self._log("read usercode <%s>", dump_bin(usercode_bits))
        return bytes(usercode_bits)[::-1]


class XC95xxInterface:
    def __init__(self, interface, logger, frequency, device):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._frequency = frequency
        self.device  = device
        self.DR_ISPENABLE = DR_ISPENABLE(device.fbs)

    def _time_us(self, time):
        return math.ceil(time * self._frequency / 1_000_000)

    def _log(self, message, *args):
        self._logger.log(self._level, "XC95xx: " + message, *args)

    async def programming_enable(self):
        self._log("programming enable")
        await self.lower.write_ir(IR_ISPEN)
        ispenable = self.DR_ISPENABLE(fbs=bits('1' * self.device.fbs), uim=1)
        await self.lower.write_dr(ispenable.to_bits())
        await self.lower.run_test_idle(1)

    async def programming_disable(self):
        self._log("programming disable")
        await self.lower.write_ir(IR_ISPEX)
        await self.lower.run_test_idle(self._time_us(WAIT_ISPEX))
        await self.lower.write_ir(IR_BYPASS)
        await self.lower.run_test_idle(1)

    async def _dr_isconfiguration(self, control, address, data=0):
        isconf = DR_ISCONFIGURATION(control=control, address=address, data=data)
        isconf_bits = await self.lower.exchange_dr(isconf.to_bits())
        isconf = DR_ISCONFIGURATION.from_bits(isconf_bits)
        return isconf

    async def _dr_isdata(self, control, data=0):
        isdata = DR_ISDATA(control=control, data=data)
        isdata_bits = await self.lower.exchange_dr(isdata.to_bits())
        isdata = DR_ISDATA.from_bits(isdata_bits)
        return isdata

    async def read(self, fast=True):
        self._log("device read")
        bs = XC9500Bitstream(self.device)
        status_bits = await self.lower.exchange_ir(IR_FVFY)
        status = IR_STATUS.from_bits(status_bits)
        if status.read_protect:
            raise XC9500Error("read failed: device is read protected")

        if fast:
            # Use FVFY just to set the address counter.
            await self._dr_isconfiguration(CTRL_START, 0)
            await self.lower.write_ir(IR_FVFYI)
            for _, coords in device_addresses(self.device):
                await self.lower.run_test_idle(1)
                res = await self._dr_isdata(CTRL_START)
                if res.control != CTRL_OK:
                    raise XC9500Error(f"fast read failed {res.bits_repr()} at {coords}")
                bs.put_byte(coords, res.data)
        else:
            # Use FVFY for all reads.
            prev_coords = None
            for addr, coords in device_addresses(self.device):
                res = await self._dr_isconfiguration(CTRL_START, addr)
                if prev_coords is not None:
                    if res.control != CTRL_OK:
                        raise XC9500Error(f"read failed {res.bits_repr()} at {prev_coords}")
                    bs.put_byte(prev_coords, res.data)
                await self.lower.run_test_idle(1)
                prev_coords = coords
            res = await self._dr_isconfiguration(CTRL_OK, 0)
            if res.control != CTRL_OK:
                raise XC9500Error(f"read failed {res.bits_repr()} at {prev_coords}")
            bs.put_byte(prev_coords, res.data)

        return bs

    async def erase(self):
        self._log("erase")

        await self.lower.write_ir(IR_FERASE)
        for fb in range(self.device.fbs):
            await self._dr_isconfiguration(CTRL_START, fb << 13)
            await self.lower.run_test_idle(self._time_us(WAIT_ERASE))
            res = await self._dr_isconfiguration(CTRL_START, fb << 13 | 0x1000)
            if res.control == CTRL_WPROT:
                raise XC9500Error("erase failed: device is write protected")
            elif res.control != CTRL_OK:
                raise XC9500Error(f"erase failed {res.bits_repr()}")
            await self.lower.run_test_idle(self._time_us(WAIT_ERASE))
            res = await self._dr_isconfiguration(CTRL_OK, 0)
            if res.control == CTRL_WPROT:
                raise XC9500Error("erase failed: device is write protected")
            elif res.control != CTRL_OK:
                raise XC9500Error(f"erase failed {res.bits_repr()}")

    async def bulk_erase(self):
        self._log("bulk erase")

        await self.lower.write_ir(IR_FBULK)
        await self._dr_isconfiguration(CTRL_START, 0)
        await self.lower.run_test_idle(self._time_us(WAIT_ERASE))
        res = await self._dr_isconfiguration(CTRL_START, 0x1000)
        if res.control == CTRL_WPROT:
            raise XC9500Error("bulk erase failed: device is write protected")
        elif res.control != CTRL_OK:
            raise XC9500Error(f"bulk erase failed {res.bits_repr()}")
        await self.lower.run_test_idle(self._time_us(WAIT_ERASE))
        res = await self._dr_isconfiguration(CTRL_OK, 0)
        if res.control == CTRL_WPROT:
            raise XC9500Error("bulk erase failed: device is write protected")
        elif res.control != CTRL_OK:
            raise XC9500Error(f"bulk erase failed {res.bits_repr()}")

    async def override_erase(self):
        self._log("override erase")
        await self.lower.write_ir(IR_FERASE)
        await self._dr_isconfiguration(CTRL_START, ADDR_OVERRIDE_MAGIC)

    async def program(self, bs, fast=True):
        self._log("program device")
        if fast:
            # Use FPGM to program first word and set the address counter.
            # Use FPGMI for much faster following writes.
            await self.lower.write_ir(IR_FPGM)
            prev_coords = None
            for addr, coords in device_addresses(self.device):
                byte = bs.get_byte(coords)
                if addr == 0:
                    await self._dr_isconfiguration(CTRL_START, addr, byte)
                    await self.lower.write_ir(IR_FPGMI)
                else:
                    res = await self._dr_isdata(CTRL_START, byte)
                    if prev_coords is not None:
                        if res.control == CTRL_WPROT:
                            raise XC9500Error("fast programming failed: device is write protected")
                        elif res.control != CTRL_OK:
                            raise XC9500Error(f"fast programming failed {res.bits_repr()} at {prev_coords}")
                await self.lower.run_test_idle(self._time_us(WAIT_PROGRAM))
                prev_coords = coords

            res = await self._dr_isdata(CTRL_OK)
            if res.control == CTRL_WPROT:
                raise XC9500Error("fast programming failed: device is write protected")
            elif res.control != CTRL_OK:
                raise XC9500Error(f"fast programming failed {res.bits_repr()} at {prev_coords}")
        else:
            # Use FPGM for all writes.
            await self.lower.write_ir(IR_FPGM)
            prev_coords = None
            for addr, coords in device_addresses(self.device):
                byte = bs.get_byte(coords)
                res = await self._dr_isconfiguration(CTRL_START, addr, byte)
                if prev_coords is not None:
                    if res.control == CTRL_WPROT:
                        raise XC9500Error("programming failed: device is write protected")
                    elif res.control != CTRL_OK:
                        raise XC9500Error(f"programming failed {res.bits_repr()} at row {prev_coords}")
                await self.lower.run_test_idle(self._time_us(WAIT_PROGRAM))
                prev_coords = coords

            res = await self._dr_isconfiguration(CTRL_OK, 0)
            if res.control == CTRL_WPROT:
                raise XC9500Error("programming failed: device is write protected")
            elif res.control != CTRL_OK:
                raise XC9500Error(f"programming failed {res.bits_repr()} at {prev_coords}")

    async def program_prot(self, bs, fast=True, read_protect=False, write_protect=False):
        bits = []
        if read_protect:
            bits += READ_PROT_BITS
        if write_protect:
            bits += [WRITE_PROT_BIT]
        if not bits:
            # Nothing to do.
            return
        
        self._log("program protection bits")
        await self.lower.write_ir(IR_FPGM)
        for fb in range(self.device.fbs):
            for coords in bits:
                row, col, bit = coords
                addr = bs_main_address(fb, row, col)
                byte = bs.fbs[fb][row][col]
                byte &= ~(1 << bit)
                await self._dr_isconfiguration(CTRL_START, addr, byte)
                await self.lower.run_test_idle(self._time_us(WAIT_PROGRAM))
                res = await self._dr_isconfiguration(CTRL_OK, 0)
                if res.control != CTRL_OK:
                    raise XC9500Error(f"programming protection bits failed {isaddr.bits_repr()}")


class ProgramXC9500Applet(JTAGProbeApplet):
    logger = logging.getLogger(__name__)
    help = "program Xilinx XC9500 CPLDs via JTAG"
    description = """
    Program, verify, and read out Xilinx XC9500 series CPLD bitstreams via the JTAG interface.

    It is recommended to use TCK frequency between 100 and 250 kHz for programming.

    Some CPLDs in the wild have been observed to return failures during programming, possibly
    because they are taken from the rejects bin or recycled, see [1]. The "program word failed"
    messages during programming do not necessarily mean a failed device; if the bitstream verifies
    afterwards, it is likely to operate correctly.

    [1]: http://tech.mattmillman.com/making-use-of-recycled-xilinx-xc9500-cplds/

    Supported devices are:
{devices}
    """.format(
        devices="\n".join(f"        * {device.name}" for device in devices)
    )

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)
        super().add_run_tap_arguments(parser)

    async def run(self, device, args):
        tap_iface = await self.run_tap(ProgramXC9500Applet, device, args)
        return XC9500Interface(tap_iface, self.logger, args.frequency * 1000)

    @classmethod
    def add_interact_arguments(cls, parser):
        parser.add_argument(
            "--slow", default=False, action="store_true",
            help="use slower but potentially more robust algorithms, where applicable")

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION")

        p_read = p_operation.add_parser(
            "read", help="read bitstream from the device and save it to a .jed file")
        p_read.add_argument(
            "jed_file", metavar="JED-FILE", type=argparse.FileType("wb"),
            help="JED file to write")

        p_program = p_operation.add_parser(
            "program", help="read bitstream from a .jed file and program it to the device")
        p_program.add_argument(
            "jed_file", metavar="JED-FILE", type=argparse.FileType("rb"),
            help="JED file to read")
        p_program.add_argument(
            "--override", default=False, action="store_true",
            help="override write-protection")
        p_program.add_argument(
            "--erase", default=False, action="store_true",
            help="erase before programming, if necessary")
        p_program.add_argument(
            "--verify", default=False, action="store_true",
            help="verify after programming")
        p_program.add_argument(
            "--write-protect", default=False, action="store_true",
            help="enable write protection")
        p_program.add_argument(
            "--read-protect", default=False, action="store_true",
            help="enable read protection")

        p_verify = p_operation.add_parser(
            "verify", help="read bitstream from a .jed file and verify it against the device")
        p_verify.add_argument(
            "jed_file", metavar="JED-FILE", type=argparse.FileType("rb"),
            help="JED file to read")

        p_erase = p_operation.add_parser(
            "erase", help="erase bitstream from the device")
        p_erase.add_argument(
            "--override", default=False, action="store_true",
            help="override write-protection")

    async def interact(self, device, args, xc9500_iface):
        idcode, xc9500_device, xc95xx_iface = await xc9500_iface.identify()
        if xc9500_device is None:
            raise GlasgowAppletError("cannot operate on unknown device with IDCODE=%#10x"
                                     % idcode.to_int())

        self.logger.info("found %s rev=%d",
                         xc9500_device.name, idcode.version)

        usercode = await xc9500_iface.read_usercode()
        self.logger.info("USERCODE=%s (%s)",
                         usercode.hex(),
                         re.sub(rb"[^\x20-\x7e]", b"?", usercode).decode("ascii"))

        try:
            if args.operation == "read":
                await xc95xx_iface.programming_enable()
                bs = await xc95xx_iface.read(fast=not args.slow)
                bs.clear_prot()
                fuses = bs.to_fuses()
                emitter = JESD3Emitter(fuses, quirk_no_design_spec=True)
                emitter.add_comment(b"DEVICE %s" % xc9500_device.name.encode())
                args.jed_file.write(emitter.emit())

            if args.operation in ("program", "verify"):
                try:
                    parser = JESD3Parser(args.jed_file.read(), quirk_no_design_spec=True)
                    parser.parse()
                except JESD3ParsingError as e:
                    raise GlasgowAppletError(str(e))

                bs = XC9500Bitstream.from_fuses(parser.fuse, xc9500_device)

            if args.operation == "program":
                await xc95xx_iface.programming_enable()

                if args.erase:
                    if args.override:
                        await xc95xx_iface.override_erase()
                    if idcode.version < 2 or args.slow:
                        await xc95xx_iface.erase()
                    else:
                        await xc95xx_iface.bulk_erase()
                    await xc95xx_iface.programming_disable()
                    await xc95xx_iface.programming_enable()

                await xc95xx_iface.program(bs, fast=not args.slow)

                if args.verify:
                    dev_bs = await xc95xx_iface.read(fast=not args.slow)
                    bs.verify(dev_bs)

                await xc95xx_iface.program_prot(bs, fast=not args.slow,
                                                read_protect=args.read_protect,
                                                write_protect=args.write_protect)

            if args.operation == "verify":
                await xc95xx_iface.programming_enable()
                dev_bs = await xc95xx_iface.read(fast=not args.slow)
                dev_bs.clear_prot()
                bs.verify(dev_bs)

            if args.operation == "erase":
                await xc95xx_iface.programming_enable()
                if args.override:
                    await xc95xx_iface.override_erase()
                if idcode.version < 2 or args.slow:
                    await xc95xx_iface.erase()
                else:
                    await xc95xx_iface.bulk_erase()

        finally:
            await xc95xx_iface.programming_disable()

# -------------------------------------------------------------------------------------------------

class ProgramXC9500AppletTool(GlasgowAppletTool, applet=ProgramXC9500Applet):
    help = "manipulate Xilinx XC9500 CPLD bitstreams"
    description = """
    See `run program-xc9500 --help` for details.
    """

    @classmethod
    def add_arguments(cls, parser):
        def idcode(arg):
            if arg.upper() in devices_by_name:
                return devices_by_name[arg.upper()]
            try:
                idcode = DR_IDCODE.from_int(int(arg, 16))
            except ValueError:
                raise argparse.ArgumentTypeError("unknown device")

            device = devices_by_idcode[idcode.mfg_id, idcode.part_id]
            if device is None:
                raise argparse.ArgumentTypeError("unknown IDCODE")
            return device

        parser.add_argument(
            "-d", "--device", metavar="DEVICE", type=idcode, required=True,
            help="select device with given name or JTAG IDCODE")

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION")

        p_read_usercode = p_operation.add_parser(
            "read-usercode", help="read USERCODE from a .jed file")
        p_read_usercode.add_argument(
            "jed_file", metavar="JED-FILE", type=argparse.FileType("rb"),
            help="bitstream file to read")

    async def run(self, args):
        if args.operation == "read-usercode":
            try:
                parser = JESD3Parser(args.jed_file.read(), quirk_no_design_spec=True)
                parser.parse()
            except JESD3ParsingError as e:
                raise GlasgowAppletError(str(e))

            bs = XC9500Bitstream.from_fuses(parser.fuse, args.device)

            usercode = 0
            for i, (fb, row, col, bit) in enumerate(USERCODE_BITS):
                data = bs.fbs[fb][row][col] >> bit & 1
                usercode |= data << i

            usercode = struct.pack(">L", usercode)
            self.logger.info("USERCODE=%s (%s)",
                             usercode.hex(),
                             re.sub(rb"[^\x20-\x7e]", b"?", usercode).decode("ascii"))
