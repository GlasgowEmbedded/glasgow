# Chipcon, (now Texas Instruments)  CC111x CC251x
#
import logging
import argparse
import asyncio
import math

from fx2.format import autodetect, input_data, output_data, flatten_data
from ... import *
from .ccdpi import *

class ProgramChipconApplet(GlasgowApplet, name="program-chipcon"):
    logger = logging.getLogger(__name__)
    help = "program TI/Chipcon CC111x CC251x "
    description = """
    Program and read back TI/Chipcon CC111x, CC251x and CC243x parts.
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

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)

        iface.add_subtarget(CCDPISubtarget(
            pads=iface.get_pads(args, pins=self.__pins),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(auto_flush=False),
            period=math.ceil(target.sys_clk_freq / (args.frequency * 1000))
        ))

        # Connect up RESETN
        reset, self._addr_reset = target.registers.add_rw(1)
        target.comb += [
            iface.pads.resetn_t.oe.eq(1),
            iface.pads.resetn_t.o.eq(~reset)
        ]

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        chipcon_iface = CCDPIInterface(iface, self.logger, self._addr_reset)
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
            "--lock-bits", metavar="LOCK-BITS", type=argparse.FileType("rb"),
            help="program flash information page from LOCK-BITS")
        p_write.add_argument(
            "--no-erase", action="store_true",
            help="do not erase chip before writing")
        p_write.add_argument(
            "--offset", metavar="OFFSET", type=address, default=0,
            help="adjust memory addresses by OFFSET")

    @staticmethod
    def _check_format(file, kind):
        try:
            autodetect(file)
        except ValueError:
            raise CCDPIError("cannot determine %s file format" % kind)

    async def interact(self, device, args, chipcon_iface):

        await chipcon_iface.connect()
        await chipcon_iface.clock_init()

        self.logger.info("connected to {} Rev:{}".format(
            chipcon_iface.device.name,
            chipcon_iface.chip_rev))
        self.logger.info(args.operation)

        if args.operation == "identify":
            self.logger.info("Id:{:X} [{}] Rev:{:d}".format(
                chipcon_iface.chip_id,
                chipcon_iface.device.name,
                chipcon_iface.chip_rev))

        elif args.operation == "erase":
            await chipcon_iface.chip_erase()

        elif args.operation == "erase-page":
            await chipcon_iface.erase_flash_page(args,address)

        elif args.operation == "read":
            if args.code:
                self._check_format(args.code, "code")
                self.logger.info("reading code (%d bytes)", args.length)
                await chipcon_iface.set_config(0)
                output_data(args.code,
                            await chipcon_iface.read_code(args.address, args.length))

            if args.lock_bits:
                self._check_format(args.lock_bits, "lock-bits")
                self.logger.info("reading flash information (%d bytes)", args.length)
                await chipcon_iface.set_config(Config.SEL_FLASH_INFO_PAGE)
                output_data(args.lock_bits,
                            await chipcon_iface.read_code(args.address, args.length))
                await chipcon_iface.set_config(0)

        elif args.operation == "write":
            if not args.no_erase:
                self.logger.info("erasing chip")
                await chipcon_iface.chip_erase()

            if args.code:
                self._check_format(args.code, "code")
                data = input_data(args.code)
                self.logger.info("writing code (%d bytes)",
                                 sum([len(chunk) for address, chunk in data]))
                await chipcon_iface.set_config(0)
                await self._write_flash_blocks(chipcon_iface, data,
                                               chipcon_iface.device.write_block_size)

            if args.lock_bits:
                self._check_format(args.lock_bits, "lock-bits")
                data = input_data(args.lock_bits)
                self.logger.info("writing flash information (%d bytes)",
                                 sum([len(chunk) for address, chunk in data]))

                await chipcon_iface.set_config(Config.SEL_FLASH_INFO_PAGE)
                await self._write_flash_blocks(chipcon_iface, data,
                                               chipcon_iface.device.write_block_size)
                await chipcon_iface.set_config(0)

        await chipcon_iface.disconnect()

    async def _write_flash_blocks(self, chipcon_iface, data, block_size):
        """Write data to flash, breaking into blocks of given size."""

        for address, chunk in data:
            for o in range(0, len(chunk), block_size):
                block = bytes(chunk[o:o+block_size])
                await chipcon_iface.write_flash(address+o, block)
                readback = await chipcon_iface.read_code(address+o, len(block))

                if block != readback:
                    raise CCDPIError("verification failed at address %#06x: %s != %s" %
                                     (address, readback.hex(), chunk.hex()))


# -------------------------------------------------------------------------------------------------

class ProgramChipconAppletTestCase(GlasgowAppletTestCase, applet=ProgramChipconApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
