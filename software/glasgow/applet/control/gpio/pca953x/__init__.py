# Ref: http://www.ti.com/lit/ds/symlink/pca9534.pdf
# Accession: G00042

import logging
import asyncio
import argparse

from .... import *
from ....interface.i2c_initiator import I2CInitiatorApplet

# register definition
REG_INPUT      = 0x00
REG_OUTPUT     = 0x01
REG_INVERT     = 0x02
REG_DIRECTION  = 0x03     # bit set means input

# word width depends on the dut used
# different ports within the dut are flattend togehter into a word
# bitnos are linear on these words
WORD_WIDTH     = 8

class PCA953xError(GlasgowAppletError):
    pass

class PCA953xI2CInterface:
    def __init__(self, interface, logger, i2c_address):
        self.lower     = interface
        self._i2c_addr = i2c_address
        self._logger  = logger
        self._level   = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

    async def _read_reg(self, reg):
        await self.lower.write(self._i2c_addr, [reg])
        result = await self.lower.read(self._i2c_addr, 1)
        if result is None:
            raise PCA953xError("PCA953x did not acknowledge I2C read at address {:#07b}"
                              .format(self._i2c_addr))
        self._logger.log(self._level, "PCA953x: reg=%#02x read=%#02x", reg, result[0])
        return result[0]

    async def _write_reg(self, reg, data):
        self._logger.log(self._level, "PCA953x: reg=%#02x write=%#02x", reg, data)
        result = await self.lower.write(self._i2c_addr, [reg, data])
        if not result:
            raise PCA953xError("PCA953x did not acknowledge I2C write at address {:#07b}"
                              .format(self._i2c_addr))

    async def get_input_word(self):
        inputval = await self._read_reg(REG_INPUT)
        return inputval

    async def get_input_bit(self, bitno):
        inputval = await self.get_input_word()
        if inputval & (1 << bitno):
            return 1
        else:
            return 0

    async def get_dir_word(self):
        """a set bit means input"""
        dirval = await self._read_reg(REG_DIRECTION)
        return dirval

    async def get_dir_bit(self, bitno):
        """a set bit means input"""
        dirval = await self.get_dir_word()
        if dirval & (1 << bitno):
            return 1
        else:
            return 0

    async def set_dir_word(self, direction):
        """a set bit means input"""
        await self._write_reg(REG_DIRECTION, direction)

    async def set_dir_bit(self, bitno, direction):
        """direction 1 means input"""
        dirval = await self.get_dir_word()
        if direction:
            dirval |= (1 << bitno)
        else:
            dirval &= ((1 << bitno) ^ 0xFF)
        await self.set_dir_word(dirval)

    async def get_output_word(self):
        outval = await self._read_reg(REG_OUTPUT)
        return outval

    async def get_output_bit(self, bitno):
        outval = await self.get_output_word()
        if outval & (1 << bitno):
            return 1
        else:
            return 0

    async def set_output_word(self, output):
        await self._write_reg(REG_OUTPUT, output)

    async def set_output_bit(self, bitno, output):
        outval = await self.get_output_word()
        if output:
            outval |= (1 << bitno)
        else:
            outval &= ((1 << bitno) ^ 0xFF)
        await self.set_output_word(outval)


