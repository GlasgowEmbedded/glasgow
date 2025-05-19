import logging
import asyncio
import enum
from amaranth import *
from amaranth.lib import io

from ... import *
from ....support.endpoint import *
from ...interface.spi_controller import SPIControllerApplet


class SPISerprogInterface:
    def __init__(self, interface):
        self.lower = interface

    async def write_read(self, sdata, rlen):
        assert len(sdata) > 0
        async with self.lower.select():
            await self.lower.write(sdata)
            return await self.lower.read(rlen)


class SerprogCommand(enum.IntEnum):
    """
    Serprog commands and responses, based on:

    - https://review.coreboot.org/plugins/gitiles/flashrom/+/refs/tags/v1.0.2/serprog.h
    - https://review.coreboot.org/plugins/gitiles/flashrom/+/refs/tags/v1.0.2/Documentation/serprog-protocol.txt
    """
    ACK               = 0x06
    NAK               = 0x15
    CMD_NOP           = 0x00    # No operation
    CMD_Q_IFACE       = 0x01    # Query interface version
    CMD_Q_CMDMAP      = 0x02    # Query supported commands bitmap
    CMD_Q_PGMNAME     = 0x03    # Query programmer name
    CMD_Q_SERBUF      = 0x04    # Query Serial Buffer Size
    CMD_Q_BUSTYPE     = 0x05    # Query supported bustypes
    CMD_Q_CHIPSIZE    = 0x06    # Query supported chipsize (2^n format)
    CMD_Q_OPBUF       = 0x07    # Query operation buffer size
    CMD_Q_WRNMAXLEN   = 0x08    # Query Write to opbuf: Write-N maximum length
    CMD_R_BYTE        = 0x09    # Read a single byte
    CMD_R_NBYTES      = 0x0A    # Read n bytes
    CMD_O_INIT        = 0x0B    # Initialize operation buffer
    CMD_O_WRITEB      = 0x0C    # Write opbuf: Write byte with address
    CMD_O_WRITEN      = 0x0D    # Write to opbuf: Write-N
    CMD_O_DELAY       = 0x0E    # Write opbuf: udelay
    CMD_O_EXEC        = 0x0F    # Execute operation buffer
    CMD_SYNCNOP       = 0x10    # Special no-operation that returns NAK+ACK
    CMD_Q_RDNMAXLEN   = 0x11    # Query read-n maximum length
    CMD_S_BUSTYPE     = 0x12    # Set used bustype(s).
    CMD_O_SPIOP       = 0x13    # Perform SPI operation.
    CMD_S_SPI_FREQ    = 0x14    # Set SPI clock frequency
    CMD_S_PIN_STATE   = 0x15    # Enable/disable output drivers


class SerprogBus(enum.IntEnum):
    """
    Bus types supported by the serprog protocol.
    """
    PARALLEL = (1 << 0)
    LPC = (1 << 1)
    FHW = (1 << 2)
    SPI = (1 << 3)


