# Ref: ATmega16U4/ATmega32U4 8-bit Microcontroller with 16/32K bytes of ISP Flash and
#      USB Controller datasheet
# Accession: G00058

import logging
from amaranth import *

from glasgow.abstract import AbstractAssembly, GlasgowPin, ClockDivisor
from glasgow.applet.program.avr import ProgramAVRError, ProgramAVRApplet, ProgramAVRInterface
from glasgow.applet.interface.spi_controller import SPIControllerInterface
from glasgow.applet.control.gpio import GPIOInterface


__all__ = ["ProgramAVRSPIInterface"]


class ProgramAVRSPIInterface(ProgramAVRInterface):
    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
                 sck: GlasgowPin, copi: GlasgowPin, cipo: GlasgowPin, reset: GlasgowPin):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        self._spi_iface = SPIControllerInterface(logger, assembly,
            sck=sck, copi=copi, cipo=cipo, mode=0)
        self._reset_iface = GPIOInterface(logger, assembly, pins=(~reset,), name="reset")

        self._extended_addr  = None

    def _log(self, message, *args):
        self._logger.log(self._level, "AVR SPI: " + message, *args)

    @property
    def clock(self) -> ClockDivisor:
        """SCK clock divisor."""
        return self._spi_iface.clock

    async def _command(self, byte1, byte2, byte3, byte4):
        command = [byte1, byte2, byte3, byte4]
        self._log("command %s", "{:08b} {:08b} {:08b} {:08b}".format(*command))
        async with self._spi_iface.select():
            result = await self._spi_iface.exchange(command)
        self._log("result  %s", "{:08b} {:08b} {:08b} {:08b}".format(*result))
        return result

    async def programming_enable(self):
        self._log("programming enable")

        # Apply power between VCC and GND while RESET and SCK are set to “0”. In some systems,
        # the programmer can not guarantee that SCK is held low during power-up. In this case,
        # RESET must be given  a positive pulse of at least two CPU clock cycles duration after
        # SCK has been set to “0”. [We have the second case.]
        async with self._spi_iface.select():
            # Set SCK low (transmit at least one byte in SPI Mode 0).
            await self._spi_iface.write(0x00)
            # Momentarily deassert RESET#.
            await self._spi_iface.synchronize()
            await self._reset_iface.output(0, False)
            await self._spi_iface.delay_ms(1)
            await self._spi_iface.synchronize()
            await self._reset_iface.output(0, True)
            await self._spi_iface.synchronize()

        # Wait for at least 20ms and enable serial programming by sending the Programming Enable
        # serial instruction to pin PDI.
        await self._spi_iface.delay_ms(20)
        _, _, echo, _ = await self._command(0b1010_1100, 0b0101_0011, 0, 0)
        if echo == 0b0101_0011:
            self._log("synchronization ok")
        else:
            raise ProgramAVRError("device not present or not synchronized")

    async def programming_disable(self):
        self._log("programming disable")
        await self._spi_iface.synchronize()
        await self._reset_iface.output(0, False)
        await self._spi_iface.delay_ms(20)

    async def _is_busy(self):
        if self.erase_time is not None:
            self._log("wait for completion")
            await self._spi_iface.delay_ms(self.erase_time)
            return False
        else:
            self._log("poll ready/busy flag")
            _, _, _, busy = await self._command(0b1111_0000, 0b0000_0000, 0, 0)
            return bool(busy & 1)

    async def read_signature(self):
        self._log("read signature")
        signature = []
        for address in range(3):
            _, _, _, sig_byte = await self._command(0b0011_0000, 0b0000_0000, address & 0b11, 0)
            signature.append(sig_byte)
        return tuple(signature)

    async def read_fuse(self, address):
        self._log("read fuse address %#04x", address)
        a0, a1 = {
            0: (0b0000, 0b0000),
            1: (0b1000, 0b1000),
            2: (0b0000, 0b1000),
        }[address]
        _, _, _, data = await self._command(
            0b0101_0000 | a0,
            0b0000_0000 | a1,
            0,  0)
        return data

    async def write_fuse(self, address, data):
        self._log("write fuse address %#04x data %02x", address, data)
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
        while await self._is_busy(): pass

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
        while await self._is_busy(): pass

    async def read_calibration(self, address):
        self._log("read calibration address %#04x", address)
        _, _, _, data = await self._command(0b0011_1000, 0b0000_0000, address, 0)
        return data

    async def load_extended_address_byte(self, address):
        extended_addr = (address >> 17) & 0xff
        if self._extended_addr != extended_addr:
            self._log("load extended address %#02x", extended_addr)
            await self._command(0b0100_1101, 0, extended_addr, 0)
            self._extended_addr = extended_addr

    async def read_program_memory(self, address):
        await self.load_extended_address_byte(address)
        self._log("read program memory address %#06x", address)
        _, _, _, data = await self._command(
            0b0010_0000 | (address & 1) << 3,
            (address >> 9) & 0xff,
            (address >> 1) & 0xff,
            0)
        return data

    async def load_program_memory_page(self, address, data):
        self._log("load program memory address %#06x data %02x", address, data)
        async with self._spi_iface.select():
            await self._spi_iface.write([
                0b0100_0000 | (address & 1) << 3,
                (address >> 9) & 0xff,
                (address >> 1) & 0xff,
                data
            ])

    async def write_program_memory_page(self, address):
        await self.load_extended_address_byte(address)
        self._log("write program memory page at %#06x", address)
        await self._command(
            0b0100_1100,
            (address >> 9) & 0xff,
            (address >> 1) & 0xff,
            0)
        while await self._is_busy(): pass

    async def read_eeprom(self, address):
        self._log("read EEPROM address %#06x", address)
        _, _, _, data = await self._command(
            0b1010_0000,
            (address >> 8) & 0xff,
            (address >> 0) & 0xff,
            0)
        return data

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
            (address >> 0) & 0xff,
            0)
        while await self._is_busy(): pass

    async def chip_erase(self):
        self._log("chip erase")
        await self._command(0b1010_1100, 0b1000_0000, 0, 0)
        while await self._is_busy(): pass


class ProgramAVRSPIApplet(ProgramAVRApplet):
    logger = logging.getLogger(__name__)
    help = f"{ProgramAVRApplet.help} via SPI"
    description = f"""
    Identify, program, and verify Microchip AVR microcontrollers using low-voltage serial (SPI)
    programming.

    While programming is disabled, the programming interface is tristated, so the applet can be
    used for in-circuit programming even if the device uses SPI itself.

    The standard AVR ICSP connector layout is as follows:

    ::

        CIPO @ * VCC
         SCK * * COPI
        RST# * * GND

    {ProgramAVRApplet.description}
    """
    required_revision = "C0"
    avr_iface: ProgramAVRSPIInterface

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "reset", required=True, default=True)
        access.add_pins_argument(parser, "sck",   required=True, default=True)
        access.add_pins_argument(parser, "cipo",  required=True, default=True)
        access.add_pins_argument(parser, "copi",  required=True, default=True)

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.avr_iface = ProgramAVRSPIInterface(self.logger, self.assembly,
                reset=args.reset, sck=args.sck, cipo=args.cipo, copi=args.copi)

    @classmethod
    def add_setup_arguments(cls, parser):
        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=100,
            help="set SCK frequency to FREQ kHz (default: %(default)s)")

    async def setup(self, args):
        await self.avr_iface.clock.set_frequency(args.frequency * 1000)

    @classmethod
    def tests(cls):
        from . import test
        return test.ProgramAVRSPIAppletTestCase
