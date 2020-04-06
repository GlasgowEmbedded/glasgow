# Chipcon, (now Texas Instruments) CC111x CC251x CC243x CC253x CC254x
#
import logging
import argparse
import asyncio
import math

from fx2.format import autodetect, input_data, flatten_data, output_data
from ....gateware.clockgen import *
from ... import *
from .ccdpi import *

class ProgramChipconApplet(GlasgowApplet, name="program-chipcon"):
    logger = logging.getLogger(__name__)
    help = "program TI/Chipcon CC111x CC251x CC243x CC253x CC254x"
    description = """
    Program and read back TI/Chipcon 8051 based SoC radios.
    CC111x, CC251x, CC243x, CC253x and CC254x.
    """
    __pins = ( "dclk", "ddat", "resetn")

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)
        for pin in cls.__pins:
            access.add_pin_argument(parser, pin, default=True)
        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=1000,
            help="set bit rate to FREQ kHz (default: %(default)s)")
        parser.add_argument(
            "-s", "--flash-size", metavar="FLASH-SIZE", type=int,
            help="set flash size FLASH-SIZE Kbytes")

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        iface.add_subtarget(CCDPISubtarget(
            pads=iface.get_pads(args, pins=self.__pins),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(auto_flush=False),
            period_cyc=math.ceil(target.sys_clk_freq / (args.frequency * 1000)),
            delay_cyc=self.derive_clock(input_hz=target.sys_clk_freq,
                                        output_hz=4e6,
                                        clock_name="delay")
        ))

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        chipcon_iface = CCDPIInterface(iface, self.logger, args.flash_size)
        return chipcon_iface

    @classmethod
    def add_interact_arguments(cls, parser):
        def address(arg):
            return int(arg, 0)
        def length(arg):
            return int(arg, 0)
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION")
        p_identify = p_operation.add_parser(
            "identify", help="read identity and revision from connected device")
        p_erase = p_operation.add_parser(
            "erase", help="erase whole device.")
        p_erase_page = p_operation.add_parser(
            "erase-page", help="erase whole device.")
        p_erase_page.add_argument(
            "address", metavar="ADDRESS", type=address,
            help="erase memory from address ADDRESS")
        p_read = p_operation.add_parser(
            "read", help="read memory")
        p_read.add_argument(
            "address", metavar="ADDRESS", type=address,
            help="read memory from address ADDRESS")
        p_read.add_argument(
            "length", metavar="LENGTH", type=length,
            help="read LENGTH bytes from memory")
        p_read.add_argument(
            "--code", metavar="CODE", type=argparse.FileType("wb"),
            help="read memory contents into CODE")
        p_read.add_argument(
            "--lock-bits", metavar="LOCK-BITS", type=argparse.FileType("wb"),
            help="read flash information page into LOCK-BITS")
        p_write = p_operation.add_parser(
            "write", help="write and verify memory")
        p_write.add_argument(
            "--code", metavar="CODE", type=argparse.FileType("rb"),
            help="program code memory contents from CODE")
        p_write.add_argument(
            "--lock-size", metavar="LOCK-SIZE", type=int, default=0,
            help="Set flash lock size - size in KBytes of upper flash memory which is write protected.")
        p_write.add_argument(
            "--lock-debug",  action="store_true",
            help="Set debug lock bit - disable all operations except id, status and erase.")
        p_write.add_argument(
            "--lock-boot", action="store_true",
            help="Set boot page lock bit, disable writing to page 0")
        p_write.add_argument(
            "--lock-bits", metavar="LOCK-BITS", type=argparse.FileType("rb"),
            help="program flash information page from LOCK-BITS")
        p_write.add_argument(
            "--no-erase", action="store_true",
            help="do not erase chip before writing")
        p_write.add_argument(
            "--no-verify", action="store_true",
            help="do not verify code after writing")

    @staticmethod
    def _check_format(file, kind):
        try:
            autodetect(file)
        except ValueError:
            raise CCDPIError("cannot determine %s file format" % kind)

    async def interact(self, device, args, chipcon_iface):
        await chipcon_iface.connect()
        debug_locked = await chipcon_iface.get_status() & Status.DEBUG_LOCKED
        if not debug_locked:
            await chipcon_iface.clock_init()
        self.logger.info("connected to {} Rev:{}{}".format(
            chipcon_iface.device.name,
            chipcon_iface.chip_rev,
            " Debug Locked" if debug_locked else ""))
        if debug_locked and args.operation not in ("identify, erase"):
            raise CCDPIError("Cannot %s when debug is locked" % args.operation)
        self.logger.info(args.operation)
        if args.operation == "identify":
            self.logger.info("Id:{:X} [{}] Rev:{:d}".format(
                chipcon_iface.chip_id,
                chipcon_iface.device.name,
                chipcon_iface.chip_rev))
        elif args.operation == "erase":
            await chipcon_iface.chip_erase()
        elif args.operation == "erase-page":
            await chipcon_iface.erase_flash_page(args.address)
        elif args.operation == "read":
            if args.code:
                self._check_format(args.code, "code")
                self.logger.info("reading code (%d bytes)", args.length)
                await chipcon_iface.set_config(0)
                output_data(args.code,
                            await self.read_flash(chipcon_iface, args.address, args.length))
            if args.lock_bits:
                self._check_format(args.lock_bits, "lock-bits")
                self.logger.info("reading flash information (%d bytes)", args.length)
                await chipcon_iface.set_config(Config.SEL_FLASH_INFO_PAGE)
                output_data(args.lock_bits,
                            await self.read_flash(args.address, args.length))
                await chipcon_iface.set_config(0)
        elif args.operation == "write":
            if not args.no_erase:
                self.logger.info("erasing chip")
                await chipcon_iface.chip_erase()
                await chipcon_iface.connect()
            if args.code:
                self._check_format(args.code, "code")
                data = input_data(args.code)
                self.logger.info("writing code (%d bytes)",
                                 sum([len(chunk) for address, chunk in data]))
                await chipcon_iface.set_config(0)
                await self.write_flash(chipcon_iface, data,
                                       chipcon_iface.device.write_block_size,
                                       not args.no_verify)
            if args.lock_bits or args.lock_boot or args.lock_size or args.lock_debug:
                data = []
                if args.lock_bits:
                    self._check_format(args.lock_bits, "lock-bits")
                    data += input_data(args.lock_bits)
                if args.lock_boot or args.lock_size or args.lock_debug:
                    data += self._make_lock_bits(chipcon_iface,
                                                 args.lock_boot, args.lock_size, args.lock_debug)
                self.logger.info("writing flash information (%d bytes)",
                                 sum([len(chunk) for address, chunk in data]))
                await chipcon_iface.set_config(Config.SEL_FLASH_INFO_PAGE)
                # Cannot verify if debug is locked
                await self.write_flash(chipcon_iface, data,
                                      chipcon_iface.device.write_block_size, not args.lock_debug)
                await chipcon_iface.set_config(0)
        await chipcon_iface.disconnect()

    async def read_flash(self, chipcon_iface, address, count):
        """Read data from flash."""
        bytes = bytearray()
        for block_address,block_count in self._aligned_range(address, count, 0x8000):
            bytes += await chipcon_iface.read_flash(block_address, block_count)
            self.logger.info("read %d bytes from %#07x", block_count, block_address)
        return bytes

    async def write_flash(self, chipcon_iface, data, block_size, verify=True):
        """Write data (and optionally verify) flash."""
        if len(data) == 0:
            return
        elif len(data) == 1:
            address,chunk = data[0]
        elif len(data) > 1:
            address,chunk = self._combine_chunks(data)
        for block_address,block_size in self._aligned_range(address, len(chunk),
                                                            chipcon_iface.device.write_block_size):
            block_offset = block_address-address
            block = bytes(chunk[block_offset:block_offset+block_size])

            await chipcon_iface.write_flash(block_address, block)
            readback = await chipcon_iface.read_flash(block_address, len(block))
            if verify and block != readback:
                raise CCDPIError("verification failed at address %#07x" % (block_address,))
            self.logger.info("written %d bytes to %#07x", len(block), address+block_offset)

    def _combine_chunks(self, data):
        """Reduce a list of (adress,chunk) to a single entry combining all chunks.
        Any gaps are filled with 0xff.
        """
        start = min([addr for (addr, _) in data])
        end = max([addr + len(chunk) for (addr, chunk) in data])
        combined_data = bytearray([0xff] * (end - start))
        for (addr, chunk) in data:
            addr -= start
            combined_data[addr:addr+len(chunk)] = chunk
        return (start, combined_data)

    def _aligned_range(self, addr, length, align):
        """Generate addr,length pairs that splits range addr,length on align boundaries."""
        limit = addr+length
        while addr < limit:
            next_boundary = (addr//align+1) * align
            count = min(limit-addr, next_boundary-addr)
            yield (addr, count)
            addr += count

    def _make_lock_bits(self, chipcon_iface, boot, size, debug):
        """Construct data to write to flash information page encoding the given lock settings."""
        if size not in chipcon_iface.device.write_protect_sizes:
            raise CCDPIError("lock size %d is not valid for device - valid sizes are %s" %
                             (size, ",".join(str(s) for s in chipcon_iface.device.write_protect_sizes)))
        lock_byte = chipcon_iface.device.write_protect_sizes[size] << 1
        if not boot:
            lock_byte |= 0x10
        if not debug:
            lock_byte |= 0x01
        self.logger.debug("Lock byte: %#02x", lock_byte)
        # Contrary to the data sheet, the lock byte appears to be byte 1 in information page.
        return [(0,bytes([0xff, lock_byte]))]

# -------------------------------------------------------------------------------------------------
class ProgramChipconAppletTestCase(GlasgowAppletTestCase, applet=ProgramChipconApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
