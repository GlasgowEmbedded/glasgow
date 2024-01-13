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


FLASH_SIZE_MAX = 0x40_000
EEPROM_SIZE = 2048


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

        self._logger.warn("after running emergency mass erase, a power cycle may be required on some chips")

    async def enable_flash_access(self, enabled):
        # Enable access to Reg_Ctl bit.
        flash_config = Flash_Config(Reg_Ctl_En=enabled)
        self._log("write Flash_Config %s", flash_config.bits_repr(omit_zero=True))
        await self.lower.write(Flash_Config_addr, flash_config.to_int(), space="memory")

    async def _flash_clean_start(self):
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

        if mode != Flash_Mode_Standby:
            self._log("write Flash_Address=%08x", address)
            await self.lower.write(Flash_Address_addr, address, space="memory")

        await self._flash_wait_for_not_busy(f"Flash command {flash_command.bits_repr(omit_zero=True)} failed")

    async def _flash_wait_for_not_busy(self, fail_msg="Failure detected"):
        flash_status = Flash_Status(Busy=1)
        while flash_status.Busy:
            flash_status = Flash_Status.from_int(
                await self.lower.read(Flash_Status_addr, space="memory"))
            self._log("read Flash_Status %s", flash_status.bits_repr(omit_zero=True))

            if flash_status.Busy_Err or flash_status.CMD_Err or flash_status.Protect_Err:
                raise MEC16xxError("%s with status %s"
                                   % (fail_msg,
                                      flash_status.bits_repr(omit_zero=True)))

    async def read_flash(self, address, count):
        await self._flash_clean_start()
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
        await self._flash_command(mode=Flash_Mode_Standby)
        return words

    async def erase_flash(self, address=0b11111 << 19):
        await self._flash_clean_start()
        await self._flash_command(mode=Flash_Mode_Erase, address=address)
        await self._flash_command(mode=Flash_Mode_Standby)

    async def program_flash(self, address, words):
        await self._flash_clean_start()
        await self._flash_command(mode=Flash_Mode_Program, address=address, burst=1)
        for offset, data in enumerate(words):
            await self.lower.write(Flash_Data_addr, data, space="memory")
            self._log("program Flash_Address=%05x Flash_Data=%08x", address + offset * 4, data)
        await self._flash_wait_for_not_busy()
        await self._flash_command(mode=Flash_Mode_Standby)

    async def is_eeprom_blocked(self):
        eeprom_status = EEPROM_Status.from_int(
                await self.lower.read(EEPROM_Status_addr, space="memory"))
        return eeprom_status.EEPROM_Block

    async def _eeprom_clean_start(self):
        if await self.is_eeprom_blocked():
            raise MEC16xxError(f"Error: EEPROM is blocked, no EEPROM operations are possible.")
        eeprom_command = EEPROM_Command(EEPROM_Mode=EEPROM_Mode_Standby)
        self._log("write EEPROM_Command %s", eeprom_command.bits_repr(omit_zero=True))
        await self.lower.write(EEPROM_Command_addr, eeprom_command.to_int(), space="memory")

        # Clear EEPROM controller error status.
        eeprom_clear_status = EEPROM_Status(Busy_Err=1, CMD_Err=1)
        self._log("clear EEPROM_Status %s", eeprom_clear_status.bits_repr(omit_zero=True))
        await self.lower.write(EEPROM_Status_addr, eeprom_clear_status.to_int(), space="memory")

    async def _eeprom_command(self, mode, address=0, burst=False):
        eeprom_command = EEPROM_Command(EEPROM_Mode=mode, Burst=burst)
        self._log("write EEPROM_Command %s", eeprom_command.bits_repr(omit_zero=True))
        await self.lower.write(EEPROM_Command_addr, eeprom_command.to_int(), space="memory")

        if mode != EEPROM_Mode_Standby:
            self._log("write EEPROM_Address=%08x", address)
            await self.lower.write(EEPROM_Address_addr, address, space="memory")

        await self._eeprom_wait_for_not_busy(f"EEPROM command {eeprom_command.bits_repr(omit_zero=True)} failed")

    async def _eeprom_wait_for_not_busy(self, fail_msg="Failure detected"):
        eeprom_status = EEPROM_Status(Busy=1)
        while eeprom_status.Busy:
            eeprom_status = EEPROM_Status.from_int(
                await self.lower.read(EEPROM_Status_addr, space="memory"))
            self._log("read EEPROM_Status %s", eeprom_status.bits_repr(omit_zero=True))

            if eeprom_status.Busy_Err or eeprom_status.CMD_Err:
                raise MEC16xxError("%s with status %s"
                                   % (fail_msg,
                                      eeprom_status.bits_repr(omit_zero=True)))

    async def _eeprom_wait_for_data_not_full(self, fail_msg="Failure detected"):
        eeprom_status = EEPROM_Status(Data_Full=1)
        while eeprom_status.Data_Full:
            eeprom_status = EEPROM_Status.from_int(
                await self.lower.read(EEPROM_Status_addr, space="memory"))
            self._log("read EEPROM_Status %s", eeprom_status.bits_repr(omit_zero=True))

            if eeprom_status.Busy_Err or eeprom_status.CMD_Err:
                raise MEC16xxError("%s with status %s"
                                   % (fail_msg,
                                      eeprom_status.bits_repr(omit_zero=True)))

    async def read_eeprom(self, address=0, count=EEPROM_SIZE):
        """Read all of the embedded 2KiB eeprom.

        Arguments:
        address -- byte address of first eeprom address
        count -- number of bytes to read
        """
        await self._eeprom_clean_start()
        await self._eeprom_command(EEPROM_Mode_Read, address = address, burst=True)
        bytes = []
        for offset in range(count):
            data = await self.lower.read(EEPROM_Data_addr, space="memory")
            self._log("read address=%05x EEPROM_Data=%08x",
                      address + offset, data)
            bytes.append(data)
        await self._eeprom_command(mode=EEPROM_Mode_Standby)
        return bytes

    async def erase_eeprom(self, address=0b11111 << 11):
        """Erase all or part of the embedded 2KiB eeprom.

        Arguments:
        address -- The default value of 0b11111 << 11 is a magic number that erases
                   the entire EEPROM. Otherwise one can specify the byte address of
                   a 8-byte page. The lower 3 bits must always be zero.
        """
        await self._eeprom_clean_start()
        await self._eeprom_command(mode=EEPROM_Mode_Erase, address=address)
        await self._eeprom_command(mode=EEPROM_Mode_Standby)

    async def program_eeprom(self, address, bytes):
        """ Program eeprom.

        Assumes that the area has already been erased.
        """
        await self._eeprom_clean_start()
        await self._eeprom_command(mode=EEPROM_Mode_Program, address=address, burst=1)
        for offset, data in enumerate(bytes):
            await self._eeprom_wait_for_data_not_full()
            await self.lower.write(EEPROM_Data_addr, data, space="memory")
            self._log("program EEPROM_Address=%05x EEPROM_Data=%08x", address + offset * 4, data)
        await self._eeprom_wait_for_not_busy()
        await self._eeprom_command(mode=EEPROM_Mode_Standby)

    async def unlock_eeprom(self, password):
        if not await self.is_eeprom_blocked():
            self._logger.log(logging.WARNING, "EEPROM is not blocked, there is nothing to unlock.")
            return
        await self.lower.write(EEPROM_Unlock_addr, password, space='memory')
        if await self.is_eeprom_blocked():
            raise MEC16xxError(f"Error: EEPROM wasn't unlocked!")
        else:
            self._logger.log(logging.INFO, "EEPROM has been successfully unlocked.")

