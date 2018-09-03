import time
import struct
import logging
import asyncio
import argparse
import collections
from migen import *
from fx2.format import autodetect, input_data, output_data

from .. import *
from .master import SPIMasterSubtarget, SPIMasterInterface


AVRDevice = collections.namedtuple("AVRDevice",
    ("name", "signature",
     "calibration_size", "fuses_size",
     "program_size", "program_page",
     "eeprom_size",  "eeprom_page"))

devices = [
    AVRDevice("attiny13a", signature=[0x1e, 0x90, 0x07],
              calibration_size=2, fuses_size=2,
              program_size=1024, program_page=32,
              eeprom_size=64, eeprom_page=4),
    AVRDevice("attiny25", signature=[0x1e, 0x91, 0x08],
              calibration_size=2, fuses_size=3,
              program_size=1024, program_page=32,
              eeprom_size=128, eeprom_page=4),
    AVRDevice("attiny45", signature=[0x1e, 0x92, 0x06],
              calibration_size=2, fuses_size=3,
              program_size=2048, program_page=64,
              eeprom_size=256, eeprom_page=4),
    AVRDevice("attiny85", signature=[0x1e, 0x93, 0x0B],
              calibration_size=2, fuses_size=3,
              program_size=4096, program_page=64,
              eeprom_size=512, eeprom_page=4),
]


class SPIFlashAVRError(GlasgowAppletError):
    pass


