# Ref: ATmega16U4/ATmega32U4 8-bit Microcontroller with 16/32K bytes of ISP Flash and USB Controller datasheet
# Accession: G00058

import math
import logging
from nmigen.compat import *

from ...interface.spi_master import SPIMasterSubtarget, SPIMasterInterface
from ... import *
from . import *


class ProgramAVRSPIInterface(ProgramAVRInterface):
    def __init__(self, interface, logger, addr_dut_reset):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._addr_dut_reset = addr_dut_reset

    def _log(self, message, *args):
        self._logger.log(self._level, "AVR SPI: " + message, *args)

    async def _command(self, byte1, byte2, byte3, byte4):
        command = [byte1, byte2, byte3, byte4]
        self._log("command %s", "{:08b} {:08b} {:08b} {:08b}".format(*command))
        result = await self.lower.transfer(command)
        self._log("result  %s", "{:08b} {:08b} {:08b} {:08b}".format(*result))
        return result

    async def programming_enable(self):
        self._log("programming enable")

        await self.lower.lower.device.write_register(self._addr_dut_reset, 1)
        await self.lower.delay_ms(20)

        _, _, echo, _ = await self._command(0b1010_1100, 0b0101_0011, 0, 0)
        if echo == 0b0101_0011:
            self._log("synchronization ok")
        else:
            raise ProgramAVRError("device not present or not synchronized")

    async def programming_disable(self):
        self._log("programming disable")
        await self.lower.synchronize()
        await self.lower.lower.device.write_register(self._addr_dut_reset, 0)
        await self.lower.delay_ms(20)

    async def _is_busy(self):
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

    async def read_program_memory(self, address):
        self._log("read program memory address %#06x", address)
        _, _, _, data = await self._command(
            0b0010_0000 | (address & 1) << 3,
            (address >> 9) & 0xff,
            (address >> 1) & 0xff,
            0)
        return data

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
        while await self._is_busy(): pass

    async def read_eeprom(self, address):
        self._log("read EEPROM address %#06x", address)
        _, _, _, data = await self._command(
            0b1010_0000,
            (address >> 8) & 0x1f,
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
            (address >> 0) & 0x3f,
            0)
        while await self._is_busy(): pass

    async def chip_erase(self):
        self._log("chip erase")
        await self._command(0b1010_1100, 0b1000_0000, 0, 0)
        while await self._is_busy(): pass


class ProgramAVRSPIApplet(ProgramAVRApplet, name="program-avr-spi"):
    logger = logging.getLogger(__name__)
    help = f"{ProgramAVRApplet.help} via SPI"
    description = """
    Identify, program, and verify Microchip AVR microcontrollers using low-voltage serial (SPI)
    programming.

    While programming is disabled, the programming interface is tristated, so the applet can be
    used for in-circuit programming even if the device uses SPI itself.

    The standard AVR ICSP connector layout is as follows:

    ::
        MISO @ * VCC
         SCK * * MOSI
        RST# * * GND
    """

    __pins = ("reset", "sck", "miso", "mosi")

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_argument(parser, "reset", default=True)
        access.add_pin_argument(parser, "sck",   default=True)
        access.add_pin_argument(parser, "miso",  default=True)
        access.add_pin_argument(parser, "mosi",  default=True)

        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=100,
            help="set SPI frequency to FREQ kHz (default: %(default)s)")

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        subtarget = iface.add_subtarget(SPIMasterSubtarget(
            pads=iface.get_pads(args, pins=self.__pins),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(auto_flush=False),
            period_cyc=math.ceil(target.sys_clk_freq / (args.frequency * 1000)),
            delay_cyc=math.ceil(target.sys_clk_freq / 1e6),
            sck_idle=0,
            sck_edge="rising",
            ss_active=0,
        ))

        dut_reset, self.__addr_dut_reset = target.registers.add_rw(1)
        target.comb += [
            subtarget.bus.oe.eq(dut_reset),
            iface.pads.reset_t.oe.eq(1),
            iface.pads.reset_t.o.eq(~dut_reset)
        ]

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        spi_iface = SPIMasterInterface(iface, self.logger)
        avr_iface = ProgramAVRSPIInterface(spi_iface, self.logger, self.__addr_dut_reset)
        return avr_iface

# -------------------------------------------------------------------------------------------------

class ProgramAVRSPIAppletTestCase(GlasgowAppletTestCase, applet=ProgramAVRSPIApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
