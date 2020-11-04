# Ref: Microchip MEC1618 Low Power 32-bit Microcontroller with Embedded Flash
# Document Number: DS00002339A
# Accession: G00005
# Ref: Microchip MEC1609 Mixed Signal Mobile Embedded Flash ARC EC BC-Link/VLPC Base Component
# Document Number: DS00002485A
# Accession: G00006

import logging
import argparse
import struct

from ....support.aobject import *
from ....arch.arc import *
from ....arch.arc.mec16xx import *
from ...debug.arc import DebugARCApplet
from ... import *


FIRMWARE_SIZE = 0x30_000


class MEC16xxError(GlasgowAppletError):
    pass


class MEC16xxInterface(aobject):
    async def __init__(self, interface, logger):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        idcode, device = await self.lower.identify()
        if device is None or device.name != "ARC6xx":
            raise MEC16xxError("cannot operate on unknown device with IDCODE=%08x"
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
        await tap_iface.write_dr(dr_reset_test.to_bits())
        dr_reset_test.VTR_POR = 1
        await tap_iface.write_dr(dr_reset_test.to_bits())
        dr_reset_test.ME = 1
        await tap_iface.write_dr(dr_reset_test.to_bits())
        dr_reset_test.VTR_POR = 0
        await tap_iface.write_dr(dr_reset_test.to_bits())

    async def enable_flash_access(self, enabled):
        # Enable access to Reg_Ctl bit.
        flash_config = Flash_Config(Reg_Ctl_En=enabled)
        self._log("write Flash_Config %s", flash_config.bits_repr(omit_zero=True))
        await self.lower.write(Flash_Config_addr, flash_config.to_int(), space="memory")

        if not enabled:
            # Clearing Reg_Ctl_En automatically clears Reg_Ctl.
            return

        # Enable access to Flash controller registers. Also, bring Flash controller to standby
        # mode if it wasn't already in it, since otherwise it will refuse commands.
        flash_command = Flash_Command(Reg_Ctl=1, Flash_Mode=Flash_Mode_Standby)
        self._log("write Flash_Command %s", flash_command.bits_repr(omit_zero=True))
        await self.lower.write(Flash_Command_addr, flash_command.to_int(), space="memory")

        # Clear Flash controller error status.
        flash_clear_status = Flash_Status(Busy_Err=1, CMD_Err=1, Protect_Err=1)
        self._log("clear Flash_Status %s", flash_clear_status.bits_repr(omit_zero=True))
        await self.lower.write(Flash_Status_addr, flash_clear_status.to_int(), space="memory")

    async def _flash_command(self, mode, address=0, burst=False):
        flash_command = Flash_Command(Reg_Ctl=1, Flash_Mode=mode, Burst=burst)
        self._log("write Flash_Command %s", flash_command.bits_repr(omit_zero=True))
        await self.lower.write(Flash_Command_addr, flash_command.to_int(), space="memory")

        self._log("write Flash_Address=%08x", address)
        await self.lower.write(Flash_Address_addr, address, space="memory")

        flash_status = Flash_Status(Busy=1)
        while flash_status.Busy:
            flash_status = Flash_Status.from_int(
                await self.lower.read(Flash_Status_addr, space="memory"))
            self._log("read Flash_Status %s", flash_status.bits_repr(omit_zero=True))

            if flash_status.Busy_Err or flash_status.CMD_Err or flash_status.Protect_Err:
                raise MEC16xxError("Flash command %s failed with status %s"
                                   % (flash_command.bits_repr(omit_zero=True),
                                      flash_status.bits_repr(omit_zero=True)))

    async def read_flash(self, address, count):
        words = []
        for offset in range(count):
            await self._flash_command(mode=Flash_Mode_Read, address=address + offset * 4)
            data_1 = await self.lower.read(Flash_Data_addr, space="memory")
            self._log("read Flash_Address=%05x Flash_Data=%08x",
                      address + offset * 4, data_1)

            # This is hella cursed. In theory, we should be able to just enable Burst in
            # Flash_Command and do a long series of reads from Flash_Data. However, sometimes
            # we silently get zeroes back for no discernible reason. Since data never gets
            # corrupted during programming, the most likely explanation is a silicon bug where
            # the debug interface is not correctly waiting for the Flash memory to acknowledge
            # the read.
            await self.lower.write(Flash_Address_addr, address + offset * 4, space="memory")
            data_2 = await self.lower.read(Flash_Data_addr, space="memory")
            self._log("read Flash_Address=%05x Flash_Data=%08x",
                      address + offset * 4, data_2)

            if data_1 == data_2:
                data = data_1
            else:
                # Third time's the charm.
                await self.lower.write(Flash_Address_addr, address + offset * 4, space="memory")
                data_3 = await self.lower.read(Flash_Data_addr, space="memory")
                self._log("read Flash_Address=%05x Flash_Data=%08x",
                          address + offset * 4, data_3)

                self._logger.warn("read glitch Flash_Address=%05x Flash_Data=%08x/%08x/%08x",
                                  address + offset * 4, data_1, data_2, data_3)

                if data_1 == data_2:
                    data = data_1
                elif data_2 == data_3:
                    data = data_2
                elif data_1 == data_3:
                    data = data_3
                else:
                    raise MEC16xxError("cannot select a read by majority")

            words.append(data)
        return words

    async def erase_flash(self, address=0b11111 << 19):
        await self._flash_command(mode=Flash_Mode_Erase, address=address)

    async def program_flash(self, address, words):
        await self._flash_command(mode=Flash_Mode_Program, address=address, burst=1)
        for offset, data in enumerate(words):
            await self.lower.write(Flash_Data_addr, data, space="memory")
            self._log("program Flash_Address=%05x Flash_Data=%08x", address + offset * 4, data)


class ProgramMEC16xxApplet(DebugARCApplet, name="program-mec16xx"):
    logger = logging.getLogger(__name__)
    help = "program Microchip MEC16xx embedded controller via JTAG"
    description = """
    Read and write Microchip MEC16xx/MEC16xxi embedded controller integrated Flash
    via the JTAG interface.

    Per the MEC16xx datasheets, the minimum JTAG frequency should be 1 MHz.
    """

    async def run(self, device, args):
        arc_iface = await super().run(device, args)
        return await MEC16xxInterface(arc_iface, self.logger)

    @classmethod
    def add_interact_arguments(cls, parser):
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

        p_emergency_erase = p_operation.add_parser(
            "emergency-erase", help="emergency erase firmware")

        p_read = p_operation.add_parser(
            "read", help="read EC firmware")
        p_read.add_argument(
            "file", metavar="FILE", type=argparse.FileType("wb"),
            help="write EC firmware to FILE")

        p_write = p_operation.add_parser(
            "write", help="write EC firmware")
        p_write.add_argument(
            "file", metavar="FILE", type=argparse.FileType("rb"),
            help="read EC firmware from FILE")

    async def interact(self, device, args, mec_iface):
        if args.operation == "read":
            await mec_iface.enable_flash_access(enabled=True)
            words = await mec_iface.read_flash(0, FIRMWARE_SIZE // 4)
            await mec_iface.enable_flash_access(enabled=False)

            for word in words:
                args.file.write(struct.pack("<L", word))

        if args.operation == "write":
            words = []
            for _ in range(FIRMWARE_SIZE // 4):
                word, = struct.unpack("<L", args.file.read(4))
                words.append(word)

            await mec_iface.enable_flash_access(enabled=True)
            await mec_iface.erase_flash()
            await mec_iface.program_flash(0, words)
            await mec_iface.enable_flash_access(enabled=False)

        if args.operation == "emergency-erase":
            await mec_iface.emergency_flash_erase()