class SPIFlashAVRInterface:
    def __init__(self, interface, logger, addr_dut_reset):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._addr_dut_reset = addr_dut_reset

    def _log(self, message, *args):
        self._logger.log(self._level, "AVR: " + message, *args)

    async def _command(self, byte1, byte2, byte3, byte4):
        command = [byte1, byte2, byte3, byte4]
        self._log("command %s", "{:08b} {:08b} {:08b} {:08b}".format(*command))
        result = await self.lower.transfer(command)
        self._log("result  %s", "{:08b} {:08b} {:08b} {:08b}".format(*result))
        return result

    async def programming_enable(self):
        self._log("programming enable")

        await self.lower.lower.device.write_register(self._addr_dut_reset, 1)
        time.sleep(0.020)

        _, _, echo, _ = await self._command(0b1010_1100, 0b0101_0011, 0, 0)
        if echo == 0b0101_0011:
            self._log("synchronization ok")
        else:
            raise SPIFlashAVRError("device not present or not synchronized")

    async def programming_disable(self):
        self._log("programming disable")
        await self.lower.lower.device.write_register(self._addr_dut_reset, 0)
        time.sleep(0.020)

    async def is_busy(self):
        self._log("poll ready/busy flag")
        _, _, _, busy = await self._command(0b1111_0000, 0b0000_0000, 0, 0)
        return bool(busy & 1)

    async def read_signature(self):
        self._log("read signature")
        signature = []
        for address in range(3):
            _, _, _, sig_byte = await self._command(0b0011_0000, 0b0000_0000, address & 0b11, 0)
            signature.append(sig_byte)
        return signature

    async def read_fuse(self, address):
        self._log("read fuse address %#04x", address)
        a1, a0 = {
            0: (0b0000, 0b0000),
            1: (0b1000, 0b1000),
            2: (0b0000, 0b1000),
        }[address]
        _, _, _, data = await self._command(
            0b0101_0000 | a0,
            0b0000_0000 | a1,
            0,  0)
        return data

    async def read_fuse_range(self, addresses):
        return bytearray([await self.read_fuse(address) for address in addresses])

    async def write_fuse(self, address, data):
        self._log("write fuse address %d data %02x", address, data)
        a = {
            0: 0b0000,
            1: 0b1000,
            2: 0b0100,
        }[address]
        await self._command(
            0b1010_1100,
            0b1010_0000 | a,
            0,
            data)
        while await self.is_busy(): pass

    async def read_lock_bits(self):
        self._log("read lock bits")
        _, _, _, data = await self._command(0b0101_1000, 0b0000_0000, 0,  0)
        return data

    async def write_lock_bits(self, data):
        self._log("write lock bits data %02x", data)
        await self._command(
            0b1010_1100,
            0b1110_0000,
            0,
            0b1100_0000 | data)
        while await self.is_busy(): pass

    async def read_calibration(self, address):
        self._log("read calibration address %#04x", address)
        _, _, _, data = await self._command(0b0011_1000, 0b0000_0000, address, 0)
        return data

    async def read_calibration_range(self, addresses):
        return bytearray([await self.read_calibration(address) for address in addresses])

    async def read_program_memory(self, address):
        self._log("read program memory address %#06x", address)
        _, _, _, data = await self._command(
            0b0010_0000 | (address & 1) << 3,
            (address >> 9) & 0xff,
            (address >> 1) & 0xff,
            0)
        return data

    async def read_program_memory_range(self, addresses):
        return bytearray([await self.read_program_memory(address) for address in addresses])

    async def load_program_memory_page(self, address, data):
        self._log("load program memory address %#06x data %02x", address, data)
        await self._command(
            0b0100_0000 | (address & 1) << 3,
            (address >> 9) & 0xff,
            (address >> 1) & 0xff,
            data)

    async def write_program_memory_page(self, address):
        self._log("write program memory page at %#06x", address)
        await self._command(
            0b0100_1100,
            (address >> 9) & 0xff,
            (address >> 1) & 0xff,
            0)

    async def write_program_memory_range(self, address, chunk, page_size):
        dirty_page = False
        page_mask  = page_size - 1

        for offset, byte in enumerate(chunk):
            byte_address = address + offset
            if dirty_page and byte_address % page_size == 0:
                await self.write_program_memory_page((byte_address - 1) & ~page_mask)
                while await self.is_busy(): pass

            await self.load_program_memory_page(byte_address & page_mask, byte)
            dirty_page = True

        if dirty_page:
            await self.write_program_memory_page(byte_address & ~page_mask)
            while await self.is_busy(): pass

    async def read_eeprom(self, address):
        self._log("read EEPROM address %#06x", address)
        _, _, _, data = await self._command(
            0b1010_0000,
            (address >> 8) & 0x1f,
            (address >> 0) & 0xff,
            0)
        return data

    async def read_eeprom_range(self, addresses):
        return bytearray([await self.read_eeprom(address) for address in addresses])

    async def load_eeprom_page(self, address, data):
        self._log("load EEPROM address %#06x data %02x", address, data)
        await self._command(
            0b1100_0001,
            (address >> 8) & 0xff,
            (address >> 0) & 0xff,
            data)

    async def write_eeprom_page(self, address):
        self._log("write EEPROM page at %#06x", address)
        await self._command(
            0b1100_0010,
            (address >> 8) & 0xff,
            (address >> 0) & 0x3f,
            0)

    async def write_eeprom_range(self, address, chunk, page_size):
        dirty_page = False
        page_mask  = page_size - 1

        for offset, byte in enumerate(chunk):
            byte_address = address + offset
            if dirty_page and byte_address % page_size == 0:
                await self.write_eeprom_page((byte_address - 1) & ~page_mask)
                while await self.is_busy(): pass

            await self.load_eeprom_page(byte_address & page_mask, byte)
            dirty_page = True

        if dirty_page:
            await self.write_eeprom_page(byte_address & ~page_mask)
            while await self.is_busy(): pass

    async def chip_erase(self):
        self._log("chip erase")
        await self._command(0b1010_1100, 0b1000_0000, 0, 0)
        while await self.is_busy(): pass