class ProgramMEC16xxApplet(DebugARCApplet):
    logger = logging.getLogger(__name__)
    help = "program Microchip MEC16xx embedded controller via JTAG"
    description = """
    Read and write Microchip MEC16xx/MEC16xxi embedded controller integrated Flash
    via the JTAG interface.

    Per the MEC16xx datasheets, the minimum JTAG frequency should be 1 MHz.

    There are two types of erase operations that can be performed:

        * Emergency erase: It erases both the flash and eeprom (if the device has an eeprom),
          using a special JTAG sequence, which may work even in the case of boot code
          corruption
        * Non-emergency erase: (see commands erase-flash and erase-eeprom). This uses normal
          flash or eeprom controller commands to perform the erase, but if the target is
          protected, then it might fail.

    Typical flash sizes:

        * 192KiB: MEC1609(i), MEC1618(i), MEC1632, MEC1633
        * 256KiB: MEC1663

    To avoid data loss when the flash size is not known for certain, we recommend attempting
    to read 256KiB flash image, and analyzing the content.
    """

    async def run(self, device, args):
        arc_iface = await super().run(device, args)
        return await MEC16xxInterface(arc_iface, self.logger)

    @classmethod
    def add_interact_arguments(cls, parser):
        def password(arg):
            try:
                value = int(arg, 0)
            except ValueError:
                raise argparse.ArgumentTypeError("must be an integer (0x, 0b, and 0o prefixes are allowed for non-decimal bases)")
            if (value >> 31) != 0:
                raise argparse.ArgumentTypeError("must be between 0x0000_0000..0x7FFF_FFFF")
            return value

        def flash_size(arg):
            mult = 1
            if arg.endswith("K"):
                mult = 1024
                arg = arg[:-1]
            try:
                value = int(arg, 0)
            except ValueError:
                raise argparse.ArgumentTypeError("must be an integer (0x, 0b, and 0o prefixes are allowed for non-decimal bases, K suffix allowed for *1024)")
            value *= mult
            if value > FLASH_SIZE_MAX:
                raise argparse.ArgumentTypeError(f"given flash size of {value} bytes is larger than the maximum flash size of {FLASH_SIZE_MAX} bytes")
            return value

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

        p_emergency_erase = p_operation.add_parser(
            "emergency-erase", help="erase both flash and eeprom (emergency mode)")

        p_read_flash = p_operation.add_parser(
            "read-flash", help="read flash memory and save it to a binary file")
        p_read_flash.add_argument(
            "-s", "--size-bytes", metavar="FLASH_SIZE_BYTES", type=flash_size, required=True,
            help="size of the embedded flash memory in bytes (typically 192K or 256K. a K suffix means multiply by 1024)")
        p_read_flash.add_argument(
            "file", metavar="FILE", type=argparse.FileType("wb"),
            help="write flash binary image to FILE")

        p_erase_flash = p_operation.add_parser(
            "erase-flash", help="erase the flash (non-emergency mode)")

        p_write_flash = p_operation.add_parser(
            "write-flash", help="erase and write the flash memory")
        p_write_flash.add_argument(
            "file", metavar="FILE", type=argparse.FileType("rb"),
            help="read flash binary image from FILE")

        p_read_eeprom = p_operation.add_parser(
            "read-eeprom", help="read eeprom memory and save it to a binary file")
        p_read_eeprom.add_argument(
            "file", metavar="FILE", type=argparse.FileType("wb"),
            help="write eeprom binary image to FILE")

        p_erase_eeprom = p_operation.add_parser(
            "erase-eeprom", help="erase the eeprom (non-emergency mode)")

        p_write_eeprom = p_operation.add_parser(
            "write-eeprom", help="erase and write the eeprom memory")
        p_write_eeprom.add_argument(
            "file", metavar="FILE", type=argparse.FileType("rb"),
            help="read eeprom binary image from FILE")

        p_unlock_eeprom = p_operation.add_parser(
            "unlock-eeprom", help="unlock eeprom with a 31-bit password")
        p_unlock_eeprom.add_argument(
            "password", metavar="PASSWORD", type=password, help="password to try to unlock with")


    async def interact(self, device, args, mec_iface):
        if args.operation == "read-flash":
            await mec_iface.enable_flash_access(enabled=True)

            self.logger.info(f"reading {args.size_bytes} bytes from flash")
            if args.size_bytes < FLASH_SIZE_MAX:
                self.logger.warn("some MEC16xx devices contain 256KiB of flash, even if the datasheet only states 192KiB is available. " +
                                 "consider attempting this command with '-s 256K' as well to avoid data loss.")

            words = await mec_iface.read_flash(0, (args.size_bytes + 3) // 4)
            await mec_iface.enable_flash_access(enabled=False)

            bytes_left = args.size_bytes
            for word in words:
                args.file.write(struct.pack("<L", word)[:bytes_left])
                bytes_left -= 4

        if args.operation == "erase-flash":
            await mec_iface.enable_flash_access(enabled=True)
            await mec_iface.erase_flash()
            await mec_iface.enable_flash_access(enabled=False)

        if args.operation == "write-flash":
            file_bytes = args.file.read()
            size = len(file_bytes)
            if size > FLASH_SIZE_MAX:
                raise MEC16xxError(f"binary file size ({size} bytes) is larger than the maximum flash address space available ({FLASH_SIZE_MAX} bytes)")
            if size % 4:
                # Make sure we pad everything to a multiple of 4 byte words
                file_bytes += (4 - (size % 4)) * b'\xff' # 0xff is the empty state of flash memory
            words = [word[0] for word in struct.iter_unpack("<L", file_bytes)]

            self.logger.info(f"erasing the entire flash, and writing {size} bytes into it")
            if size < FLASH_SIZE_MAX:
                self.logger.info(f"flash locations beyond the size of the image being written will be left in the erased uninitialized state of 0xff")

            await mec_iface.enable_flash_access(enabled=True)
            await mec_iface.erase_flash()
            await mec_iface.program_flash(0, words)
            await mec_iface.enable_flash_access(enabled=False)

        if args.operation == "emergency-erase":
            await mec_iface.emergency_flash_erase()

        if args.operation == "read-eeprom":
            data = bytes(await mec_iface.read_eeprom())
            args.file.write(data)

        if args.operation == "erase-eeprom":
            await mec_iface.erase_eeprom()

        if args.operation == "write-eeprom":
            data = args.file.read()
            if len(data) != EEPROM_SIZE:
                raise MEC16xxError(f"Error: given eeprom file size ({len(data)} bytes) is different from the physical EEPROM size ({EEPROM_SIZE} bytes)")
            await mec_iface.erase_eeprom()
            await mec_iface.program_eeprom(0, data)

        if args.operation == "unlock-eeprom":
            await mec_iface.unlock_eeprom(args.password)
