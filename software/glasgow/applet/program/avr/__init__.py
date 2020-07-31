"""
The Microchip (Atmel) AVR family has 9 (nine) incompatible programming interfaces. The vendor
provides no overview, compatibility matrix, or (for most interfaces) documentation other than
descriptions in MCU datasheets, so this document has to fill in the blanks.

The table below contains the summary of all necessary information to understand and implement these
programming interfaces (with the exception of debugWIRE). The wire counts include all wires between
the programmer and the target, including ~RESET, but excluding power, ground, and xtal (if any).

  * "Low-voltage serial"; 4-wire.
    Described in AVR910 application note and e.g. ATmega8 datasheet.
    This is what is commonly called SPI programming interface.
  * "Parallel"; 16-wire; requires +12 V on ~RESET.
    Described in e.g. ATmega8 datasheet.
  * JTAG; 4-wire.
    Described in e.g. ATmega323 datasheet.
  * "High-voltage serial"; 5-wire; requires 12 V on ~RESET.
    Described in e.g. ATtiny11 datasheet.
  * debugWIRE; 1-wire.
    Completely undocumented, partially reverse-engineered.
  * TPI ("tiny programming interface"); 3-wire.
    Described in AVR918 application note and e.g. ATtiny4 datasheet.
  * PDI ("program/debug interface"); 2-wire.
    Described in AVR1612 application note and e.g. ATxmega32D4 datasheet.
    PDI command set is a non-strict superset of TPI command set. PDICLK is unified with ~RESET.
  * UPDI ("unified program/debug interface"); 1-wire.
    Described in e.g. ATtiny417 datasheet.
    UPDI command set is a non-strict subset of PDI command set. PDICLK and PDIDATA are unified
    with ~RESET.
  * aWire; 1-wire; AVR32 only.
    Described in e.g. AT32UC3L064 datasheet.
"""

import logging
import argparse
from abc import ABCMeta, abstractmethod
from fx2.format import autodetect, input_data, output_data

from ... import *
from ....database.microchip.avr import *


__all__ = ["ProgramAVRError", "ProgramAVRInterface", "ProgramAVRApplet"]


class ProgramAVRError(GlasgowAppletError):
    pass


class ProgramAVRInterface(metaclass=ABCMeta):
    @abstractmethod
    async def programming_enable(self):
        raise NotImplementedError

    @abstractmethod
    async def programming_disable(self):
        raise NotImplementedError

    @abstractmethod
    async def read_signature(self):
        raise NotImplementedError

    @abstractmethod
    async def read_fuse(self, address):
        raise NotImplementedError

    async def read_fuse_range(self, addresses):
        return bytearray([await self.read_fuse(address) for address in addresses])

    @abstractmethod
    async def write_fuse(self, address, data):
        raise NotImplementedError

    @abstractmethod
    async def read_lock_bits(self):
        raise NotImplementedError

    @abstractmethod
    async def write_lock_bits(self, data):
        raise NotImplementedError

    @abstractmethod
    async def read_calibration(self, address):
        raise NotImplementedError

    async def read_calibration_range(self, addresses):
        return bytearray([await self.read_calibration(address) for address in addresses])

    @abstractmethod
    async def read_program_memory(self, address):
        raise NotImplementedError

    async def read_program_memory_range(self, addresses):
        return bytearray([await self.read_program_memory(address) for address in addresses])

    @abstractmethod
    async def load_program_memory_page(self, address, data):
        raise NotImplementedError

    @abstractmethod
    async def write_program_memory_page(self, address):
        raise NotImplementedError

    async def write_program_memory_range(self, address, chunk, page_size):
        dirty_page = False
        page_mask  = page_size - 1

        for offset, byte in enumerate(chunk):
            byte_address = address + offset
            if dirty_page and byte_address % page_size == 0:
                await self.write_program_memory_page((byte_address - 1) & ~page_mask)

            await self.load_program_memory_page(byte_address & page_mask, byte)
            dirty_page = True

        if dirty_page:
            await self.write_program_memory_page(byte_address & ~page_mask)

    @abstractmethod
    async def read_eeprom(self, address):
        raise NotImplementedError

    async def read_eeprom_range(self, addresses):
        return bytearray([await self.read_eeprom(address) for address in addresses])

    @abstractmethod
    async def load_eeprom_page(self, address, data):
        raise NotImplementedError

    @abstractmethod
    async def write_eeprom_page(self, address):
        raise NotImplementedError

    async def write_eeprom_range(self, address, chunk, page_size):
        dirty_page = False
        page_mask  = page_size - 1

        for offset, byte in enumerate(chunk):
            byte_address = address + offset
            if dirty_page and byte_address % page_size == 0:
                await self.write_eeprom_page((byte_address - 1) & ~page_mask)

            await self.load_eeprom_page(byte_address & page_mask, byte)
            dirty_page = True

        if dirty_page:
            await self.write_eeprom_page(byte_address & ~page_mask)

    @abstractmethod
    async def chip_erase(self):
        raise NotImplementedError


