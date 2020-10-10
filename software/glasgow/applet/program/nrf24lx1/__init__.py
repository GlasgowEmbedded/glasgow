# Reference: https://infocenter.nordicsemi.com/pdf/nRF24LE1_PS_v1.6.pdf
# Accession: G00035

import os
import math
import asyncio
import logging
import argparse
import struct
from collections import namedtuple
from nmigen.compat import *
from fx2.format import input_data, output_data

from ....support.logging import dump_hex
from ...interface.spi_controller import SPIControllerSubtarget, SPIControllerInterface
from ... import *


class ProgramNRF24Lx1Error(GlasgowAppletError):
    pass


_MemoryArea = namedtuple("_MemoryArea", ("name", "mem_addr", "spi_addr", "size"))


_nrf24le1_map = [
    _MemoryArea(name="code",    mem_addr= 0x0000, spi_addr= 0x0000, size=0x4000),
    _MemoryArea(name="NV data", mem_addr= 0xFC00, spi_addr= 0x4400, size=0x0400),
    _MemoryArea(name="info",    mem_addr=0x10000, spi_addr=0x10000, size=0x0200),
]

_nrf24lu1p_32k_map = [
    _MemoryArea(name="code",    mem_addr= 0x0000, spi_addr= 0x0000, size=0x7C00),
    _MemoryArea(name="NV data", mem_addr= 0x7C00, spi_addr= 0x7C00, size=0x0400),
    _MemoryArea(name="info",    mem_addr=0x10000, spi_addr=0x10000, size=0x0200),
]

_nrf24lu1p_16k_map = [
    _MemoryArea(name="code",    mem_addr= 0x0000, spi_addr= 0x0000, size=0x3C00),
    _MemoryArea(name="NV data", mem_addr= 0x7C00, spi_addr= 0x7C00, size=0x0400),
    _MemoryArea(name="info",    mem_addr=0x10000, spi_addr=0x10000, size=0x0200),
]


FSR_BIT_ENDEBUG = 0b10000000
FSR_BIT_STP     = 0b01000000
FSR_BIT_WEN     = 0b00100000
FSR_BIT_RDYN    = 0b00010000
FSR_BIT_INFEN   = 0b00001000
FSR_BIT_RDISMB  = 0b00000100


class ProgramNRF24Lx1Interface:
    def __init__(self, interface, logger, device, addr_dut_prog, addr_dut_reset):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._device = device
        self._addr_dut_prog  = addr_dut_prog
        self._addr_dut_reset = addr_dut_reset

    def _log(self, message, *args):
        self._logger.log(self._level, "nRF24Lx1: " + message, *args)

    async def _reset(self):
        await self._device.write_register(self._addr_dut_reset, 1)
        await asyncio.sleep(0.001) # 0.1 us
        await self._device.write_register(self._addr_dut_reset, 0)

    async def reset_program(self):
        self._log("reset mode=program")
        await self.lower.synchronize()
        await self._device.write_register(self._addr_dut_prog, 1)
        await self._reset()
        await self.lower.synchronize()
        await self.lower.delay_us(1500)

    async def reset_application(self):
        self._log("reset mode=application")
        await self.lower.synchronize()
        await self._device.write_register(self._addr_dut_prog, 0)
        await self._reset()

    async def _command(self, cmd, arg=[], ret=0):
        self._log("cmd=%02X arg=<%s> ret=%d", cmd, dump_hex(arg), ret)
        await self.lower.write(bytearray([cmd, *arg]),
                               hold_ss=(ret > 0))
        if ret > 0:
            result = await self.lower.read(ret)
            self._log("res=<%s>", dump_hex(result))
            return result

    async def read_status(self):
        status, = await self._command(0x05, ret=1)
        self._log("read status=%s", "{:#010b}".format(status))
        return status

    async def write_status(self, status):
        self._log("write status=%s", "{:#010b}".format(status))
        await self._command(0x01, arg=[status])

    async def wait_status(self):
        self._log("wait status")
        while await self.read_status() & FSR_BIT_WEN: pass

    async def write_enable(self):
        self._log("write enable")
        await self._command(0x06)

    async def write_disable(self):
        self._log("write disable")
        await self._command(0x04)

    async def read(self, address, length):
        self._log("read address=%#06x length=%#06x", address, length)
        return await self._command(0x03, arg=struct.pack(">H", address), ret=length)

    async def program(self, address, data):
        self._log("program address=%#06x length=%#06x", address, len(data))
        await self._command(0x02, arg=struct.pack(">H", address) + bytes(data))

    async def erase_page(self, page):
        self._log("erase page=%#04x", page)
        await self._command(0x52, arg=[page])

    async def erase_all(self):
        self._log("erase all")
        await self._command(0x62)

    async def read_unprotected_pages(self):
        pages, = await self._command(0x89, ret=1)
        self._log("read unprotected pages=%#04x", pages)
        return pages

    async def disable_read(self):
        self._log("disable read")
        await self._command(0x85)

    async def enable_debug(self):
        self._log("enable debug")
        await self._command(0x86)


