# Ref: https://prjunnamed.github.io/prjcombine/xpla3/index.html

import logging
import argparse
import re
import math

from ....arch.jtag import *
from ....arch.xilinx.xpla3 import *
from ....support.bits import *
from ....support.logging import *
from ....database.xilinx.xpla3 import *
from ...interface.jtag_probe import JTAGProbeApplet
from ....protocol.jesd3 import *
from ... import *


def jed_bits(device):
    fbs = len(device.fb_cols) * device.fb_rows * 2
    for fb in range(fbs):
        odd = fb % 2
        fb_row = fb // 2 % device.fb_rows
        fb_col = device.fb_cols[fb // 2 // device.fb_rows]
        # IMUX
        for imux in range(40):
            for j in range(device.imux_width):
                col = fb_col.imux_col + (device.imux_width - 1 - j)
                row = fb_row * 52 + (imux + 2 if imux < 20 else imux + 10)
                yield row, odd ^ 1, col
        # PLA AND
        for pt in range(48):
            col = fb_col.pt_col + (95 - pt if odd else pt)
            for imux in range(40):
                row = fb_row * 52 + (imux + 2 if imux < 20 else imux + 10)
                yield row, 0, col
                yield row, 1, col
            # foldback NAND
            for row, plane in [
                (0, 1),
                (0, 0),
                (1, 1),
                (1, 0),
                (50, 0),
                (50, 1),
                (51, 0),
                (51, 1),
            ]:
                yield row, plane, col
        # PLA OR
        for pt in range(48):
            col = fb_col.pt_col + (95 - pt if odd else pt)
            for mc in range(16):
                row = fb_row * 52 + 22 + mc // 2
                plane = 1 - mc % 2
                yield row, plane, col
        # per-FB misc bits
        for row, plane, col in FB_BITS:
            row = fb_row * 52 + 24 + row
            col = fb_col.mc_col + (9 - col if odd else col)
            yield row, plane, col
        # per-MC bits (MCs with IOBs)
        for mc in range(16):
            if mc in device.io_mcs:
                for row, plane, col in MC_BITS_IOB:
                    row = fb_row * 52 + (mc * 3 if mc < 8 else mc * 3 + 4) + row
                    col = fb_col.mc_col + (9 - col if odd else col)
                    yield row, plane, col
        # per-MC bits (MCs without IOBs)
        for mc in range(16):
            if mc not in device.io_mcs:
                for row, plane, col in MC_BITS_BURIED:
                    row = fb_row * 52 + (mc * 3 if mc < 8 else mc * 3 + 4) + row
                    col = fb_col.mc_col + (9 - col if odd else col)
                    yield row, plane, col
    # misc global bits
    for row, plane, col in device.global_bits:
        yield row, plane, col


class XPLA3Bitstream:
    def __init__(self, device):
        self.device = device
        rows = device.fb_rows * 52 + 2
        self.data = [
            [
                bitarray(-1, device.bs_cols)
                for _ in range(2)
            ]
            for _ in range(rows)
        ]

    @classmethod
    def from_fuses(cls, fuses, device):
        self = cls(device)
        bits = list(jed_bits(device))
        if len(fuses) != len(bits):
            raise GlasgowAppletError(
                f"JED file does not have the right fuse count (expected {len(bits)}, got {len(fuses)})")
        for (row, plane, col), val in zip(bits, fuses):
            self.data[row][plane][col] = val
        return self

    def set_ues(self, ues):
        for idx, (row, plane, col) in enumerate(self.device.ues_bits):
            byte_idx = idx // 8
            bit_idx = idx % 8 ^ 7
            if byte_idx < len(ues):
                val = ues[byte_idx] >> bit_idx & 1
            else:
                val = 1
            self.data[row][plane][col] = val

    def get_ues(self):
        res = bytearray(b"\xff" * ((len(self.device.ues_bits) + 7) // 8))
        for idx, (row, plane, col) in enumerate(self.device.ues_bits):
            val = self.data[row][plane][col]
            byte_idx = idx // 8
            bit_idx = idx % 8 ^ 7
            if byte_idx < len(res):
                res[byte_idx] &= ~(1 << bit_idx)
                res[byte_idx] |= val << bit_idx
        while len(res) > 0 and res[-1] == 0xff:
            res.pop()
        return res

    def to_fuses(self):
        return bits(self.data[row][plane][col] for row, plane, col in jed_bits(self.device))

    def verify(self, other):
        assert self.device is other.device
        for row, plane, col in jed_bits(self.device):
            if self.data[row][plane][col] != other.data[row][plane][col]:
                raise GlasgowAppletError(f"bitstream verification failed at row={row} plane={plane} col={col}")


class XPLA3Interface:
    def __init__(self, interface, logger, frequency):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._frequency = frequency
        self.idcode  = None
        self.device  = None

    def _time_us(self, time):
        return math.ceil(time * self._frequency / 1_000_000)

    def _log(self, message, *args):
        self._logger.log(self._level, "XPLA3: " + message, *args)

    def _misr(self, row, plane, data=None):
        row = row ^ row >> 1
        row = bits(row, self.DR_MISR._layout_["row"][1])
        if data is None:
            data = 0
        else:
            data = data[::-1]
        return self.DR_MISR(row=row[::-1], plane=plane, data=data).to_bits()

    async def identify(self):
        if self.idcode is None:
            await self.lower.test_reset()
            idcode_bits = await self.lower.read_dr(32)
            self.idcode = DR_IDCODE.from_bits(idcode_bits)
            self._log("read idcode mfg-id=%03x part-id=%04x",
                      self.idcode.mfg_id, self.idcode.part_id)
            if self.idcode.mfg_id not in (MFG_PHILIPS, MFG_XILINX):
                self.device = None
            else:
                self.device = devices_by_idcode[self.idcode.part_id & ~7]
            if self.device is not None:
                self.DR_MISR = DR_MISR(self.device.bs_cols, self.device.fb_rows * 52 + 2)
        return self.idcode, self.device

    async def isp_enable(self, otf=False):
        self._log("isp enable")
        await self.lower.write_ir(IR_ISP_EOTF if otf else IR_ISP_ENABLE)
        await self.lower.run_test_idle(1)

    async def isp_init(self):
        self._log("isp init")
        await self.lower.write_ir(IR_ISP_INIT)
        await self.lower.run_test_idle(self._time_us(200))

    async def isp_disable(self):
        self._log("isp disable")
        await self.lower.write_ir(IR_ISP_DISABLE)
        await self.lower.run_test_idle(self._time_us(100))

    async def read(self, sram=False):
        self._log("read")
        await self.lower.write_ir(IR_ISP_READ if sram else IR_ISP_VERIFY)
        bs = XPLA3Bitstream(self.device)
        for plane in range(2):
            for row in range(len(bs.data)):
                misr = await self.lower.exchange_dr(self._misr(row, plane))
                await self.lower.run_test_idle(self._time_us(100))
                misr = await self.lower.exchange_dr(self._misr(row, plane))
                misr = self.DR_MISR.from_bits(misr)
                await self.lower.run_test_idle(self._time_us(100))
                bs.data[row][plane][:] = bits(misr.data, self.device.bs_cols)[::-1]
        row, plane, col = self.device.read_prot_bit
        if not bs.data[row][plane][col]:
            raise GlasgowAppletError("read failed: device is read protected")
        return bs

    async def read_ues(self):
        self._log("read ues")
        await self.lower.write_ir(IR_ISP_VERIFY)
        bs = XPLA3Bitstream(self.device)
        ues_row = self.device.ues_bits[0][0]
        data = []
        for plane in range(2):
            misr = await self.lower.exchange_dr(self._misr(ues_row, plane))
            await self.lower.run_test_idle(self._time_us(100))
            misr = await self.lower.exchange_dr(self._misr(ues_row, plane))
            misr = self.DR_MISR.from_bits(misr)
            await self.lower.run_test_idle(self._time_us(100))
            data.append(bits(misr.data, self.device.bs_cols)[::-1])

        res = bytearray(b"\xff" * ((len(self.device.ues_bits) + 7) // 8))
        for idx, (row, plane, col) in enumerate(self.device.ues_bits):
            assert row == ues_row
            val = data[plane][col]
            byte_idx = idx // 8
            bit_idx = idx % 8 ^ 7
            if byte_idx < len(res):
                res[byte_idx] &= ~(1 << bit_idx)
                res[byte_idx] |= val << bit_idx
        while len(res) > 0 and res[-1] == 0xff:
            res.pop()
        return res

    async def program(self, bs, sram=False):
        self._log("program")
        await self.lower.write_ir(IR_ISP_WRITE if sram else IR_ISP_PROGRAM)
        for plane in range(2):
            for row in range(len(bs.data)):
                await self.lower.write_dr(self._misr(row, plane, bits(bs.data[row][plane])))
                if sram:
                    await self.lower.run_test_idle(self._time_us(100))
                else:
                    await self.lower.run_test_idle(self._time_us(10000))
        return bs

    async def program_read_protect(self):
        self._log("program read protect")
        await self.lower.write_ir(IR_ISP_PROGRAM)
        row, plane, col = self.device.read_prot_bit
        data = bitarray(-1, self.device.bs_cols)
        data[col] = 0
        await self.lower.write_dr(self._misr(row, plane, bits(data)))
        await self.lower.run_test_idle(self._time_us(10000))

    async def erase(self):
        self._log("erase")
        await self.lower.write_ir(IR_ISP_ERASE)
        await self.lower.write_dr('')
        await self.lower.run_test_idle(self._time_us(100000))


class ProgramXPLA3Applet(JTAGProbeApplet):
    logger = logging.getLogger(__name__)
    help = "program Xilinx XPLA3 CPLDs via JTAG"
    description = """
    Program, verify, and read out Xilinx XPLA3 series CPLD bitstreams via the JTAG interface.

    Supported devices are:

{devices}

    Warning: programming SRAM directly will not set the initial register values correctly.
    Use this option at your own risk.
    """.format(
        devices="\n".join(f"        * {device.name}" for device in devices)
    )

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)
        super().add_run_tap_arguments(parser)

    async def run(self, device, args):
        tap_iface = await self.run_tap(ProgramXPLA3Applet, device, args)
        return XPLA3Interface(tap_iface, self.logger, args.frequency * 1000)

    @classmethod
    def add_interact_arguments(cls, parser):
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION")

        p_read = p_operation.add_parser(
            "read", help="read bitstream from the device Flash and save it to a .jed file")
        p_read.add_argument(
            "jed_file", metavar="JED-FILE", type=argparse.FileType("wb"),
            help="JED file to write")
        p_read.add_argument(
            "--otf", default=False, action="store_true",
            help="use on-the-fly programming (keep device running)")

        p_read_sram = p_operation.add_parser(
            "read-sram", help="read bitstream from the device SRAM and save it to a .jed file")
        p_read_sram.add_argument(
            "jed_file", metavar="JED-FILE", type=argparse.FileType("wb"),
            help="JED file to write")
        p_read_sram.add_argument(
            "--otf", default=False, action="store_true",
            help="use on-the-fly programming (keep device running)")

        p_program = p_operation.add_parser(
            "program", help="read bitstream from a .jed file and program it to the device")
        p_program.add_argument(
            "jed_file", metavar="JED-FILE", type=argparse.FileType("rb"),
            help="JED file to read")
        p_program.add_argument(
            "--otf", default=False, action="store_true",
            help="use on-the-fly programming (keep device running)")
        p_program.add_argument(
            "--erase", default=False, action="store_true",
            help="erase before programming, if necessary")
        p_program.add_argument(
            "--verify", default=False, action="store_true",
            help="verify after programming")
        p_program.add_argument(
            "--read-protect", default=False, action="store_true",
            help="enable read protection")
        p_program.add_argument(
            "--ues", default=None, type=str.encode, nargs='?',
            help="user electronic signature (ASCII)")
        p_program.add_argument(
            "--ues-hex", default=None, type=bytes.fromhex, nargs='?',
            help="user electronic signature (hex)")

        p_program_sram = p_operation.add_parser(
            "program-sram", help="read bitstream from a .jed file and program it to the device SRAM")
        p_program_sram.add_argument(
            "jed_file", metavar="JED-FILE", type=argparse.FileType("rb"),
            help="JED file to read")
        p_program_sram.add_argument(
            "--verify", default=False, action="store_true",
            help="verify after programming")

        p_verify = p_operation.add_parser(
            "verify", help="read bitstream from a .jed file and verify it against the device")
        p_verify.add_argument(
            "jed_file", metavar="JED-FILE", type=argparse.FileType("rb"),
            help="JED file to read")
        p_verify.add_argument(
            "--otf", default=False, action="store_true",
            help="use on-the-fly programming (keep device running)")

        p_erase = p_operation.add_parser(
            "erase", help="erase bitstream from the device")

    async def interact(self, device, args, iface):
        idcode, device = await iface.identify()
        if device is None:
            raise GlasgowAppletError("cannot operate on unknown device with IDCODE=%#10x"
                                     % idcode.to_int())

        self.logger.info("found %s rev=%d",
                         device.name, idcode.version)

        await iface.isp_enable(True)
        ues = await iface.read_ues()
        ues_ascii = re.sub(rb"[^\x20-\x7e]", b"?", ues).decode("ascii")
        self.logger.info(f"UES={ues.hex()} ({ues_ascii})")
        await iface.lower.run_test_idle(1)
        await iface.isp_disable()

        await iface.lower.run_test_idle(1)
        try:
            if args.operation in ("program", "program-sram", "verify", "verify-sram"):
                try:
                    parser = JESD3Parser(args.jed_file.read(), quirk_no_design_spec=True)
                    parser.parse()
                except JESD3ParsingError as e:
                    raise GlasgowAppletError(str(e))

                bs = XPLA3Bitstream.from_fuses(parser.fuse, device) 

            if args.operation in ("read", "read-sram", "verify", "verify-sram"):
                await iface.isp_enable(args.otf)
                read_bs = await iface.read(args.operation in ("read-sram", "verify-sram"))
                read_fuses = read_bs.to_fuses()

            if args.operation in ("read", "read-sram"):
                emitter = JESD3Emitter(read_fuses, quirk_no_design_spec=True)
                emitter.add_comment(b"DEVICE %s" % device.name.upper().encode())
                args.jed_file.write(emitter.emit())

            if args.operation in ("verify", "verify-sram"):
                read_bs.verify(bs)

            if args.operation == "erase":
                await iface.isp_enable(False)
                await iface.erase()
                await iface.isp_init()

            if args.operation in ("program", "program-sram"):
                sram = args.operation == "program-sram"

                if not sram:
                    if args.ues is not None:
                        bs.set_ues(args.ues)
                    if args.ues_hex is not None:
                        bs.set_ues(args.ues_hex)

                await iface.isp_enable(False if sram else args.otf)

                if not sram and args.erase:
                    await iface.erase()
                    await iface.isp_init()

                await iface.program(bs, sram=sram)

                if args.verify:
                    read_bs = await iface.read(sram)
                    read_bs.verify(bs)

                if not sram and args.read_protect:
                    await iface.program_read_protect()

                if not sram:
                    await iface.isp_init()

        finally:
            await iface.lower.run_test_idle(1)
            await iface.isp_disable()
