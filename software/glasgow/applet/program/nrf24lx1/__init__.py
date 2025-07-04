# Reference: https://infocenter.nordicsemi.com/pdf/nRF24LE1_PS_v1.6.pdf
# Accession: G00035

from dataclasses import dataclass
import asyncio
import logging
import argparse
import struct
import enum
import os

from fx2.format import input_data, output_data

from glasgow.support.logging import dump_hex
from glasgow.abstract import AbstractAssembly, GlasgowPin, ClockDivisor
from glasgow.applet import GlasgowAppletError, GlasgowAppletV2
from glasgow.applet.interface.spi_controller import SPIControllerInterface
from glasgow.applet.control.gpio import GPIOInterface


__all__ = ["ProgramNRF24Lx1Error", "ProgramNRF24Lx1Interface"]


class ProgramNRF24Lx1Error(GlasgowAppletError):
    pass


@dataclass
class _MemoryArea:
    name: str
    mem_addr: int
    spi_addr: int
    size: int


@dataclass
class _Device:
    memory_map: list[_MemoryArea]
    buffer_size: int


_devices = {
    "LE1": _Device(
        memory_map=[
            _MemoryArea(name="code",    mem_addr= 0x0000, spi_addr= 0x0000, size=0x4000),
            _MemoryArea(name="NV data", mem_addr= 0xFC00, spi_addr= 0x4400, size=0x0400),
            _MemoryArea(name="info",    mem_addr=0x10000, spi_addr=0x10000, size=0x0200),
        ],
        buffer_size=512,
    ),
    "LU1p32k": _Device(
        memory_map=[
            _MemoryArea(name="code",    mem_addr= 0x0000, spi_addr= 0x0000, size=0x7C00),
            _MemoryArea(name="NV data", mem_addr= 0x7C00, spi_addr= 0x7C00, size=0x0400),
            _MemoryArea(name="info",    mem_addr=0x10000, spi_addr=0x10000, size=0x0200),
        ],
        buffer_size=256,
    ),
    "LU1p16k": _Device(
        memory_map=[
            _MemoryArea(name="code",    mem_addr= 0x0000, spi_addr= 0x0000, size=0x3C00),
            _MemoryArea(name="NV data", mem_addr= 0x7C00, spi_addr= 0x7C00, size=0x0400),
            _MemoryArea(name="info",    mem_addr=0x10000, spi_addr=0x10000, size=0x0200),
        ],
        buffer_size=256,
    )
}


class _FlashStatus(enum.IntFlag):
    ENDEBUG = 0b10000000
    STP     = 0b01000000
    WEN     = 0b00100000
    RDYN    = 0b00010000
    INFEN   = 0b00001000
    RDISMB  = 0b00000100


class ProgramNRF24Lx1Interface:
    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
                 cs: GlasgowPin, sck: GlasgowPin, copi: GlasgowPin, cipo: GlasgowPin,
                 prog: GlasgowPin, reset: GlasgowPin):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        self._spi_iface = SPIControllerInterface(logger, assembly,
            cs=cs, sck=sck, copi=copi, cipo=cipo, mode=0)
        self._prog_iface = GPIOInterface(logger, assembly, pins=(prog,))
        self._reset_iface = GPIOInterface(logger, assembly, pins=(~reset,))

    def _log(self, message, *args):
        self._logger.log(self._level, "nRF24Lx1: " + message, *args)

    @property
    def clock(self) -> ClockDivisor:
        return self._spi_iface.clock

    async def _reset(self):
        await self._reset_iface.output(0, True)
        await asyncio.sleep(0.001) # spec requires 0.1 us
        await self._reset_iface.output(0, False)

    async def reset_program(self):
        self._log("reset mode=program")
        await self._spi_iface.synchronize()
        await self._prog_iface.output(0, True)
        await self._reset()
        await self._spi_iface.synchronize()
        await self._spi_iface.delay_us(1500)

    async def reset_application(self):
        self._log("reset mode=application")
        await self._spi_iface.synchronize()
        await self._prog_iface.output(0, False)
        await self._reset()

    async def _command(self, cmd: int, arg: list[int] = [], ret: int = 0) -> memoryview | None:
        async with self._spi_iface.select():
            await self._spi_iface.write(bytes([cmd, *arg]))
            if ret > 0:
                result = await self._spi_iface.read(ret)
                self._log("cmd=%02X arg=<%s> res=<%s>", cmd, dump_hex(arg), dump_hex(result))
                return result
            else:
                self._log("cmd=%02X arg=<%s>", cmd, dump_hex(arg))
                return None

    async def read_status(self) -> _FlashStatus:
        status, = await self._command(0x05, ret=1)
        self._log(f"read status={status:#010b}")
        return _FlashStatus(status)

    async def write_status(self, status: _FlashStatus):
        self._log(f"write status={status:#010b}")
        await self._command(0x01, arg=[status])

    async def wait_status(self):
        self._log("wait status")
        while await self.read_status() & _FlashStatus.WEN: pass

    async def write_enable(self):
        self._log("write enable")
        await self._command(0x06)

    async def write_disable(self):
        self._log("write disable")
        await self._command(0x04)

    async def check_presence(self) -> bool:
        await self.write_enable()
        present = bool(await self.read_status() & _FlashStatus.WEN)
        if present:
            await self.write_disable()
        return present

    async def read(self, address: int, length: int) -> memoryview:
        self._log("read address=%#06x length=%#06x", address, length)
        return await self._command(0x03, arg=struct.pack(">H", address), ret=length)

    async def program(self, address: int, data: bytes | bytearray | memoryview):
        self._log("program address=%#06x length=%#06x", address, len(data))
        await self._command(0x02, arg=struct.pack(">H", address) + bytes(data))

    async def erase_page(self, page: int):
        self._log("erase page=%#04x", page)
        await self._command(0x52, arg=[page])

    async def erase_all(self):
        self._log("erase all")
        await self._command(0x62)

    async def read_unprotected_pages(self) -> int:
        pages, = await self._command(0x89, ret=1)
        self._log("read unprotected pages=%#04x", pages)
        return pages

    async def disable_read(self):
        self._log("disable read")
        await self._command(0x85)

    async def enable_debug(self):
        self._log("enable debug")
        await self._command(0x86)


