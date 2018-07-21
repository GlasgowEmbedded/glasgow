import re
import argparse


class GlasgowApplet:
    all_applets = {}

    def __init_subclass__(cls, name, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.all_applets[name] = cls

    @staticmethod
    def add_port_argument(parser, default=None, help=None):
        def port_spec(arg):
            if not re.match(r"^[A-Z]+$", arg):
                raise argparse.ArgumentTypeError("{} is not a valid port specification"
                                                 .format(arg))
            return arg

        if help is None:
            help = "bind the applet to port SPEC"
            if default is not None:
                help += " (default: %(default)s)"

        parser.add_argument("--port", metavar="SPEC", type=port_spec, default=default, help=help)

    @staticmethod
    def add_pin_argument(parser, name, default=None, help=None):
        def pin_number(arg):
            if not re.match(r"^[0-9]+$", arg):
                raise argparse.ArgumentTypeError("{} is not a valid pin number".format(arg))
            return int(arg)

        if help is None:
            help = "bind the applet I/O line " + name.upper() + " to pin NUM"
            if default is not None:
                help += " (default: %(default)s)"

        opt_name = "--pin-" + name.lower().replace("_", "-")
        parser.add_argument(opt_name, metavar="NUM", type=pin_number, default=default, help=help)

    @staticmethod
    def add_pins_argument(parser, name, width, default=None, help=None):
        def pin_set(arg):
            if re.match(r"^[0-9]+:[0-9]+$", arg):
                first, last = map(int, arg.split(":"))
                numbers = list(range(first, last))
            elif re.match(r"^[0-9]+(,[0-9]+)*$", arg):
                numbers = map(int, arg.split(","))
            else:
                raise argparse.ArgumentTypeError("{} is not a valid pin number set".format(arg))
            if len(numbers) != width:
                raise argparse.ArgumentTypeError(
                    "set {} includes {} pins, but {} pins are required"
                    .format(arg, len(numbers), width))
            return numbers

        if help is None:
            help = "bind the applet I/O lines " + name.upper() + " to pins SET"
            if default is not None:
                help += " (default: %(default)s)"

        opt_name = "--pins-" + name.lower().replace("_", "-")
        parser.add_argument(opt_name, metavar="SET", type=pin_set, default=default, help=help)

    @staticmethod
    def add_build_arguments(parser):
        pass

    @staticmethod
    def add_run_arguments(parser):
        pass

    def build(self, target):
        raise NotImplemented

    def run(self, device, args):
        raise NotImplemented


from .program_ice40 import ProgramICE40Applet
from .hd44780 import HD44780Applet
from .uart import UARTApplet
from .selftest import SelfTestApplet
