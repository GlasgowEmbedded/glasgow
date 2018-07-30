import functools
import itertools
import argparse
import re

from .. import AccessArguments


class SimulationArguments(AccessArguments):
    # First, define some state-less methods that just add arguments to an argparse instance.

    def _pin_number(self, arg):
        if not re.match(r"^[0-9]+$", arg):
            self._arg_error("{} is not a valid pin number", arg)
        return int(arg)

    def _add_pin_argument(self, parser, name, default, required):
        opt_name = "--pin-" + name.lower().replace("_", "-")
        parser.add_argument(
            opt_name, metavar="NUM", type=self._pin_number, default=default, required=required)

    def _pin_set(self, width, arg):
        if re.match(r"^[0-9]+:[0-9]+$", arg):
            first, last = map(int, arg.split(":"))
            numbers = list(range(first, last))
        elif re.match(r"^[0-9]+(,[0-9]+)*$", arg):
            numbers = list(map(int, arg.split(",")))
        else:
            self._arg_error("{} is not a valid pin number set", arg)
        if len(numbers) != width:
            self._arg_error("set {} includes {} pins, but {} pins are required",
                            arg, len(numbers), width)
        return numbers

    def _add_pin_set_argument(self, parser, name, width, default, required):
        help = "bind the applet I/O lines {!r} to pins SET".format(self._applet_name, name)
        if default is not None:
            help += " (default: %(default)s)"

        opt_name = "--pins-" + name.lower().replace("_", "-")
        parser.add_argument(
            opt_name, dest="pin_set_{}".format(name), metavar="SET",
            type=functools.partial(self._pin_set, width), default=default, required=required,
            help=help)

    # Second, define a stateful interface that has features like automatically assigning
    # default pin numbers.

    def __init__(self, applet_name):
        self._applet_name = applet_name
        self._pin_iter    = itertools.count()

    def add_build_arguments(self, parser):
        pass

    def add_pin_argument(self, parser, name, default=None, required=False):
        if default is True:
            default = str(next(self._pin_iter))
        self._add_pin_argument(parser, name, default, required)

    def add_pin_set_argument(self, parser, name, width, default=None, required=False):
        if default is True:
            default = ",".join([str(next(self._pin_iter)) for _ in range(width)])
        self._add_pin_set_argument(parser, name, width, default, required)

    def add_run_arguments(self, parser):
        pass