class ProgramAVRApplet(GlasgowApplet):
    logger = logging.getLogger(__name__)
    help = "program Microchip (Atmel) AVR microcontrollers"

    @classmethod
    def add_interact_arguments(cls, parser):
        def bits(arg): return int(arg, 2)

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION")

        p_identify = p_operation.add_parser(
            "identify", help="identify connected device")

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

        p_erase = p_operation.add_parser(
            "erase", help="erase device lock bits, program memory, and EEPROM")

    @staticmethod
    def _check_format(file, kind):
        try:
            autodetect(file)
        except ValueError:
            raise ProgramAVRError("cannot determine %s file format" % kind)

    async def interact(self, device, args, avr_iface):
        await avr_iface.programming_enable()

        signature = await avr_iface.read_signature()
        device = devices_by_signature[signature]
        self.logger.info("device signature: %s (%s)",
            "{:02x} {:02x} {:02x}".format(*signature),
            "unknown" if device is None else device.name)

        if args.operation not in (None, "identify") and device is None:
            raise ProgramAVRError("cannot operate on unknown device")

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
                raise ProgramAVRError("device does not have high fuse")

            if args.low:
                self.logger.info("writing low fuse")
                await avr_iface.write_fuse(0, args.low)
                written = await avr_iface.read_fuse(0)
                if written != args.low:
                    raise ProgramAVRError("verification of low fuse failed: %s" %
                                          "{:08b} != {:08b}".format(written, args.low))

            if args.high:
                self.logger.info("writing high fuse")
                await avr_iface.write_fuse(1, args.high)
                written = await avr_iface.read_fuse(1)
                if written != args.high:
                    raise ProgramAVRError("verification of high fuse failed: %s" %
                                          "{:08b} != {:08b}".format(written, args.high))

            if args.extra:
                self.logger.info("writing extra fuse")
                await avr_iface.write_fuse(2, args.extra)
                written = await avr_iface.read_fuse(2)
                if written != args.extra:
                    raise ProgramAVRError("verification of extra fuse failed: %s" %
                                          "{:08b} != {:08b}".format(written, args.extra))

        if args.operation == "write-lock":
            self.logger.info("writing lock bits")
            await avr_iface.write_lock_bits(args.bits)
            written = await avr_iface.read_lock_bits()
            if written != args.bits:
                raise ProgramAVRError("verification of lock bits failed: %s" %
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
                    raise ProgramAVRError("verification failed at address %#06x: %s != %s" %
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
                    raise ProgramAVRError("verification failed at address %#06x: %s != %s" %
                                          (address, written.hex(), chunk.hex()))

        if args.operation == "erase":
            self.logger.info("erasing device")
            await avr_iface.chip_erase()

        await avr_iface.programming_disable()
