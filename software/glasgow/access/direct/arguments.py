import functools
import re

from .. import AccessArguments


class DirectArguments(AccessArguments):
    # First, define some state-less methods that just add arguments to an argparse instance.

    def _port_spec(self, arg):
        if not re.match(r"^[A-Z]+$", arg):
            self._arg_error(f"{arg} is not a valid port specification")
        return arg

    def _add_port_argument(self, parser, default):
        help = "bind the applet to port SPEC"
        if default is not None:
            help += " (default: %(default)s)"

        parser.add_argument(
            "--port", dest="port_spec", metavar="SPEC", type=self._port_spec,
            default=default, help=help)

    def _add_port_voltage_arguments(self, parser, default):
        g_voltage = parser.add_mutually_exclusive_group(required=True)
        g_voltage.add_argument(
            "-V", "--voltage", metavar="VOLTS", type=float, nargs="?", default=default,
            help="set I/O port voltage explicitly")
        g_voltage.add_argument(
            "-M", "--mirror-voltage", action="store_true", default=False,
            help="sense and mirror I/O port voltage")
        g_voltage.add_argument(
            "--keep-voltage", action="store_true", default=False,
            help="do not change I/O port voltage")

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

    def __init__(self, applet_name, default_port, pin_count):
        self._applet_name  = applet_name
        self._default_port = default_port
        self._free_pins    = list(range(pin_count))

    @staticmethod
    def _get_free(free_list):
        if len(free_list) > 0:
            result = free_list[0]
            free_list.remove(result)
            return result

    def add_build_arguments(self, parser):
        self._add_port_argument(parser, self._default_port)

    def add_pin_argument(self, parser, name, default=None, required=False):
        if default is True:
            default = str(self._get_free(self._free_pins))
        self._add_pin_argument(parser, name, default, required)

    def add_pin_set_argument(self, parser, name, width, default=None, required=False):
        if isinstance(width, int):
            width = range(width, width + 1)
        if default is True and len(self._free_pins) >= width.start:
            default = ",".join([str(self._get_free(self._free_pins)) for _ in range(width.start)])
        elif isinstance(default, int) and len(self._free_pins) >= default:
            default = ",".join([str(self._get_free(self._free_pins)) for _ in range(default)])
        self._add_pin_set_argument(parser, name, width, default, required)

    def add_run_arguments(self, parser):
        self._add_port_voltage_arguments(parser, default=None)
