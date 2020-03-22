import logging
import argparse

from ...interface.i2c_initiator import I2CInitiatorApplet
from ... import *


class Memory24xInterface:
    def __init__(self, interface, logger, i2c_address, address_width, page_size):
        self.lower       = interface
        self._logger     = logger
        self._level      = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._i2c_addr   = i2c_address
        self._addr_width = address_width
        self._page_size  = page_size

    def _log(self, message, *args):
        self._logger.log(self._level, "24x: " + message, *args)

    def _carry_addr(self, addr):
        if self._addr_width == 2:
            addr_msb = (addr >> 8) & 0xff
            addr_lsb = (addr >> 0) & 0xff
            return (self._i2c_addr, [addr_msb, addr_lsb])
        else:
            i2c_addr = self._i2c_addr | (addr >> 8)
            return (i2c_addr, [addr & 0xff])

    async def read(self, addr, length):
        chunks = []

        while length > 0:
            i2c_addr, addr_bytes = self._carry_addr(addr)

            # Our lower layer can't do reads of 64K and higher, so use 32K chunks.
            chunk_size = min(length, 0x8000)

            # Note that even if this is a 1-byte address EEPROM and we write 2 bytes here,
            # we will not overwrite the contents, since the actual write is only initiated
            # on stop, not repeated start condition.
            self._log("i2c-addr=%#04x addr=%#06x", i2c_addr, addr)
            result = await self.lower.write(i2c_addr, addr_bytes)
            if result is False:
                self._log("unacked")
                return None

            self._log("read=%d", chunk_size)
            chunk = await self.lower.read(i2c_addr, chunk_size, stop=True)
            if chunk is None:
                self._log("unacked")
            else:
                self._log("chunk=<%s>", chunk.hex())
                chunks.append(chunk)

            length -= chunk_size
            addr   += chunk_size

        return b"".join(chunks)

    async def write(self, addr, data):
        while len(data) > 0:
            i2c_addr, addr_bytes = self._carry_addr(addr)

            if addr % self._page_size == 0:
                chunk_size = self._page_size
            else:
                chunk_size = self._page_size - addr % self._page_size

            chunk = data[:chunk_size]
            data  = data[chunk_size:]
            self._log("i2c-addr=%#04x addr=%#06x write=<%s>", i2c_addr, addr, chunk.hex())
            result = await self.lower.write(i2c_addr, [*addr_bytes, *chunk], stop=True)
            if result is False:
                self._log("unacked")
                return False

            while not await self.lower.poll(i2c_addr): pass
            addr += len(chunk)

        return True


