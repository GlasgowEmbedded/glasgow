import logging

from glasgow.applet import GlasgowAppletV2
from glasgow.support.endpoint import ServerEndpoint
from glasgow.protocol.flashrom import SerprogBus, SerprogCommand
from glasgow.applet.interface.spi_controller import SPIControllerInterface


__all__ = []


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

    PROGNAME = b"Glasgow serprog\0"
    assert len(PROGNAME) == 16

    def __init__(self, logger: logging.Logger, spi_iface: SPIControllerInterface,
                 endpoint: ServerEndpoint):
        self.logger    = logger
        self.spi_iface = spi_iface
        self.endpoint  = endpoint

    async def get_u8(self):
        data, = await self.endpoint.recv(1)
        return data

    async def get_u24(self):
        data = await self.endpoint.recv(3)
        return int.from_bytes(data, byteorder="little")

    async def put_u8(self, value):
        await self.endpoint.send([value])

    async def put_u16(self, value):
        await self.endpoint.send(value.to_bytes(length=2, byteorder="little"))

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
            cmdmap = self.CMDMAP_VALUE.to_bytes(length=32, byteorder="little")
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
            async with self.spi_iface.select():
                await self.spi_iface.write(sdata)
                if rlen > 0:
                    rdata = await self.spi_iface.read(rlen)
                else:
                    rdata = bytes([])
            await self.endpoint.send(rdata)
        else:
            self.logger.warning(f"Unhandled command {cmd:#04x}")
            await self.nak()


class SPIFlashromApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "expose SPI via flashrom serprog interface"
    description = """
    Expose SPI via a socket using the flashrom serprog protocol; see https://flashrom.org.

    This applet has the same default pin assignment as the `memory-25x` applet; see its description
    for details.

    Usage:

    ::

        glasgow run spi-flashrom -V 3.3 --freq 4000 tcp::2222
        /sbin/flashrom -p serprog:ip=localhost:2222

    It is also possible to flash 25-series flash chips using the `memory-25x` applet, which does
    not require a third-party tool. The advantage of using the `spi-flashrom` applet is that
    flashrom offers compatibility with a wider variety of devices, some of which may not be
    supported by the `memory-25x` applet.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "cs",   default="A5", required=True)
        access.add_pins_argument(parser, "sck",  default="A1", required=True)
        access.add_pins_argument(parser, "copi", default="A2", required=True)
        access.add_pins_argument(parser, "cipo", default="A4", required=True)
        access.add_pins_argument(parser, "wp",   default="A3")
        access.add_pins_argument(parser, "hold", default="A0")

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.spi_iface = SPIControllerInterface(self.logger, self.assembly,
                cs=args.cs, sck=args.sck, copi=args.copi, cipo=args.cipo)
            if args.wp:
                self.assembly.use_pulls({~args.wp:   "low"})
            if args.hold:
                self.assembly.use_pulls({~args.hold: "low"})

    @classmethod
    def add_setup_arguments(cls, parser):
        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=100,
            help="set SCK frequency to FREQ kHz (default: %(default)s)")

    async def setup(self, args):
        await self.spi_iface.clock.set_frequency(args.frequency * 1000)

    @classmethod
    def add_run_arguments(cls, parser):
        ServerEndpoint.add_argument(parser, "endpoint")

    async def run(self, args):
        endpoint = await ServerEndpoint("socket", self.logger, args.endpoint)
        while True:
            try:
                await SerprogCommandHandler(self.logger, self.spi_iface, endpoint).handle_cmd()
            except EOFError:
                pass

    @classmethod
    def tests(cls):
        from . import test
        return test.SPIFlashromAppletTestCase