class ProgramNRF24Lx1Applet(GlasgowApplet, name="program-nrf24lx1"):
    logger = logging.getLogger(__name__)
    help = "program nRF24LE1 and nRF24LU1+ RF microcontrollers"
    description = """
    Program the non-volatile memory of nRF24LE1 and nRF24LU1+ microcontrollers.
    """

    __pins = ("prog", "sck", "copi", "cipo", "cs", "reset")

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_build_arguments(parser)

        # Order matches the pin order, in clockwise direction.
        access.add_pin_argument(parser, "prog",  default=True)
        access.add_pin_argument(parser, "sck",   default=True)
        access.add_pin_argument(parser, "copi",  default=True)
        access.add_pin_argument(parser, "cipo",  default=True)
        access.add_pin_argument(parser, "cs",    default=True)
        access.add_pin_argument(parser, "reset", default=True)

        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=1000,
            help="set SPI frequency to FREQ kHz (default: %(default)s)")

    def build(self, target, args):
        dut_prog,  self.__addr_dut_prog  = target.registers.add_rw(1)
        dut_reset, self.__addr_dut_reset = target.registers.add_rw(1)

        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        pads = iface.get_pads(args, pins=self.__pins)

        subtarget = iface.add_subtarget(SPIControllerSubtarget(
            pads=pads,
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(auto_flush=True),
            period_cyc=math.ceil(target.sys_clk_freq / (args.frequency * 1000)),
            delay_cyc=math.ceil(target.sys_clk_freq / 1e6),
            sck_idle=0,
            sck_edge="rising",
            cs_active=0,
        ))
        subtarget.comb += [
            pads.prog_t.o.eq(dut_prog),
            pads.prog_t.oe.eq(1),
            pads.reset_t.o.eq(~dut_reset),
            pads.reset_t.oe.eq(1),
            subtarget.bus.oe.eq(dut_prog),
        ]

        return subtarget

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        spi_iface = SPIControllerInterface(iface, self.logger)
        nrf24lx1_iface = ProgramNRF24Lx1Interface(spi_iface, self.logger, device,
                                                  self.__addr_dut_prog, self.__addr_dut_reset)
        return nrf24lx1_iface

    @classmethod
    def add_interact_arguments(cls, parser):
        parser.add_argument(
            "-d", "--device", metavar="DEVICE", required=True,
            choices=("LE1", "LU1p16k", "LU1p32k"),
            help="type of device to program (one of: %(choices)s)")

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

        p_read = p_operation.add_parser(
            "read", help="read MCU memory contents")
        p_read.add_argument(
            "file", metavar="HEX-FILE", type=argparse.FileType("wb"),
            help="firmware file to write (in Intel HEX format)")

        p_program = p_operation.add_parser(
            "program", help="program MCU memory contents")
        p_program.add_argument(
            "file", metavar="HEX-FILE", type=argparse.FileType("rb"),
            help="firmware file to read (in Intel HEX format)")
        p_program.add_argument(
            "--info-page", default=False, action="store_true",
            help="erase and program info page, if present in firmware file (DANGEROUS)")

        p_erase = p_operation.add_parser(
            "erase", help="erase MCU memory contents")
        p_erase.add_argument(
            "--info-page", metavar="BACKUP-HEX-FILE", type=str,
            help="back up, erase, and restore info page, removing read protection (DANGEROUS)")

        p_protect_read = p_operation.add_parser(
            "protect-read", help="protect MCU memory from reading via SPI")

        p_enable_debug = p_operation.add_parser(
            "enable-debug", help="enable MCU hardare debugging features")

    async def interact(self, device, args, nrf24lx1_iface):
        page_size = 512
        if args.device == "LE1":
            memory_map  = _nrf24le1_map
            buffer_size = 512
        elif args.device == "LU1p32k":
            memory_map  = _nrf24lu1p_32k_map
            buffer_size = 256
        elif args.device == "LU1p16k":
            memory_map  = _nrf24lu1p_16k_map
            buffer_size = 256
        else:
            assert False

        try:
            await nrf24lx1_iface.reset_program()

            async def check_info_page(address):
                old_status = await nrf24lx1_iface.read_status()
                try:
                    await nrf24lx1_iface.write_status(FSR_BIT_INFEN)
                    fuse, = await nrf24lx1_iface.read(address, 1)
                    return fuse != 0xff
                finally:
                    await nrf24lx1_iface.write_status(old_status)

            async def check_read_protected():
                if await check_info_page(0x23):
                    raise ProgramNRF24Lx1Error("MCU is read protected; run `erase --info-page`")

            if args.operation == "read":
                await check_read_protected()

                chunks = []
                for memory_area in memory_map:
                    self.logger.info("reading %s memory", memory_area.name)
                    if memory_area.spi_addr & 0x10000:
                        await nrf24lx1_iface.write_status(FSR_BIT_INFEN)
                    else:
                        await nrf24lx1_iface.write_status(0)
                    area_data = await nrf24lx1_iface.read(memory_area.spi_addr & 0xffff,
                                                          memory_area.size)
                    chunks.append((memory_area.mem_addr, area_data))
                output_data(args.file, chunks, fmt="ihex")

            if args.operation == "program":
                await check_read_protected()

                area_index   = 0
                memory_area  = memory_map[area_index]
                erased_pages = set()
                for chunk_mem_addr, chunk_data in sorted(input_data(args.file, fmt="ihex"),
                                                         key=lambda c: c[0]):
                    if len(chunk_data) == 0:
                        continue
                    if chunk_mem_addr < memory_area.mem_addr:
                        raise ProgramNRF24Lx1Error("data outside of memory map at {:#06x}"
                                                 .format(chunk_mem_addr))
                    while chunk_mem_addr >= memory_area.mem_addr + memory_area.size:
                        area_index += 1
                        if area_index >= len(memory_area):
                            raise ProgramNRF24Lx1Error("data outside of memory map at {:#06x}"
                                                     .format(chunk_mem_addr))
                        memory_area = memory_map[area_index]
                    if chunk_mem_addr + len(chunk_data) > memory_area.mem_addr + memory_area.size:
                        raise ProgramNRF24Lx1Error("data outside of memory map at {:#06x}"
                                                 .format(memory_area.mem_addr + memory_area.size))
                    if memory_area.spi_addr & 0x10000 and not args.info_page:
                        self.logger.warn("data provided for info page, but info page programming "
                                         "is not enabled")
                        continue

                    chunk_spi_addr = (chunk_mem_addr
                                      - memory_area.mem_addr
                                      + memory_area.spi_addr) & 0xffff
                    if memory_area.spi_addr & 0x10000:
                        level = logging.WARN
                        await nrf24lx1_iface.write_status(FSR_BIT_INFEN)
                    else:
                        level = logging.INFO
                        await nrf24lx1_iface.write_status(0)

                    overwrite_pages = set(range(
                        (chunk_spi_addr // page_size),
                        (chunk_spi_addr + len(chunk_data) + page_size - 1) // page_size))
                    need_erase_pages = overwrite_pages - erased_pages
                    if need_erase_pages:
                        for page in need_erase_pages:
                            page_addr = (memory_area.spi_addr & 0x10000) | (page * page_size)
                            self.logger.log(level, "erasing %s memory at %#06x+%#06x",
                                            memory_area.name, page_addr, page_size)
                            await nrf24lx1_iface.write_enable()
                            await nrf24lx1_iface.erase_page(page)
                            await nrf24lx1_iface.wait_status()
                        erased_pages.update(need_erase_pages)

                    self.logger.log(level, "programming %s memory at %#06x+%#06x",
                                    memory_area.name, chunk_mem_addr, len(chunk_data))
                    while len(chunk_data) > 0:
                        await nrf24lx1_iface.write_enable()
                        await nrf24lx1_iface.program(chunk_spi_addr, chunk_data[:buffer_size])
                        await nrf24lx1_iface.wait_status()
                        chunk_data  = chunk_data[buffer_size:]
                        chunk_spi_addr += buffer_size

            if args.operation == "erase":
                if args.info_page:
                    await nrf24lx1_iface.write_status(FSR_BIT_INFEN)
                    info_page = await nrf24lx1_iface.read(0x0000, 0x0100)
                    self.logger.warn("backing up info page to %s", args.info_page)
                    if os.path.isfile(args.info_page):
                        raise ProgramNRF24Lx1Error("info page backup file already exists")
                    with open(args.info_page, "wb") as f:
                        output_data(f, [(0x10000, info_page)])
                    self.logger.warn("erasing code and data memory, and info page")
                else:
                    await check_read_protected()
                    await nrf24lx1_iface.write_status(0)
                    self.logger.info("erasing code and data memory")
                try:
                    await nrf24lx1_iface.write_enable()
                    await nrf24lx1_iface.erase_all()
                    await nrf24lx1_iface.wait_status()
                    if args.info_page:
                        self.logger.info("restoring info page DSYS area")
                        await nrf24lx1_iface.write_enable()
                        await nrf24lx1_iface.program(0, info_page[:32]) # DSYS only
                        await nrf24lx1_iface.wait_status()
                except:
                    if args.info_page:
                        self.logger.error("IMPORTANT: programming failed; restore DSYS manually "
                                          "using `program --info-page %s`",
                                          args.info_page)
                    raise

            if args.operation == "protect-read":
                if await check_info_page(0x23):
                    raise ProgramNRF24Lx1Error("memory read protection is already enabled")

                self.logger.warn("protecting code and data memory from reads")
                await nrf24lx1_iface.write_enable()
                await nrf24lx1_iface.disable_read()
                await nrf24lx1_iface.wait_status()

            if args.operation == "enable-debug":
                if await check_info_page(0x24):
                    raise ProgramNRF24Lx1Error("hardware debugging features already enabled")

                self.logger.info("enabling hardware debugging features")
                await nrf24lx1_iface.write_enable()
                await nrf24lx1_iface.enable_debug()
                await nrf24lx1_iface.wait_status()

        finally:
            await nrf24lx1_iface.reset_application()

# -------------------------------------------------------------------------------------------------

class ProgramNRF24Lx1AppletTestCase(GlasgowAppletTestCase, applet=ProgramNRF24Lx1Applet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