class SerprogCommandHandler:
    CMDMAP_VALUE = (
        (1 << SerprogCommand.CMD_NOP)       |
        (1 << SerprogCommand.CMD_Q_IFACE)   |
        (1 << SerprogCommand.CMD_Q_CMDMAP)  |
        (1 << SerprogCommand.CMD_Q_PGMNAME) |
        (1 << SerprogCommand.CMD_Q_SERBUF)  |
        (1 << SerprogCommand.CMD_Q_BUSTYPE) |
        (1 << SerprogCommand.CMD_SYNCNOP)   |
        (1 << SerprogCommand.CMD_O_SPIOP)   |
        (1 << SerprogCommand.CMD_S_BUSTYPE)
    )

    PROGNAME = b'Glasgow serprog\0'
    assert len(PROGNAME) == 16

    def __init__(self, interface, endpoint, logger):
        self.interface = interface
        self.endpoint  = endpoint
        self.logger    = logger

    async def get_u8(self):
        data, = await self.endpoint.recv(1)
        return data

    async def get_u24(self):
        data = await self.endpoint.recv(3)
        return int.from_bytes(data, byteorder='little')

    async def put_u8(self, value):
        await self.endpoint.send([value])

    async def put_u16(self, value):
        await self.endpoint.send(value.to_bytes(length=2, byteorder='little'))

    async def ack(self):
        await self.put_u8(SerprogCommand.ACK)

    async def nak(self):
        await self.put_u8(SerprogCommand.NAK)

    async def handle_cmd(self):
        cmd = await self.get_u8()

        if cmd == SerprogCommand.CMD_NOP:
            await self.ack()
        elif cmd == SerprogCommand.CMD_SYNCNOP:
            await self.nak()
            await self.ack()
        elif cmd == SerprogCommand.CMD_Q_IFACE:
            await self.ack()
            await self.put_u16(1)
        elif cmd == SerprogCommand.CMD_Q_BUSTYPE:
            await self.ack()
            await self.put_u8(SerprogBus.SPI)
        elif cmd == SerprogCommand.CMD_Q_PGMNAME:
            await self.ack()
            await self.endpoint.send(self.PROGNAME)
        elif cmd == SerprogCommand.CMD_Q_CMDMAP:
            cmdmap = self.CMDMAP_VALUE.to_bytes(length=32, byteorder='little')
            await self.ack()
            await self.endpoint.send(cmdmap)
        elif cmd == SerprogCommand.CMD_Q_SERBUF:
            await self.ack()
            await self.put_u16(0xffff)
        elif cmd == SerprogCommand.CMD_S_BUSTYPE:
            bustype = await self.get_u8()
            if bustype == SerprogBus.SPI:
                await self.ack()
            else:
                await self.nak()
        elif cmd == SerprogCommand.CMD_O_SPIOP:
            slen = await self.get_u24()
            rlen = await self.get_u24()
            await self.ack()
            sdata = await self.endpoint.recv(slen)
            assert len(sdata) == slen
            rdata = await self.interface.write_read(sdata, rlen)
            await self.endpoint.send(rdata)
        else:
            self.logger.warning(f"Unhandled command {cmd:#04x}")
            await self.nak()


class SPIFlashromSubtarget(Elaboratable):
    def __init__(self, controller, hold):
        self.controller = controller
        self.hold = hold

    def elaborate(self, platform):
        m = Module()

        m.submodules.controller = self.controller
        m.submodules.hold_buffer = hold = io.Buffer("o", self.hold)

        m.d.comb += self.controller.bus.oe.eq(self.controller.bus.cs == 1)

        if self.hold is not None:
            m.d.comb += [
                hold.oe.eq(1),
                hold.o.eq(1),
            ]

        return m


class SPIFlashromApplet(SPIControllerApplet):
    logger = logging.getLogger(__name__)
    help = "expose SPI via flashrom serprog interface"
    description = """
    Expose SPI via a socket using the flashrom serprog protocol; see https://www.flashrom.org.
    This applet has the same default pin assignment as the `memory-25x` applet; See its description
    for details.

    Usage:

    ::
        glasgow run spi-flashrom -V 3.3 --freq 4000 tcp::2222
        /sbin/flashrom -p serprog:ip=localhost:2222

    It is also possible to flash 25-series flash chips using the `memory-25x` applet, which does
    not require a third-party tool.
    The advantage of using the `spi-flashrom` applet is that flashrom offers compatibility with
    a wider variety of devices, some of which may not be supported by the `memory-25x` applet.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access, omit_pins=True)

        access.add_pins_argument(parser, "cs",   default="A5", required=True)
        access.add_pins_argument(parser, "cipo", default="A4", required=True)
        access.add_pins_argument(parser, "wp",   default="A3")
        access.add_pins_argument(parser, "copi", default="A2", required=True)
        access.add_pins_argument(parser, "sck",  default="A1", required=True)
        access.add_pins_argument(parser, "hold", default="A0")

    def build_subtarget(self, target, args):
        subtarget = super().build_subtarget(target, args)
        if args.hold is not None:
            hold = self.mux_interface.get_port(args.hold, name="hold")
        else:
            hold = None
        return SPIFlashromSubtarget(subtarget, hold)

    async def run(self, device, args):
        spi_iface = await self.run_lower(SPIFlashromApplet, device, args)
        return SPISerprogInterface(spi_iface)

    @classmethod
    def add_interact_arguments(cls, parser):
        ServerEndpoint.add_argument(parser, "endpoint")

    async def interact(self, device, args, iface):
        endpoint = await ServerEndpoint("socket", self.logger, args.endpoint,
            deprecated_cancel_on_eof=True)
        async def handle():
            while True:
                try:
                    handler = SerprogCommandHandler(iface, endpoint, self.logger)
                    await handler.handle_cmd()
                except asyncio.CancelledError:
                    pass
        handle_fut = asyncio.ensure_future(handle())
        # This `asyncio.wait()` call is necessary for ^C to be handled correctly.
        await asyncio.wait([handle_fut], return_when=asyncio.FIRST_EXCEPTION)
