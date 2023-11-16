import functools
import itertools
import re

from .. import AccessArguments


class SimulationArguments(AccessArguments):
    # First, define some state-less methods that just add arguments to an argparse instance.

    def _mandatory_pin_number(self, arg):
        if not re.match(r"^[0-9]+$", arg):
            self._arg_error(f"{arg} is not a valid pin number")
        return int(arg)

    def _optional_pin_number(self, arg):
        if arg == "-":
            return None
        return self._mandatory_pin_number(arg)

    def _add_pin_argument(self, parser, name, default, required):
        help = f"bind the applet I/O line {name!r} to pin NUM"
        if default is not None:
            help += " (default: %(default)s)"

        if required:
            type = self._mandatory_pin_number
            if default is not None:
                required = False
        else:
            type = self._optional_pin_number

        opt_name = "--pin-" + name.lower().replace("_", "-")
        parser.add_argument(
            opt_name, metavar="NUM", type=type, default=default, required=required, help=help)

    def _pin_set(self, width, arg):
        if arg == "":
            numbers = []
        elif re.match(r"^[0-9]+:[0-9]+$", arg):
            first, last = map(int, arg.split(":"))
            numbers = list(range(first, last + 1))
        elif re.match(r"^[0-9]+(,[0-9]+)*$", arg):
            numbers = list(map(int, arg.split(",")))
        else:
            self._arg_error(f"{arg} is not a valid pin number set")
        if len(numbers) not in width:
            if len(width) == 1:
                width_desc = str(width[0])
            else:
                width_desc = f"{width.start}..{width.stop - 1}"
            self._arg_error(f"set {arg} includes {len(numbers)} pins, but {width_desc} pins are required")
        return numbers

    def _add_pin_set_argument(self, parser, name, width, default, required):
        help = f"bind the applet I/O lines {name!r} to pins SET"
        if default is not None:
            if default:
                help += " (default: %(default)s)"
            else:
                help += " (default is empty)"

        opt_name = "--pins-" + name.lower().replace("_", "-")
        parser.add_argument(
            opt_name, dest=f"pin_set_{name}", metavar="SET",
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
        if isinstance(width, int):
            width = range(width, width + 1)
        if default is True:
            default = ",".join([str(next(self._pin_iter)) for _ in range(width.start)])
        elif isinstance(default, int):
            default = ",".join([str(next(self._pin_iter)) for _ in range(default)])
        self._add_pin_set_argument(parser, name, width, default, required)

    def add_run_arguments(self, parser):
        pass
