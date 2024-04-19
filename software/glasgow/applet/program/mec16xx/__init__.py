
# Ref: Microchip MEC1618 Low Power 32-bit Microcontroller with Embedded Flash
# Document Number: DS00002339A
# Accession: G00005
# Ref: Microchip MEC1609 Mixed Signal Mobile Embedded Flash ARC EC BC-Link/VLPC Base Component
# Document Number: DS00002485A
# Accession: G00006

import logging
import argparse
import struct
import asyncio
import textwrap

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

    async def emergency_mass_erase(self):
        tap_iface = self.lower.lower

        # This sequence difference from the emergency mass erase sequence
        # that is described in the following ways:
        # * The polarity of VTR_POR and VCC_POR are described in contradic-
        #   tory ways in the datasheet. The emergency erase sequence describes
        #   it as active high, while the register description says it's active
        #   low. Experiments on MEC1663 show that it's really active-low
        # * The datasheet doesn't spell this out but the following sequence
        #   initializes VTR_POR and VCC_POR to its deasserted state before
        #   beginning the sequence
        # * At the end we also restore ME, and POR_EN.

        await tap_iface.write_ir(IR_RESET_TEST)
        dr_reset_test = DR_RESET_TEST(VTR_POR=1, VCC_POR=1)
        await tap_iface.write_dr(dr_reset_test.to_bits())

        dr_reset_test.POR_EN = 1
        await tap_iface.write_dr(dr_reset_test.to_bits())

        dr_reset_test.VTR_POR = 0
        await tap_iface.write_dr(dr_reset_test.to_bits())

        dr_reset_test.ME = 1
        await tap_iface.write_dr(dr_reset_test.to_bits())

        dr_reset_test.VTR_POR = 1
        await tap_iface.write_dr(dr_reset_test.to_bits())

        # The following flush is needed to ensure that we don't simply spend
        # the next sleep with the command that causes the mass erase queued up
        # but not executed
        await tap_iface.flush()

        WAIT_SECONDS = 1
        # In practice it has been observed that waiting 0.1 seconds is plenty
        self._logger.info(f"waiting {WAIT_SECONDS} second(s) to make sure emergency mass erase is complete")
        await asyncio.sleep(WAIT_SECONDS)

        dr_reset_test.ME = 0
        await tap_iface.write_dr(dr_reset_test.to_bits())

        dr_reset_test.VTR_POR = 0
        await tap_iface.write_dr(dr_reset_test.to_bits())

        dr_reset_test.VTR_POR = 1
        await tap_iface.write_dr(dr_reset_test.to_bits())

        dr_reset_test.POR_EN = 0
        await tap_iface.write_dr(dr_reset_test.to_bits())

        await tap_iface.flush()

        self._logger.warning("after running emergency mass erase, a power cycle may be required on some chips")

    async def reset_quick_halt(self):
        tap_iface = self.lower.lower

        await tap_iface.write_ir(IR_RESET_TEST)
        dr_reset_test = DR_RESET_TEST(VTR_POR=1, VCC_POR=1)
        await tap_iface.write_dr(dr_reset_test.to_bits())

        dr_reset_test.POR_EN = 1
        await tap_iface.write_dr(dr_reset_test.to_bits())

        dr_reset_test.VTR_POR = 0
        await tap_iface.write_dr(dr_reset_test.to_bits())

        await tap_iface.flush()

        dr_reset_test.VTR_POR = 1
        await tap_iface.write_dr(dr_reset_test.to_bits())

        await self.lower.force_halt(read_modify_write=False)

        dr_reset_test.POR_EN = 0
        await tap_iface.write_dr(dr_reset_test.to_bits())

        await tap_iface.flush()

    async def test_lock_data_block(self):
        # This will immediately cause flash_status.Data_Block to be asserted
        # because we're talking to the MEC over JTAG
        flash_config = Flash_Config.from_int(
            await self.lower.read(Flash_Config_addr, space="memory"))
        flash_config.Data_Protect = 1
        self._log("write Flash_Config %s", flash_config.bits_repr(omit_zero=True))
        await self.lower.write(Flash_Config_addr, flash_config.to_int(), space="memory")

    async def test_lock_boot_block(self):
        flash_config = Flash_Config.from_int(
            await self.lower.read(Flash_Config_addr, space="memory"))
        flash_config.Boot_Protect_En = 1
        self._log("write Flash_Config %s", flash_config.bits_repr(omit_zero=True))
        await self.lower.write(Flash_Config_addr, flash_config.to_int(), space="memory")
        # The following read will cause flash_status.Boot_Block to be asserted:
        await self.lower.read(4096, space="memory")

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

    async def _flash_wait_for_data_not_full(self, fail_msg="Failure detected"):
        flash_status = Flash_Status(Data_Full=1)
        while flash_status.Data_Full:
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

                self._logger.warning("read glitch Flash_Address=%05x Flash_Data=%08x/%08x/%08x",
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

    async def read_flash_burst(self, address, count):
        await self._flash_clean_start()
        words = []
        await self._flash_command(mode=Flash_Mode_Read, address=address, burst = 1)
        for offset in range(count-2):
            data = await self.lower.read(Flash_Data_addr, space="memory")
            self._log("read Flash_Address=%05x Flash_Data=%08x",
                      address + offset * 4, data)
            words.append(data)
        await self._flash_command(mode=Flash_Mode_Standby)

        # The last 2 words should be read out in non-burst mode, to prevent touching a potentially
        # protected Data Block region, and avoid causing a protection error

        for offset in range(count - 2, count):
            await self._flash_command(mode=Flash_Mode_Read, address=address + offset * 4, burst = 0)
            data = await self.lower.read(Flash_Data_addr, space="memory")
            self._log("read Flash_Address=%05x Flash_Data=%08x",
                      address + offset * 4, data)
            words.append(data)
            await self._flash_command(mode=Flash_Mode_Standby)

        return words

    async def erase_flash(self, address=0b11111 << 19):
        await self._flash_clean_start()
        await self._flash_command(mode=Flash_Mode_Erase, address=address)
        await self._flash_command(mode=Flash_Mode_Standby)

    async def erase_flash_range(self, address, size_bytes):
        page_size = 2048
        while size_bytes > 0:
            await self.erase_flash(address)
            address += page_size
            size_bytes -= page_size

    async def program_flash(self, address, words):
        await self._flash_clean_start()
        await self._flash_command(mode=Flash_Mode_Program, address=address, burst=1)
        for offset, data in enumerate(words):
            await self._flash_wait_for_data_not_full()
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

    This applet has been tested and works correctly on Lenovo Thinkshield-branded MEC1663
    (2024 january). This applet was originally developed to support MEC1618/MEC1618i, however
    the latest changes and fixes have not yet been tested on this device.

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
            "-f", "--force", action='store_true',
            help="force reading the flash even if it would result in an incomplete image due to security settings")
        p_read_flash.add_argument(
            "-b", "--burst", action='store_true',
            help="use burst read for speed. this may be unreliable on some MEC16xx variants")
        p_read_flash.add_argument(
            "file", metavar="FILE", type=argparse.FileType("wb"),
            help="write flash binary image to FILE")

        p_erase_flash = p_operation.add_parser(
            "erase-flash", help="erase the flash (non-emergency mode)")
        p_erase_flash.add_argument(
            "-f", "--force", action='store_true',
            help="force erasing the flash even if parts of it can't be erased due to security settings")
        p_erase_flash.add_argument(
            "-s", "--size-bytes", metavar="FLASH_SIZE_BYTES", type=flash_size,
            help="size of the embedded flash memory in bytes (typically 192K or 256K. a K suffix means multiply by 1024)")

        p_write_flash = p_operation.add_parser(
            "write-flash", help="erase and write the flash memory")
        p_write_flash.add_argument(
            "-f", "--force", action='store_true',
            help="force erasing and writing the flash even if parts of it can't be written due to security settings")
        p_write_flash.add_argument(
            "-s", "--size-bytes", metavar="FLASH_SIZE_BYTES", type=flash_size,
            help="size of the embedded flash memory in bytes (typically 192K or 256K. a K suffix means multiply by 1024)")
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

        p_security_status = p_operation.add_parser(
            "security-status", help="print security status")

        p_reset_quick_halt = p_operation.add_parser(
            "reset-quick-halt", help="perform a VTR POR reset, and then quickly attempt to force-halt the CPU")

        p_test_lock_data_block = p_operation.add_parser(
            "test-lock-data-block", help="temporarily lock data block, for testing purposes")

        p_test_lock_boot_block = p_operation.add_parser(
            "test-lock-boot-block", help="temporarily lock boot block, for testing purposes")


    async def interact(self, device, args, mec_iface):
        if args.operation in ['read-flash', 'erase-flash', 'write-flash']:
            if args.force and args.size_bytes is None:
                raise MEC16xxError(f"must also specify --size-bytes when using {args.operation} --force")

            flash_status = Flash_Status.from_int(
                await mec_iface.lower.read(Flash_Status_addr, space="memory"))

            starting_address = 0
            if flash_status.Boot_Block:
                if not args.force:
                    raise MEC16xxError("the flash_status.Boot_Block bit is asserted! this makes the lower 4KiB of flash (a.k.a. the Boot Block) "
                                   "inaccessible, and the non-emergency mass-erase is also disabled! If you wish to only access the non-protected "
                                   "regions with the current command, use --force. Also, it should still be possible to erase everything with the "
                                   "'emergency-erase' command.")
                else:
                    starting_address = 4096
                    self.logger.warning("skipping over the first 4KiB of flash (a.k.a. the Boot Block). It will not be erased/read/written. "
                                        "If reading, the output will be INCOMPLETE and will contain all 0xFFs")

            final_bytes_to_skip = 0
            if flash_status.Data_Block:
                if not args.force:
                    raise MEC16xxError("the flash_status.Data_Block bit is asserted! this makes the higher 4KiB of flash (a.k.a. the Data Block) "
                                   "inaccessible, and the non-emergency mass-erase is also disabled! If you wish to only access the non-protected "
                                   "regions with the current command, use --force. Also, it should still be possible to erase everything with the "
                                   "'emergency-erase' command.")
                else:
                    final_bytes_to_skip = 4096
                    self.logger.warning("skipping over the last 4KiB of flash (a.k.a. the Data Block). It will not be erased/read/written. "
                                        "If reading, the output will be INCOMPLETE and will contain all 0xFFs")

        if args.operation == "read-flash":
            await mec_iface.enable_flash_access(enabled=True)

            self.logger.info(f"reading {args.size_bytes} bytes from flash")
            if args.size_bytes < FLASH_SIZE_MAX:
                self.logger.warning("some MEC16xx devices contain 256KiB of flash, even if the datasheet only states 192KiB is available. "
                                    "consider attempting this command with '-s 256K' as well to avoid data loss.")

            real_size_bytes = args.size_bytes - starting_address - final_bytes_to_skip

            if args.burst:
                self.logger.warning("beware that burst has been observed to not work correctly in the past on some MEC16xx variants")
                words = await mec_iface.read_flash_burst(starting_address, (real_size_bytes + 3) // 4)
            else:
                self.logger.info("this may take many minutes. consider trying higher jtag clock speeds (e.g. '-f 4000'), and consider trying '--burst'. "
                                 "beware that burst has been observed to not work correctly in the past on some MEC16xx variants")
                words = await mec_iface.read_flash(starting_address, (real_size_bytes + 3) // 4)
            await mec_iface.enable_flash_access(enabled=False)

            bytes_left = real_size_bytes
            args.file.write(starting_address * b'\xff')
            for word in words:
                args.file.write(struct.pack("<L", word)[:bytes_left])
                bytes_left -= 4
            args.file.write(final_bytes_to_skip * b'\xff')

        if args.operation == "erase-flash":

            await mec_iface.enable_flash_access(enabled=True)
            if starting_address or final_bytes_to_skip:
                await mec_iface.erase_flash_range(starting_address, args.size_bytes - starting_address - final_bytes_to_skip)
            else:
                await mec_iface.erase_flash()
            await mec_iface.enable_flash_access(enabled=False)

        if args.operation == "write-flash":
            file_bytes = args.file.read()
            file_size = len(file_bytes)
            if file_size > FLASH_SIZE_MAX:
                raise MEC16xxError(f"binary file size ({file_size} bytes) is larger than the maximum flash address space available ({FLASH_SIZE_MAX} bytes)")
            flash_size = args.size_bytes or file_size
            if file_size > flash_size:
                raise MEC16xxError(f"binary file size ({file_size} bytes) is larger than the specified flash size ({flash_size} bytes)")
            if file_size > flash_size - final_bytes_to_skip:
                tail = file_bytes[flash_size - final_bytes_to_skip:]
                if tail != len(tail) * b'\xff':
                    self.logger.warning("the specified flash image has non-empty Data Block (the final 4KiB). that area will not be written.")
            if starting_address:
                head = file_bytes[:starting_address]
                if head != len(head) * b'\xff':
                    self.logger.warning("the specified flash image has non-empty Boot Block (the first 4KiB). that area will not be written.")
            toflash_bytes = file_bytes[starting_address:flash_size - final_bytes_to_skip]
            if len(toflash_bytes) % 4:
                # Make sure we pad everything to a multiple of 4 byte words
                toflash_bytes += (4 - (len(toflash_bytes) % 4)) * b'\xff' # 0xff is the empty state of flash memory
            words = [word[0] for word in struct.iter_unpack("<L", toflash_bytes)]

            await mec_iface.enable_flash_access(enabled=True)
            if starting_address or final_bytes_to_skip:
                flash_accessible_size = args.size_bytes - starting_address - final_bytes_to_skip
                self.logger.info(f"partially erasing the flash, and writing {len(toflash_bytes)} bytes into it")
                if len(toflash_bytes) < flash_accessible_size:
                    self.logger.info(f"unprotected flash locations beyond the size of the image being written will be left in the erased uninitialized state of 0xff")
                await mec_iface.erase_flash_range(starting_address, flash_accessible_size)
            else:
                self.logger.info(f"erasing the entire flash, and writing {len(toflash_bytes)} bytes into it")
                if len(toflash_bytes) < FLASH_SIZE_MAX:
                    self.logger.info(f"flash locations beyond the size of the image being written will be left in the erased uninitialized state of 0xff")
                await mec_iface.erase_flash()
            await mec_iface.program_flash(starting_address, words)
            await mec_iface.enable_flash_access(enabled=False)

        if args.operation == "emergency-erase":
            await mec_iface.emergency_mass_erase()

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

        if args.operation == "reset-quick-halt":
            await mec_iface.reset_quick_halt()

        if args.operation == "test-lock-data-block":
            await mec_iface.test_lock_data_block()

        if args.operation == "test-lock-boot-block":
            await mec_iface.test_lock_boot_block()

        if args.operation in ("security-status", "reset-quick-halt", "test-lock-data-block", "test-lock-boot-block"):
            flash_status = Flash_Status.from_int(
                await mec_iface.lower.read(Flash_Status_addr, space="memory"))

            self.logger.info(textwrap.dedent(f"""
                Security status:
                Boot_Block = {flash_status.Boot_Block}
                Data_Block = {flash_status.Data_Block}
                EEPROM_Block = {await mec_iface.is_eeprom_blocked()}"""))