class ControlGPIOPCA953xApplet(I2CInitiatorApplet, name="control-gpio-pca953x"):
    help = "control I²C gpio extenders of the pca/tca 953x, 955x and compatible series"
    description = """
    Control I²C gpio extenders of the pca/tca 953x, 955x, tca6408, max731x and
    compatible series.
    To check other devices for compatibility, compare the register layout with the definition
    at the beginning of the applet source. Currently supports only devices with 4 and 8 io pins.
    """

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)

        def i2c_address(arg):
            return int(arg, 0)
        parser.add_argument(
            "--i2c-address", type=i2c_address, metavar="ADDR", default=0x20,
            help="I2C address of the ic (default: %(default)#02x)")

    async def run(self, device, args):
        i2c_iface = await self.run_lower(ControlGPIOPCA953xApplet, device, args)
        return PCA953xI2CInterface(i2c_iface, self.logger, args.i2c_address)

    @classmethod
    def add_interact_arguments(cls, parser):
        def auto_int(arg): return int(arg, 0)

        def arg_conv_range(conv, low, high):
            def arg(value):
                value = conv(value)
                if not (low <= value <= high):
                    raise argparse.ArgumentTypeError(
                        "{} is not between {} and {}".format(value, low, high))
                return value
            return arg

        def inout(arg):
            allowed_vals = {
                '0': 0,
                '1': 1,
                'i': 1,
                'o': 0,
                'in': 1,
                'out': 0
            }
            if arg not in allowed_vals:
                raise argparse.ArgumentTypeError(
                    "illegal value {}, must be 0|1|o|i|in|out".format(arg))
            return allowed_vals[arg]
        
        # TODO(py3.7): add required=True
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION")

        p_get_input_word = p_operation.add_parser(
            "get-input-word", help="read the input values from all pins")

        p_get_input_bit = p_operation.add_parser(
            "get-input-bit", help="read the input value from one pin/bit")

        p_get_input_bit.add_argument(
            "bitno", type=arg_conv_range(int, 0, WORD_WIDTH-1),
            help="bit number to read (bit numbers are linear over the whole dut)")

        p_get_dir_word = p_operation.add_parser(
            "get-dir-word", help="read the direction values from all pins, a set bit means input")

        p_get_dir_bit = p_operation.add_parser(
            "get-dir-bit", help="read the direction value from one pin/bit")

        p_get_dir_bit.add_argument(
            "bitno", type=arg_conv_range(int, 0, WORD_WIDTH-1),
            help="bit number to read (bit numbers are linear over the whole dut)")

        p_set_dir_word = p_operation.add_parser(
            "set-dir-word", help="set the direction for all pins")

        p_set_dir_word.add_argument(
            "dirword", type=auto_int,
            help="directions word, a set bit means input")

        p_set_dir_bit = p_operation.add_parser(
            "set-dir-bit", help="set the direction for one bit / pin")

        p_set_dir_bit.add_argument(
            "bitno", type=arg_conv_range(int, 0, WORD_WIDTH-1),
            help="bit number to set (bit numbers are linear over the whole dut)")

        p_set_dir_bit.add_argument(
            "direction", type=inout,
            help="direction: 0|1|o|i|in|out")

        p_get_output_word = p_operation.add_parser(
            "get-output-word", help="read the output values from all pins")

        p_get_output_bit = p_operation.add_parser(
            "get-output-bit", help="read the output value from one pin/bit")

        p_get_output_bit.add_argument(
            "bitno", type=arg_conv_range(int, 0, WORD_WIDTH-1),
            help="bit number to read (bit numbers are linear over the whole dut)")

        p_set_output_word = p_operation.add_parser(
            "set-output-word", help="set the output for all pins")

        p_set_output_word.add_argument(
            "outword", type=auto_int,
            help="output word")

        p_set_output_bit = p_operation.add_parser(
            "set-output-bit", help="set the output for one bit / pin")

        p_set_output_bit.add_argument(
            "bitno", type=arg_conv_range(int, 0, WORD_WIDTH-1),
            help="bit number to set (bit numbers are linear over the whole dut)")

        p_set_output_bit.add_argument(
            "output", type=arg_conv_range(int, 0, 1),
            help="output bit value")

    async def interact(self, device, args, pca953x):
        if args.operation == "get-input-word":
            inword = await pca953x.get_input_word()
            print("input pins : {inword:0{word_width}b} / 0x{inword:0{hex_word_width}x}"
                  .format(inword=inword,
                          word_width=WORD_WIDTH,
                          hex_word_width=-(-WORD_WIDTH // 4)        # always round up
                          ))

        if args.operation == "get-input-bit":
            inbit = await pca953x.get_input_bit(args.bitno)
            print("input pin {0:d} : {1:d}".format(args.bitno, inbit))

        if args.operation == "get-dir-word":
            inword = await pca953x.get_dir_word()
            print("pin directions : {inword:0{word_width}b} / 0x{inword:0{hex_word_width}x}"
                  .format(inword=inword,
                          word_width=WORD_WIDTH,
                          hex_word_width=-(-WORD_WIDTH // 4)        # always round up
                          ))

        if args.operation == "get-dir-bit":
            inbit = await pca953x.get_dir_bit(args.bitno)
            dirtext = 'in' if inbit == 1 else 'out'
            print("pin {0:d} direction : {1:d} / {2:s}".format(args.bitno, inbit, dirtext))

        if args.operation == "set-dir-word":
            await pca953x.set_dir_word(args.dirword)

        if args.operation == "set-dir-bit":
            await pca953x.set_dir_bit(args.bitno, args.direction)

        if args.operation == "get-output-word":
            outword = await pca953x.get_output_word()
            print("pin output : {outword:0{word_width}b} / 0x{outword:0{hex_word_width}x}"
                  .format(outword=outword,
                          word_width=WORD_WIDTH,
                          hex_word_width=-(-WORD_WIDTH // 4)        # always round up
                          ))

        if args.operation == "get-output-bit":
            outbit = await pca953x.get_output_bit(args.bitno)
            print("pin {0:d} output : {1:d}".format(args.bitno, outbit))

        if args.operation == "set-output-word":
            await pca953x.set_output_word(args.outword)

        if args.operation == "set-output-bit":
            await pca953x.set_output_bit(args.bitno, args.output)