class Memory24xApplet(I2CInitiatorApplet, name="memory-24x"):
    logger = logging.getLogger(__name__)
    help = "read and write 24-series I²C EEPROM memories"
    default_page_size = 8
    description = """
    Read and write memories compatible with 24-series EEPROM memory, such as Microchip 24C02C,
    Atmel 24C256, or hundreds of other memories that typically have "24X" where X is a letter
    in their part number.

    If one address byte is used and an address higher than 255 is specified, either directly
    or implicitly through operation size, the high address bits are logically ORed with
    the I²C address. In this case the pins used on smaller devices for low address bits are
    internally not connected.

    # Page size

    The memory performs writes by first latching incoming data into a page buffer, and committing
    the page buffer after a stop condition. If more data is provided than the page buffer size,
    or if page boundary is crossed when the address is autoincremneted, a wraparound occurs; this
    generally results in wrong memory contents after the write operation is complete. The purpose
    of having a page buffer is to batch updates, since a write of any length between 1 and page
    size takes the same amount of time.

    Using the correct page size is vitally important for writes. A smaller page size can always
    be used with a memory that actually has a larger page size, but not vice versa. Using a page
    size larger than 1 is necessary to get good performance.

    The default page size in this applet is {page_size}, because no memories with page smaller
    than {page_size} bytes have been observed in the wild so far, and this results in decent
    performance with all memories. However, it is possible that a memory could have a smaller
    page size. In that case it is necessary to specify a `--page-size 1` option explicitly.
    Conversely, specifying a larger page size, when applicable, will significantly improve write
    performance.

    The pinout of a typical 24-series IC is as follows (the A2:0 pins may be N/C in large devices):

    ::
          A0 @ * VCC
          A1 * * WP#
          A2 * * SCL
         GND * * SDA
    """.format(page_size=default_page_size)

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)

        def address(arg):
            return int(arg, 0)

        parser.add_argument(
            "-A", "--i2c-address", type=address, metavar="I2C-ADDR", default=0b1010000,
            help="I²C address of the memory; typically 0b1010(A2)(A1)(A0) "
                 "(default: 0b1010000)")
        parser.add_argument(
            "-W", "--address-width", type=int, choices=[1, 2], required=True,
            help="number of address bytes to use (one of: 1 2)")
        parser.add_argument(
            "-P", "--page-size", type=int, metavar="PAGE-SIZE", default=cls.default_page_size,
            help="page buffer size; writes will be split into PAGE-SIZE byte long aligned chunks")

    async def run(self, device, args):
        i2c_iface = await super().run(device, args)
        return Memory24xInterface(
            i2c_iface, self.logger, args.i2c_address, args.address_width, args.page_size)

    @classmethod
    def add_interact_arguments(cls, parser):
        def address(arg):
            return int(arg, 0)
        def length(arg):
            return int(arg, 0)
        def hex_bytes(arg):
            return bytes.fromhex(arg)

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

        p_read = p_operation.add_parser(
            "read", help="read memory")
        p_read.add_argument(
            "address", metavar="ADDRESS", type=address,
            help="read memory starting at address ADDRESS, with wraparound")
        p_read.add_argument(
            "length", metavar="LENGTH", type=length,
            help="read LENGTH bytes from memory")
        p_read.add_argument(
            "-f", "--file", metavar="FILENAME", type=argparse.FileType("wb"),
            help="write memory contents to FILENAME")

        p_write = p_operation.add_parser(
            "write", help="write memory")
        p_write.add_argument(
            "address", metavar="ADDRESS", type=address,
            help="write memory starting at address ADDRESS")
        g_write_data = p_write.add_mutually_exclusive_group(required=True)
        g_write_data.add_argument(
            "-d", "--data", metavar="DATA", type=hex_bytes,
            help="write memory with DATA as hex bytes")
        g_write_data.add_argument(
            "-f", "--file", metavar="FILENAME", type=argparse.FileType("rb"),
            help="write memory with contents of FILENAME")

        p_verify = p_operation.add_parser(
            "verify", help="verify memory")
        p_verify.add_argument(
            "address", metavar="ADDRESS", type=address,
            help="verify memory starting at address ADDRESS")
        g_verify_data = p_verify.add_mutually_exclusive_group(required=True)
        g_verify_data.add_argument(
            "-d", "--data", metavar="DATA", type=hex_bytes,
            help="compare memory with DATA as hex bytes")
        g_verify_data.add_argument(
            "-f", "--file", metavar="FILENAME", type=argparse.FileType("rb"),
            help="compare memory with contents of FILENAME")

    async def interact(self, device, args, m24x_iface):
        if args.operation == "read":
            data = await m24x_iface.read(args.address, args.length)
            if data is None:
                raise GlasgowAppletError("memory did not acknowledge read")

            if args.file:
                args.file.write(data)
            else:
                print(data.hex())

        if args.operation == "write":
            if args.data is not None:
                data = args.data
            if args.file is not None:
                data = args.file.read()

            success = await m24x_iface.write(args.address, data)
            if not success:
                raise GlasgowAppletError("memory did not acknowledge write")

        if args.operation == "verify":
            if args.data is not None:
                golden_data = args.data
            if args.file is not None:
                golden_data = args.file.read()

            actual_data = await m24x_iface.read(args.address, len(golden_data))
            if actual_data is None:
                raise GlasgowAppletError("memory did not acknowledge read")
            if actual_data == golden_data:
                self.logger.info("verify PASS")
            else:
                raise GlasgowAppletError("verify FAIL")
