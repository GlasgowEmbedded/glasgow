import logging
import argparse
import asyncio
import textwrap
import os

from ....support.aobject import *
from ... import *
from ...interface.issp_host import ISSPHostApplet
from fx2.format import input_data, output_data
from . import vectors

class Psoc1Error(GlasgowAppletError):
    pass

class SyncEnabledContext:
    def __init__(self, fconfig, iface):
        self.fconfig = fconfig
        self.iface = iface

    async def __aenter__(self):
        if self.fconfig.has_sync_en_dis_cmd:
            await self.iface.lower.send_bitstring(vectors.SYNC_ENABLE, do_poll=0, do_zero_bits=0)

    async def __aexit__(self, exc_type, exc, tb):
        if exc is None and self.fconfig.has_sync_en_dis_cmd:
            await self.iface.lower.send_bitstring(vectors.SYNC_DISABLE, do_poll=0, do_zero_bits=0)

class Psoc1Interface(aobject):
    async def __init__(self, interface, logger, voltage, has_xres):
        self.lower = interface
        self._logger = logger
        self._level = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._voltage = voltage
        self._has_xres = has_xres

    def _log(self, message, *args):
        self._logger.log(self._level, "PSoC1: " + message, *args)

    async def _power_cycle(self):
        device = self.lower.lower.device
        VA = await device.get_voltage('A')
        VB = await device.get_voltage('A')
        await device.reset_alert("AB")
        await device.set_voltage("AB", 0.0)
        await device.poll_alert()
        await asyncio.sleep(0.100)
        await device.set_voltage("A", VA)
        await device.set_voltage("B", VB)
        await asyncio.sleep(0.001) # TVDDWait, but it's hard to control this precisely

    async def initialize_and_get_silicon_id(self, fconfig):
        await self.lower.low_sclk()
        if self._has_xres:
            await self.lower.assert_xres()
            await asyncio.sleep(0.001)
        else:
            self._logger.warn("Warning: Using power-cycle method, because no xres pin has been specified. "+
                              "The power-cycle method is experimental, and doesn't tightly control timing")
            await self._power_cycle()
        if fconfig.init_type == 0:
            await self.lower.send_bitstring(vectors.INITIALIZE_1,
                needs_single_clock_pulse_for_poll=fconfig.needs_single_clock_pulse_for_poll,
                needs_arbitrary_clocks_for_poll=fconfig.needs_arbitrary_clocks_for_poll)
            await self.lower.send_bitstring(vectors.INITIALIZE_2,
                needs_single_clock_pulse_for_poll=fconfig.needs_single_clock_pulse_for_poll,
                needs_arbitrary_clocks_for_poll=fconfig.needs_arbitrary_clocks_for_poll)
            if self._voltage > 3.6:
                await self.lower.send_bitstring(vectors.INITIALIZE_3_5V, do_poll=0)
            else:
                await self.lower.send_bitstring(vectors.INITIALIZE_3_3V, do_poll=0)
            await self.lower.send_bitstring(vectors.ID_SETUP,
                needs_single_clock_pulse_for_poll=fconfig.needs_single_clock_pulse_for_poll,
                needs_arbitrary_clocks_for_poll=fconfig.needs_arbitrary_clocks_for_poll)
            silicon_id = await self.lower.read_bytes(0b11111000, 2)
            return vectors.SiliconId(*silicon_id)
        elif fconfig.init_type == 1:
            await self.lower.send_bitstring(vectors.ID_SETUP_1,
                needs_single_clock_pulse_for_poll=fconfig.needs_single_clock_pulse_for_poll,
                needs_arbitrary_clocks_for_poll=fconfig.needs_arbitrary_clocks_for_poll)
            await self.lower.send_bitstring(vectors.ID_SETUP_2,
                needs_single_clock_pulse_for_poll=fconfig.needs_single_clock_pulse_for_poll,
                needs_arbitrary_clocks_for_poll=fconfig.needs_arbitrary_clocks_for_poll)
            async with SyncEnabledContext(fconfig, self):
                silicon_id = (*await self.lower.read_bytes(0b1111_1000, 2),
                              *await self.lower.read_bytes(0b1111_0011, 1, reg_not_mem=1),
                              *await self.lower.read_bytes(0b1111_0000, 1, reg_not_mem=1))
            return vectors.SiliconId(*silicon_id)

    async def release_bus(self):
        await self.lower.float_sclk()
        await self.lower.float_xres()

    async def set_block_num(self, number):
        if number < 0 or number > 255:
            raise Psoc1Error("Block number out of range\n")
        await self.lower.write_bytes(0b11111010, (number,))

    async def set_bank_num(self, number):
        """
        Only supported by RevL-covered devices
        """
        assert number >= 0
        assert number <= 3
        await self.lower.send_bitstring( \
            ("1101111011100010000111" + \
             "11011111010000000dd111" + \
             "1101111011100000000111").replace( \
            "dd", f"{number:02b}"), do_poll=0, do_zero_bits=0)

    @staticmethod
    def _slowed_down_bitstring(bitstring, padding_between_mnemonics=100):
        """Adds 0-bit padding between 22-bit mnemonics. The purpose is to space out the mnemonics in time.
        Doing it this way is nicer then implementing another counter in hardware, and also better (quicker) than
        waiting for a delay on the host.
        """
        return ("0" * padding_between_mnemonics).join([bitstring[i:i+22] for i in range(0, len(bitstring), 22)])

    async def get_security(self, fconfig):
        if fconfig.read_security_type in (1, 2):
            await self.lower.send_bitstring(vectors.GET_SECURITY,
                needs_single_clock_pulse_for_poll=fconfig.needs_single_clock_pulse_for_poll,
                needs_arbitrary_clocks_for_poll=fconfig.needs_arbitrary_clocks_for_poll)
            return await self.lower.read_bytes(0b1000_0000, fconfig.secure_bytes_per_bank)
        elif fconfig.read_security_type in (3, 4):
            await self.lower.send_bitstring(vectors.READ_SECURITY_SETUP, do_poll=0, do_zero_bits=0)
            assert fconfig.secure_bytes_per_bank <= (2 ** 7)
            for address in range(fconfig.secure_bytes_per_bank):
                address_bitstr = f"{address:07b}"
                assert len(address_bitstr) == 7
                async with SyncEnabledContext(fconfig, self):
                    read_security_1_modified = self._slowed_down_bitstring(vectors.READ_SECURITY_1.replace("aaaaaaa", address_bitstr), 100)
                    # Note: it has been observed that for part CY8C24493, when running at 8MHz, this vector is sensitive to how spaced-out
                    # its mnemonics are. At 1MHz it runs fine, but at some point above that it starts returning corrupt data. For this reason
                    # we space it out, so it works correctly at all supported frequencies. Note that a spacing of 15 "0" clock cycles has
                    # been observed as sufficient (while 14 wasn't), however we've chosen to employ 100 for paranoia reasons.
                    await self.lower.send_bitstring(read_security_1_modified, do_poll=0, do_zero_bits=0)
                if fconfig.read_security_type == 3:
                    await self.lower.send_bitstring(vectors.READ_SECURITY_2,
                        needs_single_clock_pulse_for_poll=fconfig.needs_single_clock_pulse_for_poll,
                        needs_arbitrary_clocks_for_poll=fconfig.needs_arbitrary_clocks_for_poll)
                    await self.lower.send_bitstring(vectors.READ_SECURITY_3.replace("aaaaaaa", address_bitstr),
                        needs_single_clock_pulse_for_poll=fconfig.needs_single_clock_pulse_for_poll,
                        needs_arbitrary_clocks_for_poll=fconfig.needs_arbitrary_clocks_for_poll)
                elif fconfig.read_security_type == 4:
                    await self.lower.send_bitstring(vectors.READ_SECURITY_2, do_poll=0)
                    await self.lower.send_bitstring(vectors.READ_SECURITY_3.replace("aaaaaaa", address_bitstr), do_poll=0)
            async with SyncEnabledContext(fconfig, self):
                return await self.lower.read_bytes(0b1000_0000, fconfig.secure_bytes_per_bank)
        else:
            raise Psoc1Error("This device doesn't support reading security information")

    async def set_security(self, fconfig, data):
        async with SyncEnabledContext(fconfig, self):
            if fconfig.has_read_write_setup:
                await self.lower.send_bitstring(vectors.READ_WRITE_SETUP, do_poll=0, do_zero_bits=0)
            await self.lower.write_bytes(0b1000_0000, data)
            await self.lower.send_bitstring(vectors.SET_SECURITY[fconfig.set_security_type],
                needs_single_clock_pulse_for_poll=fconfig.needs_single_clock_pulse_for_poll,
                needs_arbitrary_clocks_for_poll=fconfig.needs_arbitrary_clocks_for_poll)
            await self.lower.wait_pending()

    async def reset_run(self):
        if self._has_xres:
            await self.lower.assert_xres()
            await asyncio.sleep(0.001)
            await self.lower.deassert_xres()
            await self.lower.float_xres()
        else:
            self._logger.info("Power-cycling instead of resetting device because not xres pin has been specified")
            await self._power_cycle()

    async def bulk_erase(self, fconfig):
        if fconfig.erase_type == 0:
            await self.lower.send_bitstring(vectors.BULK_ERASE,
                needs_single_clock_pulse_for_poll=fconfig.needs_single_clock_pulse_for_poll,
                needs_arbitrary_clocks_for_poll=fconfig.needs_arbitrary_clocks_for_poll)
        elif fconfig.erase_type == 1:
            await self.lower.send_bitstring(vectors.ERASE,
                needs_single_clock_pulse_for_poll=fconfig.needs_single_clock_pulse_for_poll,
                needs_arbitrary_clocks_for_poll=fconfig.needs_arbitrary_clocks_for_poll)

    async def read_block(self, fconfig, block_num):
        if fconfig.has_read_write_setup:
            await self.lower.send_bitstring(vectors.READ_WRITE_SETUP, do_poll=0, do_zero_bits=0)

        async with SyncEnabledContext(fconfig, self):
            await self.set_block_num(block_num)

        await self.lower.send_bitstring(vectors.VERIFY_SETUP[fconfig.verify_setup_type],
            needs_single_clock_pulse_for_poll=fconfig.needs_single_clock_pulse_for_poll,
            needs_arbitrary_clocks_for_poll=fconfig.needs_arbitrary_clocks_for_poll)

        # It's been observed that verify_setup sometimes needs a little bit of
        # additional time, especially when running the interface at 8MHz, otherwise
        # the first byte read will be corrupt:
        await self.lower.wait_pending()
        await asyncio.sleep(0.001)

        async with SyncEnabledContext(fconfig, self):
            if fconfig.has_read_status:
                status = (await self.lower.read_bytes(0b1111_1000, 1))[0]
                if status == 0x01:
                    raise Psoc1Error(f"While reading flash block {block_num} has been reported as secured!")

            if fconfig.has_read_write_setup:
                await self.lower.send_bitstring(vectors.READ_WRITE_SETUP, do_poll=0, do_zero_bits=0)

            return await self.lower.read_bytes(0b1000_0000, fconfig.bytes_per_block)

    async def write_block(self, fconfig, block_num, data, wait_pending=True):
        program_block = vectors.PROGRAM_BLOCK[fconfig.program_block_type]

        if fconfig.has_sync_en_dis_cmd:
            await self.lower.send_bitstring(vectors.SYNC_ENABLE, do_poll=0, do_zero_bits=0)

        if fconfig.has_read_write_setup:
            await self.lower.send_bitstring(vectors.READ_WRITE_SETUP, do_poll=0, do_zero_bits=0)

        await self.lower.write_bytes(0b1000_0000, data)

        async with SyncEnabledContext(fconfig, self):
            await self.set_block_num(block_num)

        await self.lower.send_bitstring(program_block,
            needs_single_clock_pulse_for_poll=fconfig.needs_single_clock_pulse_for_poll,
            needs_arbitrary_clocks_for_poll=fconfig.needs_arbitrary_clocks_for_poll)

        if fconfig.has_read_status:
            async with SyncEnabledContext(fconfig, self):
                status = (await self.lower.read_bytes(0b1111_1000, 1))[0]
                if status == 0x04:
                    raise Psoc1Error("Programming failure reported!")
                elif status != 0x00:
                    raise Psoc1Error(f"Unknown programming status code reported: 0x{status:02x}!")
        elif wait_pending:
            await self.lower.wait_pending()

    async def get_checksum(self, fconfig):
        checksum_setup = vectors.CHECKSUM_SETUP[fconfig.checksum_setup_type]
        if checksum_setup is None:
            return None
        await self.lower.send_bitstring(checksum_setup,
            needs_single_clock_pulse_for_poll=fconfig.needs_single_clock_pulse_for_poll,
            needs_arbitrary_clocks_for_poll=fconfig.needs_arbitrary_clocks_for_poll)
        async with SyncEnabledContext(fconfig, self):
            return [(await self.lower.read_bytes(0b1111_1001, 1))[0],
                    (await self.lower.read_bytes(0b1111_1000, 1))[0]]

