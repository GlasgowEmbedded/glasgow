import logging

from .. import *
from ..i2c_master import I2CMasterApplet


logger = logging.getLogger(__name__)


class I2CEEPROM24CInterface:
    def __init__(self, interface, logger, i2c_address, address_width, page_size):
        self.lower       = interface
        self._logger     = logger
        self._level      = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._i2c_addr   = i2c_address
        self._addr_width = address_width
        self._page_size  = page_size

    def _log(self, message, *args):
        self._logger.log(self._level, "I2C EEPROM: " + message, *args)

    def _carry_addr(self, addr):
        if self._addr_width == 2:
            addr_msb = (addr >> 8) & 0xff
            addr_lsb = (addr >> 0) & 0xff
            return (self._i2c_addr, [addr_msb, addr_lsb])
        else:
            i2c_addr = self._i2c_addr | (addr >> 8)
            return (i2c_addr, [addr & 0xff])

    def read(self, addr, size):
        i2c_addr, addr_bytes = self._carry_addr(addr)

        self._log("i2c-addr=%#04x addr=%#06x", i2c_addr, addr)
        result = self.lower.write(i2c_addr, addr_bytes)
        if result is None:
            self._log("unacked")
            return None

        self._log("read=%d", size)
        data = self.lower.read(i2c_addr, size, stop=True)
        self._log("data=<%s>", data.hex())
        return data

    def write(self, addr, data):
        while len(data) > 0:
            i2c_addr, addr_bytes = self._carry_addr(addr)

            if addr % self._page_size == 0:
                chunk_size = self._page_size
            else:
                chunk_size = self._page_size - addr % self._page_size

            chunk = data[:chunk_size]
            data  = data[chunk_size:]
            self._log("i2c-addr=%#04x addr=%#06x write=<%s>", i2c_addr, addr, chunk.hex())
            result = self.lower.write(i2c_addr, [*addr_bytes, *chunk], stop=True)
            if result is None:
                self._log("unacked")
                return False

            while not self.lower.poll(i2c_addr): pass
            addr += len(chunk)

        return True


class I2CEEPROM24CApplet(I2CMasterApplet, name="i2c-eeprom-24c"):
    logger = logger
    help = "read and write 24C-compatible EEPROMs"
    description = """
    Read and write arbitrary areas of a 24Cxx-compatible EEPROM.

    If one address byte is used and an address higher than 255 is specified, either directly
    or implicitly through operation size, the high address bits are logically ORed with
    the I2C address.
    """

    @classmethod
    def add_run_arguments(cls, parser, access):
        access.add_run_arguments(parser)

        parser.add_argument(
            "-A", "--i2c-address", type=int, metavar="I2C-ADDR", default=0b1010000,
            help="I2C address of the EEPROM; typically 0b1010(A2)(A1)(A0) "
                 "(default: 0b1010000)")
        parser.add_argument(
            "-W", "--address-width", type=int, choices=[1, 2], required=True,
            help="number of address bytes to use (one of: 1 2)")
        parser.add_argument(
            "-P", "--page-size", type=int, metavar="PAGE-SIZE", default=8,
            help="page buffer size; writes will be split into PAGE-SIZE byte chunks")

        parser.add_argument(
            "-a", "--address", type=int, metavar="ADDR", default=0,
            help="first memory address of the read or write operation")
        g_operation = parser.add_mutually_exclusive_group(required=True)
        g_operation.add_argument(
            "-r", "--read", type=int, metavar="SIZE",
            help="read SIZE bytes starting at ADDR")
        def hex(arg): return bytes.fromhex(arg)
        g_operation.add_argument(
            "-w", "--write", type=hex, metavar="DATA",
            help="write hex bytes DATA starting at ADDR")

    def run(self, device, args, interactive=True):
        i2c_iface = super().run(device, args, interactive=False)
        eeprom_iface = I2CEEPROM24CInterface(
            i2c_iface, self.logger, args.i2c_address, args.address_width, args.page_size)
        if not interactive:
            return eeprom_iface

        if args.read is not None:
            result = eeprom_iface.read(args.address, args.read)
            if result is not None:
                print(result.hex())

        elif args.write is not None:
            eeprom_iface.write(args.address, args.write)