class SPIFlashAVRApplet(GlasgowApplet, name="spi-flash-avr"):
    logger = logging.getLogger(__name__)
    help = "flash Microchip AVR microcontrollers"
    description = """
    Identify, program, and verify Microchip AVR microcontrollers using serial (SPI) programming.

    While programming is disabled, the SPI bus is tristated, so the applet can be used for
    in-circuit programming.

    Supported devices: %s
    """.format(", ".join(map(lambda d: d.name, devices)))

    __pins = ("reset", "sck", "miso", "mosi")

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_argument(parser, "reset", default=True)
        access.add_pin_argument(parser, "sck",   default=True)
        access.add_pin_argument(parser, "miso",  default=True)
        access.add_pin_argument(parser, "mosi",  default=True)

        parser.add_argument(
            "-b", "--bit-rate", metavar="FREQ", type=int, default=100,
            help="set SPI bit rate to FREQ kHz (default: %(default)s)")

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        subtarget = ResetInserter()(SPIMasterSubtarget(
            pads=iface.get_pads(args, pins=self.__pins),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(streaming=False),
            bit_rate=args.bit_rate * 1000,
            sck_idle=0,
            sck_edge="rising",
            ss_active=0,
        ))
        target.submodules += subtarget

        reset, self.__addr_reset = target.registers.add_rw(1)
        target.comb += subtarget.reset.eq(reset)

        dut_reset, self.__addr_dut_reset = target.registers.add_rw(1)
        target.comb += [
            subtarget.bus.oe.eq(dut_reset),
            iface.pads.reset_t.oe.eq(1),
            iface.pads.reset_t.o.eq(~dut_reset)
        ]

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        spi_iface = SPIMasterInterface(iface, self.logger, self.__addr_reset)
        await spi_iface.reset()
        avr_iface = SPIFlashAVRInterface(spi_iface, self.logger, self.__addr_dut_reset)
        return avr_iface

    @classmethod
    def add_interact_arguments(cls, parser):
        def bits(arg): return int(arg, 2)

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION")

        p_read = p_operation.add_parser(
            "read", help="read device memories")
        p_read.add_argument(
            "-f", "--fuses", default=False, action="store_true",
            help="display fuse bytes")
        p_read.add_argument(
            "-l", "--lock-bits", default=False, action="store_true",
            help="display lock bits")
        p_read.add_argument(
            "-c", "--calibration", default=False, action="store_true",
            help="display calibration bytes")
        p_read.add_argument(
            "-p", "--program", metavar="FILE", type=argparse.FileType("wb"),
            help="write program memory contents to FILE")
        p_read.add_argument(
            "-e", "--eeprom", metavar="FILE", type=argparse.FileType("wb"),
            help="write EEPROM contents to FILE")

        p_write_fuses = p_operation.add_parser(
            "write-fuses", help="write and verify device fuses")
        p_write_fuses.add_argument(
            "-L", "--low", metavar="BITS", type=bits,
            help="set low fuse to binary BITS")
        p_write_fuses.add_argument(
            "-H", "--high", metavar="BITS", type=bits,
            help="set high fuse to binary BITS")
        p_write_fuses.add_argument(
            "-E", "--extra", metavar="BITS", type=bits,
            help="set extra fuse to binary BITS")

        p_write_lock = p_operation.add_parser(
            "write-lock", help="write and verify device lock bits")
        p_write_lock.add_argument(
            "bits", metavar="BITS", type=bits,
            help="write lock bits BITS")

        p_write_program = p_operation.add_parser(
            "write-program", help="write and verify device program memory")
        p_write_program.add_argument(
            "file", metavar="FILE", type=argparse.FileType("rb"),
            help="read program memory contents from FILE")

        p_write_eeprom = p_operation.add_parser(
            "write-eeprom", help="write and verify device EEPROM")
        p_write_eeprom.add_argument(
            "file", metavar="FILE", type=argparse.FileType("rb"),
            help="read EEPROM contents from FILE")

    @staticmethod
    def _check_format(file, kind):
        try:
            autodetect(file)
        except ValueError:
            raise GlasgowAppletError("cannot determine %s file format" % kind)

    async def interact(self, device, args, avr_iface):
        await avr_iface.programming_enable()

        signature = await avr_iface.read_signature()
        for device in devices:
            if device.signature == signature:
                break
        else:
            device = None
        self.logger.info("device signature: %s (%s)",
            "{:02x} {:02x} {:02x}".format(*signature),
            "unknown" if device is None else device.name)

        if args.operation is not None and device is None:
            raise GlasgowAppletError("cannot operate on unknown device")

        if args.operation == "read":
            if args.fuses:
                fuses = await avr_iface.read_fuse_range(range(device.fuses_size))
                if device.fuses_size > 2:
                    self.logger.info("fuses: low %s high %s extra %s",
                                     "{:08b}".format(fuses[0]),
                                     "{:08b}".format(fuses[1]),
                                     "{:08b}".format(fuses[2]))
                elif device.fuses_size > 1:
                    self.logger.info("fuses: low %s high %s",
                                     "{:08b}".format(fuses[0]),
                                     "{:08b}".format(fuses[1]))
                else:
                    self.logger.info("fuse: %s", "{:08b}".format(fuses[0]))

            if args.lock_bits:
                lock_bits = await avr_iface.read_lock_bits()
                self.logger.info("lock bits: %s", "{:08b}".format(lock_bits))

            if args.calibration:
                calibration = \
                    await avr_iface.read_calibration_range(range(device.calibration_size))
                self.logger.info("calibration bytes: %s",
                                 " ".join(["%02x" % b for b in calibration]))

            if args.program:
                self._check_format(args.program, "program memory")
                self.logger.info("reading program memory (%d bytes)", device.program_size)
                output_data(args.program,
                    await avr_iface.read_program_memory_range(range(device.program_size)))

            if args.eeprom:
                self._check_format(args.eeprom, "EEPROM")
                self.logger.info("reading EEPROM (%d bytes)", device.eeprom_size)
                output_data(args.eeprom,
                    await avr_iface.read_eeprom_range(range(device.eeprom_size)))

        if args.operation == "write-fuses":
            if args.high and device.fuses_size < 2:
                raise GlasgowAppletError("device does not have high fuse")

            if args.low:
                self.logger.info("writing low fuse")
                await avr_iface.write_fuse(0, args.low)
                written = await avr_iface.read_fuse(0)
                if written != args.low:
                    raise GlasgowAppletError("verification of low fuse failed: %s" %
                                             "{:08b} != {:08b}".format(written, args.low))

            if args.high:
                self.logger.info("writing high fuse")
                await avr_iface.write_fuse(1, args.high)
                written = await avr_iface.read_fuse(1)
                if written != args.high:
                    raise GlasgowAppletError("verification of high fuse failed: %s" %
                                             "{:08b} != {:08b}".format(written, args.high))

        if args.operation == "write-lock":
            self.logger.info("writing lock bits")
            await avr_iface.write_lock_bits(args.bits)
            written = await avr_iface.read_lock_bits()
            if written != args.bits:
                raise GlasgowAppletError("verification of lock bits failed: %s" %
                                         "{:08b} != {:08b}".format(written, args.bits))

        if args.operation == "write-program":
            self.logger.info("erasing chip")
            await avr_iface.chip_erase()

            self._check_format(args.file, "program memory")
            data = input_data(args.file)
            self.logger.info("writing program memory (%d bytes)",
                             sum([len(chunk) for address, chunk in data]))
            for address, chunk in data:
                chunk = bytes(chunk)
                await avr_iface.write_program_memory_range(address, chunk, device.program_page)
                written = await avr_iface.read_program_memory_range(range(address, len(chunk)))
                if written != chunk:
                    raise GlasgowAppletError("verification failed at address %#06x: %s != %s" %
                                             (address, written.hex(), chunk.hex()))

        if args.operation == "write-eeprom":
            self._check_format(args.file, "EEPROM")
            data = input_data(args.file)
            self.logger.info("writing EEPROM (%d bytes)",
                             sum([len(chunk) for address, chunk in data]))
            for address, chunk in data:
                chunk = bytes(chunk)
                await avr_iface.write_eeprom_range(address, chunk, device.eeprom_page)
                written = await avr_iface.read_eeprom_range(range(address, len(chunk)))
                if written != chunk:
                    raise GlasgowAppletError("verification failed at address %#06x: %s != %s" %
                                             (address, written.hex(), chunk.hex()))

        await avr_iface.programming_disable()

# -------------------------------------------------------------------------------------------------

class SPIFlashAVRAppleTestCase(GlasgowAppletTestCase, applet=SPIFlashAVRApplet):
    def test_build(self):
        self.assertBuilds()