class ProgramPsoc1Applet(ISSPHostApplet):
    logger = logging.getLogger(__name__)
    help = "program Cypress PSoC1 microcontrollers via ISSP"
    description = """
    Read and write Cypress PSoC1 microcontrollers via the ISSP interface.

    This applet has been tested and works correctly on the following devices (as of Aug 2024):

        * CY8C24493
        * CY8C24894
        * CY8C21434
        * CY8C27643
        * CY8C29666

    Per the ISSP spec, the maximum frequency should be 8MHz.
    All commands except for reset-run must receive a valid part number to check against.
    When connecting to an unknown chip, please be aware that there are two groups of chips supported
    by this applet, and their initialization sequence, up to the point where silicon ID can be read
    differs. One group is chips described by ISSP specs RevK, RevL (aka AN2026a and AN2026b),
    and the other group is described by RevI (aka AN2026c). If you want to use the "get-silicon-id"
    command to find out what chip you're connected to you may pass a different part number to that
    command as long as it is withing the same group of chips, it should be able to read the Silicon ID.
    If reading the silicon ID succeeds, the console log messages will report the correct part number.
    """

    async def run(self, device, args):
        issp_iface = await super().run(device, args)
        return await Psoc1Interface(issp_iface, self.logger, args.voltage, has_xres = hasattr(args, "pin_xres") and args.pin_xres is not None)

    @classmethod
    def add_interact_arguments(cls, parser):
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

        p_get_silicon_id = p_operation.add_parser(
            "get-silicon-id", help="read package-specific silicon ID from the target")
        p_get_silicon_id.add_argument(
            "-p", "--part", metavar="PART_NUMBER", type=str, required=True,
            help="specify part number to get silicon ID from")

        p_reset_run = p_operation.add_parser(
            "reset-run", help="assert and deassert reset, allowing the chip to boot")

        p_bulk_erase = p_operation.add_parser(
            "bulk-erase", help="bulk erase flash memory")
        p_bulk_erase.add_argument(
            "-p", "--part", metavar="PART_NUMBER", type=str, required=True,
            help="specify part number to bulk erase")
        p_bulk_erase.add_argument(
            "-f", "--force", action='store_true',
            help="ignore some errors that can be ignored")

        p_read_flash = p_operation.add_parser(
            "read-flash", help="read flash memory and save it to a binary file")
        p_read_flash.add_argument(
            "-p", "--part", metavar="PART_NUMBER", type=str, required=True,
            help="specify part number we're reading flash from")
        p_read_flash.add_argument(
            "-f", "--force", action='store_true',
            help="ignore some errors that can be ignored")
        p_read_flash.add_argument(
            "file", metavar="FILE", type=argparse.FileType("wb"),
            help="write flash binary image to FILE")

        p_get_security = p_operation.add_parser(
            "get-security", help="get security status of the device")
        p_get_security.add_argument(
            "-p", "--part", metavar="PART_NUMBER", type=str, required=True,
            help="specify part number we're getting security information from")
        p_get_security.add_argument(
            "-f", "--force", action='store_true',
            help="ignore some errors that can be ignored")

        p_program = p_operation.add_parser(
            "program", help="bulk erase and program the flash memory")
        p_program.add_argument(
            "-p", "--part", metavar="PART_NUMBER", type=str, required=True,
            help="specify part number we're programming")
        p_program.add_argument(
            "-f", "--force", action='store_true',
            help="ignore some errors that can be ignored")
        p_program.add_argument(
            "--ihex", action='store_true',
            help="use intel hex file format, instead of trying to auto-detect it")
        p_program.add_argument(
            "--bin", action='store_true',
            help="use binary file format, instead of trying to auto-detect it")
        p_program.add_argument(
            "--no-verify", action='store_true',
            help="skip verification of data bytes written")
        p_program.add_argument(
            "--no-write-security", action='store_true',
            help="skip writing security information")
        p_program.add_argument(
            "--no-verify-security", action='store_true',
            help="don't verify written security information (security is verified by default only on devices on which we're sure security verification is supported)")
        p_program.add_argument(
            "--verify-security", action='store_true',
            help="verify written security information (security is verified by default only on devices on which we're sure security verification is supported)")
        p_program.add_argument(
            "--no-check-checksum", action='store_true',
            help="skip checking device-calculated checksum")
        p_program.add_argument(
            "file", metavar="FILE", type=argparse.FileType("rb"),
            help="read flash binary image from FILE")

        p_verify_full = p_operation.add_parser(
            "verify-full", help="fully verify the flash memory content matches given file (only works if security doesn't prevent flash read)")
        p_verify_full.add_argument(
            "-p", "--part", metavar="PART_NUMBER", type=str, required=True,
            help="specify part number we're verifying")
        p_verify_full.add_argument(
            "-f", "--force", action='store_true',
            help="ignore some errors that can be ignored")
        p_verify_full.add_argument(
            "--ihex", action='store_true',
            help="use intel hex file format, instead of trying to auto-detect it")
        p_verify_full.add_argument(
            "--bin", action='store_true',
            help="use binary file format, instead of trying to auto-detect it")
        p_verify_full.add_argument(
            "--no-check-checksum", action='store_true',
            help="skip checking device-calculated checksum")
        p_verify_full.add_argument(
            "file", metavar="FILE", type=argparse.FileType("rb"),
            help="read flash binary image from FILE")

        p_verify_checksum = p_operation.add_parser(
            "verify-checksum", help="Compare the checksum calculated by the device against the checksum found in the input file.")
        p_verify_checksum.add_argument(
            "-p", "--part", metavar="PART_NUMBER", type=str, required=True,
            help="specify part number we're verifying")
        p_verify_checksum.add_argument(
            "-f", "--force", action='store_true',
            help="ignore some errors that can be ignored")
        p_verify_checksum.add_argument(
            "--ihex", action='store_true',
            help="use intel hex file format, instead of trying to auto-detect it")
        p_verify_checksum.add_argument(
            "--bin", action='store_true',
            help="use binary file format, instead of trying to auto-detect it")
        p_verify_checksum.add_argument(
            "--no-verify-security", action='store_true',
            help="don't verify written security information (security is verified by default only on devices on which we're sure security verification is supported)")
        p_verify_checksum.add_argument(
            "--verify-security", action='store_true',
            help="verify written security information (security is verified by default only on devices on which we're sure security verification is supported)")
        p_verify_checksum.add_argument(
            "file", metavar="FILE", type=argparse.FileType("rb"),
            help="read flash binary image from FILE")

    @staticmethod
    def count_flash_bytes(chunks):
        cnt_bytes = 0
        for address, chunk in chunks:
            if address <= 0x100000:
                if address + len(chunk) <= 0x100000:
                    cnt_bytes += len(chunk)
                else:
                    cnt_bytes += 0x100000 - address
        return cnt_bytes

    @staticmethod
    def get_bytes(chunks, starting_address, length):
        bytes = []
        for address, chunk in chunks:
            if chunk:
                if (address < starting_address + length) and \
                   (address + len(chunk) > starting_address):
                    if address < starting_address:
                        chunk = chunk[starting_address - address:]
                        address = starting_address
                    if address - starting_address + len(chunk) > length:
                        chunk = chunk[:length - (address - starting_address)]
                    if address - starting_address > len(bytes):
                        bytes.extend([0] * (address - starting_address - len(bytes)))
                    bytes[address - starting_address: address - starting_address + len(chunk)] = chunk
        return bytes

    @staticmethod
    def get_flash_bytes(chunks, bytes_per_block):
        """ Return contiguous flash bytes derived from chunks returned by input_data() """
        bytes = ProgramPsoc1Applet.get_bytes(chunks, 0, 0x100000)
        if len(bytes) % bytes_per_block:
            bytes.extend([0x0] * (bytes_per_block - (len(bytes) % bytes_per_block)))
        return bytes

    @staticmethod
    def get_security_bytes(chunks, secure_bytes_per_bank):
        """ Get security bytes from ihex chunks """
        bytes = ProgramPsoc1Applet.get_bytes(chunks, 0x100000, 128)
        if len(bytes) % secure_bytes_per_bank:
            bytes.extend([0x0] * (secure_bytes_per_bank - (len(bytes) % secure_bytes_per_bank)))
        return bytes

    @staticmethod
    def get_checksum_bytes(chunks):
        """ Get security bytes from ihex chunks """
        bytes = ProgramPsoc1Applet.get_bytes(chunks, 0x200000, 64)
        return bytes

    def error_or_warning(self, only_warn, message):
        if only_warn:
            self.logger.warn(message)
        else:
            raise Psoc1Error(message + " (You may skip over this error by using -f/--force)")

    async def _get_all_security(self, iface, fconfig):
        if fconfig.banks:
            block = []
            for current_bank in range(fconfig.banks):
                await iface.set_bank_num(current_bank)
                block.extend(await iface.get_security(fconfig))
        else:
            block = await iface.get_security(fconfig)
        return block

    def _check_silicon_id_is_as_expected(self, args, silicon_id):
        expected_silicon_id = vectors.get_expected_silicon_id(args.part)
        if hasattr(args, 'force'):
            force = args.force
        else:
            force = True
        if silicon_id == expected_silicon_id:
            self.logger.info(f"Verify Silicon ID Procedure succeeded. Silicon ID is: {str(silicon_id)}")
        elif expected_silicon_id is None:
            self.error_or_warning(force, f"Unable to Verify Silicon ID {str(silicon_id)}. We don't know what the silicon ID of {args.part} is supposed to be. Please consider contributing the silicon ID.")
        else:
            self.error_or_warning(force, f"Unexpected silicon ID: got {str(silicon_id)} instead of {str(expected_silicon_id)}")

    async def interact(self, device, args, iface):
        if hasattr(args, 'part'):
            fconfig = vectors.flash_config[args.part]
            if fconfig is None:
                raise Psoc1Error(f"Part number {args.part} not recognized.")
            if fconfig.banks:
                fconfig_bytes = fconfig.bytes_per_block * fconfig.blocks * fconfig.banks
                self.logger.info(f"Part number {args.part} has {fconfig_bytes/1024:.1f} KiB flash ({fconfig.bytes_per_block} bytes/block, {fconfig.blocks} blocks/bank, {fconfig.banks} banks).")
            else:
                fconfig_bytes = fconfig.bytes_per_block * fconfig.blocks
                self.logger.info(f"Part number {args.part} has {fconfig_bytes/1024:.1f} KiB flash ({fconfig.bytes_per_block} bytes/block, {fconfig.blocks} blocks).")
        else:
            assert args.operation in ("reset-run",) # only command that doesn't require part number to be specified
        if args.operation == "get-silicon-id":
            silicon_id = await iface.initialize_and_get_silicon_id(fconfig)
            await iface.release_bus()
            matching = []
            for sid, part in vectors.silicon_ids:
                if sid == silicon_id:
                    matching.append(part)
            if matching:
                strmatching = " / ".join([str(m) for m in matching])
                self.logger.info(f"Found known chip: {strmatching} {str(silicon_id)}")
            else:
                self.logger.warn(f"Found unknown chip: {str(silicon_id)}")
            self._check_silicon_id_is_as_expected(args, silicon_id)
        elif args.operation == "reset-run":
            await iface.reset_run()
        elif args.operation == "bulk-erase":
            silicon_id = await iface.initialize_and_get_silicon_id(fconfig)
            self._check_silicon_id_is_as_expected(args, silicon_id)
            await iface.bulk_erase(fconfig)
            self.logger.info("Executed Bulk Erase")
            await iface.release_bus()
        elif args.operation == "get-security":
            silicon_id = await iface.initialize_and_get_silicon_id(fconfig)
            self._check_silicon_id_is_as_expected(args, silicon_id)
            if fconfig.read_security_type == 1:
                self.logger.warn(f"This part number may or may not support the vectors for reading security information. The matching ISSP specs don't document it, but at least some devices have been found supporting it. Use your own judgement whether you want to trust these results.")
            block = await self._get_all_security(iface, fconfig)
            await iface.release_bus()
            self.logger.info(f"The following security bytes have been read: {', '.join([hex(b) for b in block])}")
            self.logger.info("Interpretation:")

            def get_desc_encoded(bank, blockno):
                i = bank * fconfig.blocks + blockno
                if blockno < fconfig.blocks:
                    return (block[i // 4] >> ((i % 4) * 2)) & 3
                return None

            def human_readable_desc(enc):
                lookup = {
                    0: "U = Unprotected",
                    1: "F = Factory upgrade (external and internal writes are permitted)",
                    2: "R = Field upgrade (internal writes permitted)",
                    3: "W = Full protection",
                }
                return f"{enc:02b}b: {lookup[enc]}"

            def explain_bank(prefix_string, bank):
                last_explained = -1
                for i in range(fconfig.blocks):
                    desc = get_desc_encoded(bank, i)
                    next_desc = get_desc_encoded(bank, i+1)
                    if desc != next_desc:
                        self.logger.info(f"    {prefix_string}Blocks {last_explained+1}..{i}: {human_readable_desc(desc)}")
                        last_explained = i

            if fconfig.banks:
                for i in range(fconfig.banks):
                    explain_bank(f"Bank {i} ", i)
            else:
                explain_bank("", 0)

        elif args.operation == "read-flash":
            silicon_id = await iface.initialize_and_get_silicon_id(fconfig)
            self._check_silicon_id_is_as_expected(args, silicon_id)

            current_block = 0
            current_bank = 0
            for sbyte in range(0, fconfig_bytes, fconfig.bytes_per_block):
                print(f"\rReading [{sbyte * 100 // fconfig_bytes}%]", end="")
                if fconfig.banks != 0:
                    if current_block == 0:
                        await iface.set_bank_num(current_bank)
                else:
                    assert current_bank == 0
                block = await iface.read_block(fconfig, current_block)
                args.file.write(bytes(block))
                current_block += 1
                if current_block >= fconfig.blocks:
                    current_block = 0
                    current_bank += 1
            print("\rReading [100%]\n", end="")
            self.logger.info(f"Written {fconfig_bytes} bytes to {args.file.name}.")
            self.logger.warning(f"Warning: this only returned valid data, if security was disabled!")
            await iface.release_bus()
        elif args.operation in ("program", "verify-full", "verify-checksum"):
            ext = os.path.splitext(args.file.name)[1].lower()
            if args.bin:
                format = "bin"
            elif args.ihex:
                format = "ihex"
            else:
                if ext in (".hex", ".ihex", ".ihx"):
                    format = "ihex"
                elif ext in (".bin",):
                    format = "bin"
                else:
                    raise Psoc1Error("Cannot autodetect file format based on file extension. Please specify --ihex or --bin.")
            data = input_data(args.file, format)
            databytes = self.get_flash_bytes(data, fconfig.bytes_per_block)
            lbytes = len(databytes)
            count_nonpad_bytes = self.count_flash_bytes(data)
            assert count_nonpad_bytes <= lbytes
            if lbytes > fconfig_bytes:
                self.error_or_warning(args.force, f"Input file contains {lbytes} bytes, which is more than the flash size.")
            if count_nonpad_bytes < fconfig_bytes:
                self.logger.warn(f"Input file contains {count_nonpad_bytes} bytes (not including padding), which is less than the flash size. This operation will erase the whole flash, so all data will be overwritten")

            silicon_id = await iface.initialize_and_get_silicon_id(fconfig)
            self._check_silicon_id_is_as_expected(args, silicon_id)

            if args.operation in ("program",):
                self.logger.info("Performing bulk erase.")
                await iface.bulk_erase(fconfig)
                current_block = 0
                current_bank = 0
                for sbyte in range(0, lbytes, fconfig.bytes_per_block):
                    print(f"\rProgramming [{sbyte * 100 // lbytes}%]", end="")
                    if fconfig.banks != 0:
                        if current_block == 0:
                            await iface.set_bank_num(current_bank)
                    else:
                        assert current_bank == 0
                    block = databytes[sbyte: sbyte + fconfig.bytes_per_block]
                    await iface.write_block(fconfig, current_block, block)
                    current_block += 1
                    if current_block >= fconfig.blocks:
                        current_block = 0
                        current_bank += 1
                print("\rProgramming [100%]\n", end="")
                self.logger.info(f"Programmed {lbytes} bytes.")

            if args.operation == "verify-full" or (args.operation == "program" and not args.no_verify):
                current_block = 0
                current_bank = 0
                for sbyte in range(0, lbytes, fconfig.bytes_per_block):
                    print(f"\rVerifying [{sbyte * 100 // lbytes}%]", end="")
                    if fconfig.banks != 0 and current_block == 0:
                        await iface.set_bank_num(current_bank)
                    block = await iface.read_block(fconfig, current_block)
                    for i in range(len(block)):
                        if block[i] != databytes[sbyte + i]:
                            print("")
                            self.logger.error(f"Error at offset 0x{sbyte+i:04x}, expected: 0x{databytes[sbyte+i]:02x} got: 0x{block[i]:02x}")
                            if args.operation == "verify-full":
                                self.logger.info("Note that verification is only expected to work when security is not enabled. Consider running only verify-checksum.")
                            raise Psoc1Error(f"Verification failed!")
                    current_block += 1
                    if current_block >= fconfig.blocks:
                        current_block = 0
                        current_bank += 1
                print("\rVerifying [100%]\n", end="")
                self.logger.info(f"Verified {lbytes} bytes successfully.")

            if args.operation == "program" and not args.no_write_security:
                security_bytes = self.get_security_bytes(data, fconfig.secure_bytes_per_bank)
                if security_bytes:
                    self.logger.info(f"Programming security bits.")
                    if fconfig.banks:
                        for current_bank in range(fconfig.banks):
                            await iface.set_bank_num(current_bank)
                            await iface.set_security(fconfig, security_bytes[current_bank * fconfig.secure_bytes_per_bank: (current_bank + 1) * fconfig.secure_bytes_per_bank])
                    else:
                        await iface.set_security(fconfig, security_bytes)
                else:
                    self.logger.warn(f"No security information found in input file. Not programming security bits.")

            get_security_guaranteed_supported = fconfig.read_security_type >= 2
            if ((args.operation == "program" and not args.no_write_security and (args.verify_security or get_security_guaranteed_supported)) or
                (args.operation == "verify-checksum" and (args.verify_security or get_security_guaranteed_supported))):
                if not args.no_verify_security:
                    security_bytes = self.get_security_bytes(data, fconfig.secure_bytes_per_bank)
                    if security_bytes:
                        self.logger.info(f"Verifying security bits.")
                        block = await self._get_all_security(iface, fconfig)
                        if block == security_bytes[:len(block)]:
                            self.logger.info(f"Verified {len(block)} bytes of security data.")
                        else:
                            raise Psoc1Error(f"Verification of security data failed.")
                    else:
                        self.logger.warn(f"No security information found in input file. Not checking security bits.")

            if args.operation == "verify-checksum" or (args.operation in ("program", "verify-full") and not args.no_check_checksum):
                checksum_bytes = self.get_checksum_bytes(data)
                if checksum_bytes:
                    if fconfig.banks:
                        r_checksums = []
                        for current_bank in range(fconfig.banks):
                            await iface.set_bank_num(current_bank)
                            single_bank_checksum = await iface.get_checksum(fconfig)
                            r_checksums.append((single_bank_checksum[0] << 8) | single_bank_checksum[1])
                        r_checksum = sum(r_checksums)
                        r_checksum = [(r_checksum >> 8) & 0xff, r_checksum & 0xff]
                    else:
                        r_checksum = await iface.get_checksum(fconfig)
                    if r_checksum is None:
                        self.logger.warn("Unable to read checksum.")
                    else:
                        if r_checksum == checksum_bytes:
                            self.logger.info(f"Checksum verification successful, checksum is as expected: {checksum_bytes}!")
                        else:
                            raise Psoc1Error(f"Checksum error, expected: {checksum_bytes}, got: {r_checksum}")
                else:
                    self.logger.warn(f"No checksum bytes found in input file. Not checking checksum.")

            await iface.release_bus()