class ProgramNRF24Lx1Applet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "program nRF24LE1 and nRF24LU1+ RF microcontrollers"
    description = """
    Program the non-volatile memory of nRF24LE1 and nRF24LU1+ microcontrollers.
    """
    required_revision = "C0"
    nrf24lx1_iface: ProgramNRF24Lx1Interface

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        # Order matches the pin order, in clockwise direction.
        access.add_pins_argument(parser, "prog",  default=True, required=True)
        access.add_pins_argument(parser, "sck",   default=True, required=True)
        access.add_pins_argument(parser, "copi",  default=True, required=True)
        access.add_pins_argument(parser, "cipo",  default=True, required=True)
        access.add_pins_argument(parser, "cs",    default=True, required=True)
        access.add_pins_argument(parser, "reset", default=True, required=True)

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.nrf24lx1_iface = ProgramNRF24Lx1Interface(self.logger, self.assembly,
                cs=args.cs, sck=args.sck, copi=args.copi, cipo=args.cipo,
                prog=args.prog, reset=args.reset)

    @classmethod
    def add_setup_arguments(cls, parser):
        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=1000,
            help="set SPI frequency to FREQ kHz (default: %(default)s)")

    async def setup(self, args):
        await self.nrf24lx1_iface.clock.set_frequency(args.frequency * 1000)

    @classmethod
    def add_run_arguments(cls, parser):
        parser.add_argument(
            "-d", "--device", metavar="DEVICE", required=True,
            choices=list(_devices.keys()),
            help=f"type of device to program (one of: {', '.join(_devices.keys())})")

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

    async def run(self, args):
        device = _devices[args.device]
        page_size = 512
        memory_map = device.memory_map
        buffer_size = device.buffer_size

        try:
            await self.nrf24lx1_iface.reset_program()

            if not await self.nrf24lx1_iface.check_presence():
                raise ProgramNRF24Lx1Error("MCU is not present")

            async def check_info_page(address):
                old_status = await self.nrf24lx1_iface.read_status()
                try:
                    await self.nrf24lx1_iface.write_status(_FlashStatus.INFEN)
                    fuse, = await self.nrf24lx1_iface.read(address, 1)
                    return fuse != 0xff
                finally:
                    await self.nrf24lx1_iface.write_status(old_status)

            async def check_read_protected():
                if await check_info_page(0x23):
                    raise ProgramNRF24Lx1Error("MCU is read protected; run `erase --info-page`")

            if args.operation == "read":
                await check_read_protected()

                chunks = []
                for memory_area in memory_map:
                    self.logger.info("reading %s memory", memory_area.name)
                    if memory_area.spi_addr & 0x10000:
                        await self.nrf24lx1_iface.write_status(_FlashStatus.INFEN)
                    else:
                        await self.nrf24lx1_iface.write_status(0)
                    area_data = await self.nrf24lx1_iface.read(memory_area.spi_addr & 0xffff,
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
                        raise ProgramNRF24Lx1Error(
                            f"data outside of memory map at {chunk_mem_addr:#06x}")
                    while chunk_mem_addr >= memory_area.mem_addr + memory_area.size:
                        area_index += 1
                        if area_index >= memory_area.size:
                            raise ProgramNRF24Lx1Error(
                                f"data outside of memory map at {chunk_mem_addr:#06x}")
                        memory_area = memory_map[area_index]
                    if chunk_mem_addr + len(chunk_data) > memory_area.mem_addr + memory_area.size:
                        raise ProgramNRF24Lx1Error(
                            f"data outside of memory map at "
                            f"{memory_area.mem_addr + memory_area.size:#06x}")
                    if memory_area.spi_addr & 0x10000 and not args.info_page:
                        self.logger.warning("data provided for info page, but info page "
                                            "programming is not enabled")
                        continue

                    chunk_spi_addr = (chunk_mem_addr
                                      - memory_area.mem_addr
                                      + memory_area.spi_addr) & 0xffff
                    if memory_area.spi_addr & 0x10000:
                        level = logging.WARNING
                        await self.nrf24lx1_iface.write_status(_FlashStatus.INFEN)
                    else:
                        level = logging.INFO
                        await self.nrf24lx1_iface.write_status(0)

                    overwrite_pages = set(range(
                        (chunk_spi_addr // page_size),
                        (chunk_spi_addr + len(chunk_data) + page_size - 1) // page_size))
                    need_erase_pages = overwrite_pages - erased_pages
                    if need_erase_pages:
                        for page in need_erase_pages:
                            page_addr = (memory_area.spi_addr & 0x10000) | (page * page_size)
                            self.logger.log(level, "erasing %s memory at %#06x+%#06x",
                                            memory_area.name, page_addr, page_size)
                            await self.nrf24lx1_iface.write_enable()
                            await self.nrf24lx1_iface.erase_page(page)
                            await self.nrf24lx1_iface.wait_status()
                        erased_pages.update(need_erase_pages)

                    self.logger.log(level, "programming %s memory at %#06x+%#06x",
                                    memory_area.name, chunk_mem_addr, len(chunk_data))
                    while len(chunk_data) > 0:
                        await self.nrf24lx1_iface.write_enable()
                        await self.nrf24lx1_iface.program(chunk_spi_addr, chunk_data[:buffer_size])
                        await self.nrf24lx1_iface.wait_status()
                        chunk_data  = chunk_data[buffer_size:]
                        chunk_spi_addr += buffer_size

            if args.operation == "erase":
                if args.info_page:
                    await self.nrf24lx1_iface.write_status(_FlashStatus.INFEN)
                    info_page = await self.nrf24lx1_iface.read(0x0000, 0x0100)
                    self.logger.warning("backing up info page to %s", args.info_page)
                    if os.path.isfile(args.info_page):
                        raise ProgramNRF24Lx1Error("info page backup file already exists")
                    with open(args.info_page, "wb") as f:
                        output_data(f, [(0x10000, info_page)])
                    self.logger.warning("erasing code and data memory, and info page")
                else:
                    await check_read_protected()
                    await self.nrf24lx1_iface.write_status(0)
                    self.logger.info("erasing code and data memory")
                try:
                    await self.nrf24lx1_iface.write_enable()
                    await self.nrf24lx1_iface.erase_all()
                    await self.nrf24lx1_iface.wait_status()
                    if args.info_page:
                        self.logger.info("restoring info page DSYS area")
                        await self.nrf24lx1_iface.write_enable()
                        await self.nrf24lx1_iface.program(0, info_page[:32]) # DSYS only
                        await self.nrf24lx1_iface.wait_status()
                except:
                    if args.info_page:
                        self.logger.error("IMPORTANT: programming failed; restore DSYS manually "
                                          "using `program --info-page %s`",
                                          args.info_page)
                    raise

            if args.operation == "protect-read":
                if await check_info_page(0x23):
                    raise ProgramNRF24Lx1Error("memory read protection is already enabled")

                self.logger.warning("protecting code and data memory from reads")
                await self.nrf24lx1_iface.write_enable()
                await self.nrf24lx1_iface.disable_read()
                await self.nrf24lx1_iface.wait_status()

            if args.operation == "enable-debug":
                if await check_info_page(0x24):
                    raise ProgramNRF24Lx1Error("hardware debugging features already enabled")

                self.logger.info("enabling hardware debugging features")
                await self.nrf24lx1_iface.write_enable()
                await self.nrf24lx1_iface.enable_debug()
                await self.nrf24lx1_iface.wait_status()

        finally:
            await self.nrf24lx1_iface.reset_application()

    @classmethod
    def tests(cls):
        from . import test
        return test.ProgramNRF24Lx1AppletTestCase
