import re
import os
import sys
import ast
import logging
import contextlib
import asyncio
import signal
import argparse
import textwrap
import platform
import unittest
import importlib.metadata
from datetime import datetime

from vcd import VCDWriter
from amaranth import UnusedElaboratable
from fx2 import FX2Config, FX2Device, FX2DeviceError, VID_CYPRESS, PID_FX2
from fx2.format import input_data, diff_data

from . import __version__
from .support.logging import *
from .support.asignal import *
from .support.plugin import PluginRequirementsUnmet, PluginLoadError
from .hardware.device import GlasgowDeviceError, GlasgowDevice, GlasgowDeviceConfig
from .hardware.device import VID_QIHW, PID_GLASGOW
from .hardware.toolchain import ToolchainNotFound
from .hardware.build_plan import GatewareBuildError
from .hardware.assembly import HardwareAssembly
from .legacy import DeprecatedTarget, DeprecatedMultiplexer
from .legacy import DeprecatedDevice, DeprecatedDemultiplexer
from .applet import *


# When running as `-m glasgow.cli`, `__name__` is `__main__`, and the real name
# can be retrieved from `__loader__.name`.
logger = logging.getLogger(__loader__.name)


class TextHelpFormatter(argparse.HelpFormatter):
    def __init__(self, prog):
        if "COLUMNS" in os.environ:
            columns = int(os.environ["COLUMNS"])
        else:
            try:
                columns, _ = os.get_terminal_size(sys.stderr.fileno())
            except OSError:
                columns = 80
        super().__init__(prog, width=columns, max_help_position=28)

    def _fill_text(self, text, width, indent):
        def filler(match):
            text = match[0]
            if text.startswith("::"):
                return text[2:]

            list_match = re.match(r"(\s*)(\*.+)", text, flags=re.S)
            if list_match:
                text = re.sub(r"(\S)\s+(\S)", r"\1 \2", list_match[2])
                text = textwrap.fill(text, width,
                                     initial_indent=indent + "  ",
                                     subsequent_indent=indent + "    ")
            else:
                text = textwrap.fill(text, width,
                                     initial_indent=indent,
                                     subsequent_indent=indent)

            text = text + (match[2] or "")
            text = re.sub(r"(\w-) (\w)", r"\1\2", text)
            return text

        text = textwrap.dedent(text).strip()
        text = text.replace("::\n\n", "::\n")
        return re.sub(r"((?!\n\n)(?!\n\s+(?:\*|\$|\d+\.)).)+(\n*)?", filler, text, flags=re.S)


def version_info():
    glasgow_version = __version__
    python_version = ".".join(map(str, sys.version_info[:3]))
    python_implementation = platform.python_implementation()
    python_platform = platform.platform()
    freedesktop_os_name = ""
    try:
        freedesktop_os_release = platform.freedesktop_os_release()
        if "PRETTY_NAME" in freedesktop_os_release:
            freedesktop_os_name = f" {freedesktop_os_release['PRETTY_NAME']}"
    except OSError:
        pass
    return (
        f"Glasgow {glasgow_version} "
        f"({python_implementation} {python_version} on {python_platform}{freedesktop_os_name})"
    )


def create_argparser():
    parser = argparse.ArgumentParser(formatter_class=TextHelpFormatter, fromfile_prefix_chars="@")

    parser.add_argument(
        "-V", "--version", action="version", version=version_info(),
        help="show version and exit")
    parser.add_argument(
        "-v", "--verbose", default=0, action="count",
        help="increase logging verbosity")
    parser.add_argument(
        "-q", "--quiet", default=0, action="count",
        help="decrease logging verbosity")
    parser.add_argument(
        "-L", "--log-file", metavar="FILE", type=argparse.FileType("w"),
        help="save log messages at highest verbosity to FILE")
    parser.add_argument(
        "-F", "--filter-log", metavar="FILTER", type=str, action="append",
        help="raise TRACE log messages to INFO if they begin with 'FILTER: '")
    parser.add_argument(
        "--no-shorten", default=False, action="store_true",
        help="do not shorten sequences in logs")
    parser.add_argument(
        "--statistics", dest="show_statistics", default=False, action="store_true",
        help="display performance counters before exiting")

    return parser


def get_argparser():
    class LazyParser(argparse.ArgumentParser):
        """This is a lazy ArgumentParser that runs any added build_func(s) just before arguments
        are parsed"""
        def __init__(self, *args, **kwargs):
            self.build_funcs = []
            super().__init__(*args, **kwargs)

        def add_build_func(self, build_func):
            self.build_funcs.append(build_func)

        def build(self):
            for build_func in self.build_funcs:
                build_func()
            self.build_funcs.clear()

        def parse_args(self, args=None, namespace=None):
            self.build()
            return super().parse_args(args, namespace)

        def parse_known_args(self, args=None, namespace=None):
            self.build()
            return super().parse_known_args(args, namespace)

        def parse_intermixed_args(self, args=None, namespace=None):
            self.build()
            return super().parse_intermixed_args(args, namespace)

        def parse_known_intermixed_args(self, args=None, namespace=None):
            self.build()
            return super().parse_known_intermixed_args(args, namespace)

    def add_subparsers(parser, **kwargs):
        if isinstance(parser, argparse._MutuallyExclusiveGroup):
            container = parser._container
            if kwargs.get('prog') is None:
                formatter = container._get_formatter()
                formatter.add_usage(container.usage, [], [], '')
                kwargs['prog'] = formatter.format_help().strip()

            parsers_class = parser._pop_action_class(kwargs, 'parsers')
            kwargs["parser_class"] = type(container)
            subparsers = argparse._SubParsersAction(option_strings=[], **kwargs)
            parser._add_action(subparsers)
        else:
            subparsers = parser.add_subparsers(**kwargs)
        return subparsers

    def add_stub_parser(subparsers, handle, metadata):
        # fantastically cursed
        p_stub = subparsers.add_parser(
            handle, help=metadata.synopsis, description=metadata.description,
            formatter_class=TextHelpFormatter, prefix_chars='\0', add_help=False)
        p_stub.add_argument("args", nargs="...", help=argparse.SUPPRESS)
        p_stub.add_argument("help", nargs="?", default=p_stub.format_help())

    def add_applet_arg(parser, mode, *, required=False):
        subparsers = add_subparsers(
            parser, dest="applet", metavar="APPLET", required=required, parser_class=LazyParser)

        for handle, metadata in GlasgowAppletMetadata.all().items():
            if not metadata.loadable:
                add_stub_parser(subparsers, handle, metadata)
                continue
            applet_cls = metadata.load()

            # Don't do `.tests() is None`, as this has the overhead of importing the tests module
            # (about 5ms per applet, which adds up). Instead, check if the function was overridden,
            # as it's pointless to override it just to return `None`.
            if mode == "test" and applet_cls.tests is GlasgowApplet.tests:
                continue

            help        = applet_cls.help
            description = applet_cls.description
            if applet_cls.preview:
                help += " (PREVIEW QUALITY APPLET)"
                description = "    This applet is PREVIEW QUALITY and may CORRUPT DATA or " \
                              "have missing features. Use at your own risk.\n" + description
            if applet_cls.required_revision > "A0":
                help += f" (rev{applet_cls.required_revision}+)"
                description += "\n    This applet requires Glasgow rev{} or later." \
                               .format(applet_cls.required_revision)

            p_applet = subparsers.add_parser(
                handle, help=help, description=description,
                formatter_class=TextHelpFormatter)

            def p_applet_build_factory(p_applet, handle, applet_cls, mode):
                # factory function for proper closure
                def p_applet_build():
                    if mode == "test":
                        p_applet.add_argument(
                            "tests", metavar="TEST", nargs="*",
                            help="test cases to run")

                    if mode in ("build", "interact", "repl", "script"):
                        access_args = GlasgowAppletArguments(applet_name=handle)
                        if mode in ("interact", "repl", "script"):
                            g_applet_build = p_applet.add_argument_group("build arguments")
                            applet_cls.add_build_arguments(g_applet_build, access_args)
                            if issubclass(applet_cls, GlasgowAppletV2):
                                g_applet_setup = p_applet.add_argument_group("setup arguments")
                                applet_cls.add_setup_arguments(g_applet_setup)
                                if mode == "interact":
                                    applet_cls.add_run_arguments(p_applet)
                            else:
                                g_applet_run = p_applet.add_argument_group("run arguments")
                                applet_cls.add_run_arguments(g_applet_run, access_args)
                                if mode == "interact":
                                    applet_cls.add_interact_arguments(p_applet)
                            if mode == "repl":
                                # FIXME: same as above
                                applet_cls.add_repl_arguments(p_applet)
                        if mode == "build":
                            applet_cls.add_build_arguments(p_applet, access_args)

                    if mode == "tool":
                        applet_cls.tool_cls.add_arguments(p_applet)

                    if mode in ("repl", "script"):
                        # this will absorb all arguments from the '--' onwards (inclusive), make sure it's
                        # always last... the '--' item that ends up at the front is removed before the list
                        # is passed to the repo / script environment
                        p_applet.add_argument('script_args', nargs=argparse.REMAINDER)
                return p_applet_build
            p_applet.add_build_func(p_applet_build_factory(p_applet, handle, applet_cls, mode))

    def add_applet_tool_arg(parser, *, required=False):
        subparsers = add_subparsers(
            parser, dest="tool", metavar="TOOL", required=required, parser_class=LazyParser)

        def p_tool_build_factory(p_tool, tool_cls):
            def p_tool_build():
                tool_cls.add_arguments(p_tool)
            return p_tool_build

        for handle, metadata in GlasgowAppletToolMetadata.all().items():
            if not metadata.loadable:
                add_stub_parser(subparsers, handle, metadata)
                continue

            tool_cls = metadata.load()
            p_tool = subparsers.add_parser(
                handle, help=tool_cls.help, description=tool_cls.description,
                formatter_class=TextHelpFormatter)
            p_tool.add_build_func(p_tool_build_factory(p_tool, tool_cls))

    parser = create_argparser()

    def revision(arg):
        revisions = ["A0", "B0", "C0", "C1", "C2", "C3"]
        if arg in revisions:
            return arg
        else:
            raise argparse.ArgumentTypeError("{} is not a valid revision (should be one of: {})"
                                             .format(arg, ", ".join(revisions)))

    def serial(arg):
        if re.match(r"^[A-C][0-9]-\d{8}T\d{6}Z$", arg):
            return arg
        else:
            raise argparse.ArgumentTypeError(f"{arg} is not a valid serial number")

    parser.add_argument(
        "--serial", metavar="SERIAL", type=serial,
        help="use device with serial number SERIAL")

    subparsers = parser.add_subparsers(dest="action", metavar="COMMAND", parser_class=LazyParser)
    subparsers.required = True

    def add_ports_arg(parser):
        parser.add_argument(
            "ports", metavar="PORTS", type=str, nargs="?", default="AB",
            help="I/O port set (one or more of: A B, default: all)")

    def add_voltage_arg(parser, help):
        parser.add_argument(
            "voltage", metavar="VOLTS", type=float, nargs="?", default=None,
            help=f"{help} (range: 1.8-5.0)")

    p_voltage = subparsers.add_parser(
        "voltage", formatter_class=TextHelpFormatter,
        help="query or set I/O port voltage")
    add_ports_arg(p_voltage)
    add_voltage_arg(p_voltage,
        help="I/O port voltage")
    p_voltage.add_argument(
        "--tolerance", metavar="PCT", type=float, default=10.0,
        help="raise alert if measured voltage deviates by more than ±PCT%% (default: %(default)s)")
    p_voltage.add_argument(
        "--alert", dest="set_alert", default=False, action="store_true",
        help="raise an alert if Vsense is out of range of Vio")

    p_safe = subparsers.add_parser(
        "safe", formatter_class=TextHelpFormatter,
        help="turn off all I/O port voltage regulators and drivers")

    p_voltage_limit = subparsers.add_parser(
        "voltage-limit", formatter_class=TextHelpFormatter,
        help="limit I/O port voltage as a safety mechanism")
    add_ports_arg(p_voltage_limit)
    add_voltage_arg(p_voltage_limit,
        help="maximum allowed I/O port voltage")

    def add_run_args(parser):
        g_run_bitstream = parser.add_mutually_exclusive_group()
        g_run_bitstream.add_argument(
            "--reload", default=False, action="store_true",
            help="(advanced) reload bitstream even if an identical one is already loaded")
        g_run_bitstream.add_argument(
            "--prebuilt", default=False, action="store_true",
            help="(advanced) load prebuilt applet bitstream from ./<applet-name.bin>")
        g_run_bitstream.add_argument(
            "--prebuilt-at", dest="prebuilt_at", metavar="BITSTREAM-FILE",
            type=argparse.FileType("rb"),
            help="(advanced) load prebuilt applet bitstream from BITSTREAM-FILE")

    p_run = subparsers.add_parser(
        "run", formatter_class=TextHelpFormatter,
        help="run an applet and interact through its command-line interface")
    add_run_args(p_run)
    p_run.add_build_func(lambda: add_applet_arg(p_run, mode="interact", required=True))

    p_repl = subparsers.add_parser(
        "repl", formatter_class=TextHelpFormatter,
        help="run an applet and open a REPL to use its programming interface")
    add_run_args(p_repl)
    p_repl.add_build_func(lambda: add_applet_arg(p_repl, mode="repl", required=True))

    p_script = subparsers.add_parser(
        "script", formatter_class=TextHelpFormatter,
        help="run an applet and execute a script against its programming interface")
    g_script_source = p_script.add_mutually_exclusive_group(required=True)
    g_script_source.add_argument(
        "script_file", metavar="FILENAME", type=argparse.FileType("r"), nargs="?",
        help="run Python script FILENAME in the applet context")
    g_script_source.add_argument(
        "-c", metavar="COMMAND", dest="script_cmd", type=str,
        help="run Python statement COMMAND in the applet context")
    add_run_args(p_script)
    p_script.add_build_func(lambda: add_applet_arg(p_script, mode="script", required=True))

    p_multi = subparsers.add_parser(
        "multi", formatter_class=TextHelpFormatter,
        help="(experimental) run multiple applets simultaneously")
    p_multi.add_argument(
        "rest", metavar="ARGS", nargs=argparse.REMAINDER,
        help="applet name and arguments for each applet, separated by ++ arguments")

    p_tool = subparsers.add_parser(
        "tool", formatter_class=TextHelpFormatter,
        help="run an offline tool provided with an applet")
    p_tool.add_build_func(lambda: add_applet_tool_arg(p_tool, required=True))

    p_flash = subparsers.add_parser(
        "flash", formatter_class=TextHelpFormatter,
        help="program FX2 firmware or applet bitstream into EEPROM")

    g_flash_firmware = p_flash.add_mutually_exclusive_group()
    g_flash_firmware.add_argument(
        "--firmware", metavar="FILENAME", type=argparse.FileType("rb"),
        help="(advanced) read firmware from the specified file")
    g_flash_firmware.add_argument(
        "--remove-firmware", default=False, action="store_true",
        help="remove any firmware present")

    g_flash_bitstream = p_flash.add_mutually_exclusive_group()
    g_flash_bitstream.add_argument(
        "--bitstream", metavar="FILENAME", type=argparse.FileType("rb"),
        help="(advanced) read bitstream from the specified file")
    g_flash_bitstream.add_argument(
        "--remove-bitstream", default=False, action="store_true",
        help="remove any bitstream present")
    p_flash.add_build_func(lambda: add_applet_arg(g_flash_bitstream, mode="build"))

    p_build = subparsers.add_parser(
        "build", formatter_class=TextHelpFormatter,
        help="(advanced) build applet logic and save it as a file")
    p_build.add_argument(
        "--rev", metavar="REVISION", type=revision, required=True,
        help="board revision")
    p_build.add_argument(
        "-t", "--type", metavar="TYPE", type=str,
        choices=["zip", "archive", "il", "rtlil", "bin", "bitstream"], default="bitstream",
        help="artifact to build (one of: archive rtlil bitstream, default: %(default)s)")
    p_build.add_argument(
        "-f", "--filename", metavar="FILENAME", type=str,
        help="file to save artifact to (default: <applet-name>.{zip,il,bin})")
    p_build.add_build_func(lambda: add_applet_arg(p_build, mode="build", required=True))

    p_test = subparsers.add_parser(
        "test", formatter_class=TextHelpFormatter,
        help="(advanced) test applet logic without target hardware")
    p_test.add_build_func(lambda: add_applet_arg(p_test, mode="test", required=True))

    def factory_serial(arg):
        if re.match(r"^\d{8}T\d{6}Z$", arg):
            return arg
        else:
            raise argparse.ArgumentTypeError(f"{arg} is not a valid serial number")

    def factory_manufacturer(arg):
        if len(arg) <= 23:
            return arg
        else:
            raise argparse.ArgumentTypeError(f"{arg} is too long for the manufacturer field")

    p_factory = subparsers.add_parser(
        "factory", formatter_class=TextHelpFormatter,
        help="(advanced) initial device programming")
    p_factory.add_argument(
        "--reinitialize", default=False, action="store_true",
        help="(DANGEROUS) find an already programmed device and reinitialize it")
    p_factory.add_argument(
        "--rev", metavar="REVISION", dest="factory_rev", type=revision, required=True,
        help="board revision")
    p_factory.add_argument(
        "--serial", metavar="SERIAL", dest="factory_serial", type=factory_serial,
        default=datetime.now().strftime("%Y%m%dT%H%M%SZ"),
        help="serial number in ISO 8601 format (if not specified: %(default)s)")
    p_factory.add_argument(
        "--manufacturer", metavar="MFG", dest="factory_manufacturer", type=factory_manufacturer,
        default="", # the default is implemented in the firmware
        help="manufacturer string (if not specified: whitequark research)")
    p_factory.add_argument(
        "--using-modified-design-files", dest="factory_modified_design", choices=("yes", "no"),
        required=True, # must be specified explicitly
        help="whether the design files used to manufacture the PCBA were modified from the ones "
             "published in the https://github.com/GlasgowEmbedded/glasgow/ repository")

    p_list = subparsers.add_parser(
        "list", formatter_class=TextHelpFormatter,
        help="list devices connected to the system")

    return parser


# The name of this function appears in Verilog output, so keep it tidy.
def _applet(assembly, args):
    try:
        applet_cls = GlasgowAppletMetadata.get(args.applet).load()
        match applet := applet_cls(assembly):
            case GlasgowAppletV2():
                applet.build(args)
                return applet, None
            case GlasgowApplet():
                target = DeprecatedTarget(assembly)
                with assembly.add_applet(applet):
                    applet.build(target, args)
                return applet, target
    except GlasgowAppletError as e:
        applet.logger.error(e)
        logger.error("failed to build applet %r", args.applet)
        raise SystemExit()


class TerminalFormatter(logging.Formatter):
    DEFAULT_COLORS = {
        "TRACE"   : "\033[0m",
        "DEBUG"   : "\033[36m",
        "INFO"    : "\033[1m",
        "WARNING" : "\033[1;33m",
        "ERROR"   : "\033[1;31m",
        "CRITICAL": "\033[1;41m",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.colors = dict(self.DEFAULT_COLORS)
        for color_override in os.getenv("GLASGOW_COLORS", "").split(":"):
            if color_override:
                level, color = color_override.split("=", 2)
                self.colors[level] = f"\033[{color}m"

    def format(self, record):
        color = self.colors.get(record.levelname, "")
        # glasgow.applet.foo → g.applet.foo
        record.name = record.name.replace("glasgow.", "g.")
        # applet.memory._25x → applet.memory.25x
        record.name = record.name.replace("._", ".")
        return f"{color}{super().format(record)}\033[0m"


class SubjectFilter:
    def __init__(self, level, subjects):
        self.level    = level
        self.subjects = subjects or ()

    def filter(self, record):
        levelno = record.levelno
        for subject in self.subjects:
            if isinstance(record.msg, str) and record.msg.startswith(subject + ": "):
                levelno = logging.INFO
        return levelno >= self.level


def create_logger():
    root_logger = logging.getLogger()

    term_formatter_args = {"style": "{",
        "fmt": "{levelname[0]:s}: {name:s}: {message:s}"}
    term_handler = logging.StreamHandler()
    if sys.stderr.isatty() and sys.platform != 'win32':
        term_handler.setFormatter(TerminalFormatter(**term_formatter_args))
    else:
        term_handler.setFormatter(logging.Formatter(**term_formatter_args))
    root_logger.addHandler(term_handler)
    return term_handler


def configure_logger(args, term_handler):
    root_logger = logging.getLogger()

    file_formatter_args = {"style": "{",
        "fmt": "[{asctime:s}] {levelname:s}: {name:s}: {message:s}"}
    file_handler = None
    if args.log_file:
        file_handler = logging.StreamHandler(args.log_file)
        file_handler.setFormatter(logging.Formatter(**file_formatter_args))
        root_logger.addHandler(file_handler)

    level = logging.INFO + args.quiet * 10 - args.verbose * 10
    if level < 0 or args.no_shorten:
        dump_hex.limit = dump_bin.limit = dump_seq.limit = dump_mapseq.limit = None

    if args.log_file or args.filter_log:
        term_handler.addFilter(SubjectFilter(level, args.filter_log))
        root_logger.setLevel(logging.TRACE)
    else:
        # By setting the log level on the root logger, we avoid creating LogRecords in the first
        # place instead of filtering them later; we have a *lot* of logging, so this is much
        # more efficient.
        root_logger.setLevel(level)


@contextlib.contextmanager
def gc_freeze():
    if sys.implementation.name == "cpython":
        # Run a full garbage collection, then move all remaining objects into the permanent
        # generation. This greatly reduces the amount of work the garbage collector has to do in a
        # full generation 2 collection while running the applet task.
        import gc
        gc.collect()
        gc.freeze()
        yield
        gc.unfreeze()
    else:
        yield


class SIGINTCaught(Exception):
    """This exception is necessary because asyncio recognizes both SystemExit and
    KeyboardInterrupt and treats them specially in a way we don't need."""


async def wait_for_sigint():
    await wait_for_signal(signal.SIGINT)
    logger.debug("Ctrl+C pressed, terminating")
    raise SIGINTCaught


async def main():
    # Handle log messages emitted during construction of the argument parser (e.g. by the plugin
    # subsystem).
    term_handler = create_logger()

    args = get_argparser().parse_args()
    configure_logger(args, term_handler)

    device = None
    try:
        if args.action not in ("build", "test", "tool", "factory", "list"):
            device = GlasgowDevice(args.serial)
            assembly = HardwareAssembly(device=device)

        if args.action == "voltage":
            if args.voltage is not None:
                await device.reset_alert(args.ports)
                await device.poll_alert() # clear any remaining alerts
                try:
                    await device.set_voltage(args.ports, args.voltage)
                except:
                    await device.set_voltage(args.ports, 0.0)
                    raise
                if args.set_alert and args.voltage != 0.0:
                    await asyncio.sleep(0.050) # let the output capacitor discharge a bit
                    await device.set_alert_tolerance(args.ports, args.voltage,
                                                     args.tolerance / 100)

            print("Port\tVio\tVlimit\tVsense\tVsense(range)")
            alerts = await device.poll_alert()
            for port in args.ports:
                vio    = await device.get_voltage(port)
                vlimit = await device.get_voltage_limit(port)
                vsense = await device.measure_voltage(port)
                alert  = await device.get_alert(port)
                notice = ""
                if port in alerts:
                    notice += " (ALERT)"
                print("{}\t{:.2}\t{:.2}\t{:.3}\t{:.2}-{:.2}\t{}"
                      .format(port, vio, vlimit, vsense, alert[0], alert[1], notice))

        if args.action == "safe":
            await device.reset_alert("AB")
            await device.set_voltage("AB", 0.0)
            await device.poll_alert() # clear any remaining alerts
            logger.info("all ports safe")

        if args.action == "voltage-limit":
            if args.voltage is not None:
                await device.set_voltage_limit(args.ports, args.voltage)

            print("Port\tVio\tVlimit")
            for port in args.ports:
                vio    = await device.get_voltage(port)
                vlimit = await device.get_voltage_limit(port)
                print("{}\t{:.2}\t{:.2}"
                      .format(port, vio, vlimit))

        if args.action in ("run", "repl", "script"):
            applet, target = _applet(assembly, args)

            if args.prebuilt or args.prebuilt_at:
                bitstream_file = args.prebuilt_at or open(f"{args.applet}.bin", "rb")
                with bitstream_file:
                    await assembly.start(device, _bitstream_file=bitstream_file)
            else:
                await assembly.start(device, reload_bitstream=args.reload)

            if target:
                device = DeprecatedDevice(target)
                device.demultiplexer = DeprecatedDemultiplexer(device, target.multiplexer.pipe_count)

            async def run_applet():
                if args.action in ("repl", "script"):
                    if len(args.script_args) > 0 and args.script_args[0] == "--":
                        args.script_args = args.script_args[1:]

                logger.info("running handler for applet %r", args.applet)
                try:
                    match applet:
                        case GlasgowAppletV2():
                            await applet.setup(args)
                            if args.action == "run":
                                return await applet.run(args)
                            elif args.action == "repl":
                                await applet.repl(args)
                            elif args.action == "script":
                                if args.script_file:
                                    script_code = args.script_file.read()
                                    script_name = args.script_file.name
                                else:
                                    script_code = args.script_cmd
                                    script_name = "<command>"
                                code = compile(script_code, filename=script_name, mode="exec",
                                    flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
                                await applet.script(args, code)

                        case GlasgowApplet():
                            iface = await applet.run(device, args)
                            if args.action == "run":
                                return await applet.interact(device, args, iface)
                            elif args.action == "repl":
                                await applet.repl(device, args, iface)
                            elif args.action == "script":
                                if args.script_file:
                                    code = compile(args.script_file.read(),
                                        filename=args.script_file.name,
                                        mode="exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
                                else:
                                    code = compile(args.script_cmd,
                                        filename="<command>",
                                        mode="exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
                                future = eval(code, {"iface":iface, "device":device, "args":args})
                                if future is not None:
                                    await future

                except SystemExit as e:
                    return e.code
                except GlasgowAppletError as e:
                    applet.logger.error(str(e))
                    return 1
                except asyncio.CancelledError:
                    return 130 # 128 + SIGINT

            try:
                with gc_freeze():
                    async with asyncio.TaskGroup() as group:
                        applet_task = group.create_task(run_applet())

                        if args.action != "repl":
                            sigint_task = group.create_task(wait_for_sigint())
                            await asyncio.wait([applet_task])
                            sigint_task.cancel()
            except* SIGINTCaught:
                pass

            await assembly.stop()
            if args.show_statistics:
                assembly.statistics()

            return applet_task.result()

        if args.action == "multi":
            assembly = HardwareAssembly(device=device)
            applets = []
            while args.rest:
                try:
                    split_at = args.rest.index("++")
                except ValueError:
                    split_at = len(args.rest)
                applet_cmdline, args.rest = args.rest[:split_at], args.rest[split_at + 1:]
                if len(applet_cmdline) < 1:
                    logger.error(f"no applet name specified for applet #{len(applets) + 1}")
                    return

                applet_name, *applet_args = applet_cmdline
                try:
                    applet_parser = argparse.ArgumentParser()
                    def argparse_exit(self, status=0, message=None):
                        if status: raise
                    applet_parser.exit = argparse_exit

                    applet_cls = GlasgowAppletMetadata.get(applet_name).load()
                    if not issubclass(applet_cls, GlasgowAppletV2):
                        logger.error(f"applet {applet_name!r} must be migrated to V2 API first")
                        return 1

                    applet_cls.add_build_arguments(applet_parser,
                        GlasgowAppletArguments(applet_name))
                    applet_cls.add_setup_arguments(applet_parser)
                    applet_cls.add_run_arguments(applet_parser)
                    applet_parsed_args = applet_parser.parse_args(applet_args)

                    applet = applet_cls(assembly)
                    applet.build(applet_parsed_args)
                    applets.append((applet, applet_name, applet_parsed_args))

                except argparse.ArgumentError as exn:
                    logger.error(f"error for applet #{len(applets) + 1} {applet_name!r}:")
                    logger.error("%s", exn)
                    return 1

                except:
                    logger.error(f"error building applet #{len(applets) + 1} {applet_name!r}:")
                    raise

            async with assembly:
                for index, (applet, applet_name, applet_parsed_args) in enumerate(applets):
                    try:
                        await applet.setup(applet_parsed_args)
                    except:
                        logger.error(f"error setting up applet #{index + 1} {applet_name!r}:")
                        raise

                try:
                    async def applet_task(applet, applet_parsed_args):
                        await applet.run(applet_parsed_args)
                        logger.info(f"applet #{index + 1} {applet_name!r} has finished running")

                    with gc_freeze():
                        async with asyncio.TaskGroup() as group:
                            applet_tasks = []
                            for applet, applet_name, applet_parsed_args in applets:
                                applet_tasks.append(group.create_task(
                                    applet_task(applet, applet_parsed_args),
                                    name=f"{applet_name}#{index + 1}"
                                ))

                            sigint_task = group.create_task(wait_for_sigint())
                            await asyncio.wait(applet_tasks)
                            sigint_task.cancel()

                except* SIGINTCaught:
                    pass

        if args.action == "tool":
            tool = GlasgowAppletToolMetadata.get(args.tool).load()()
            try:
                return await tool.run(args)
            except GlasgowAppletError as e:
                tool.logger.error(e)
                return 1

        if args.action == "flash":
            logger.info("reading device configuration")
            header = await device.read_eeprom("fx2", 0, 8 + 4 + GlasgowDeviceConfig.size)
            header[0] = 0xC2 # see below

            fx2_config = FX2Config.decode(header, partial=True)
            if (len(fx2_config.firmware) != 1 or
                    fx2_config.firmware[0][0] != 0x4000 - GlasgowDeviceConfig.size or
                    len(fx2_config.firmware[0][1]) != GlasgowDeviceConfig.size):
                raise SystemExit("Unrecognized or corrupted configuration block")
            glasgow_config = GlasgowDeviceConfig.decode(fx2_config.firmware[0][1])

            logger.info("device has serial %s-%s",
                        glasgow_config.revision, glasgow_config.serial)
            if fx2_config.disconnect:
                logger.info("device has flashed firmware")
            else:
                logger.info("device does not have flashed firmware")
            if glasgow_config.bitstream_size:
                logger.info("device has flashed bitstream ID %s",
                            glasgow_config.bitstream_id.hex())
            else:
                logger.info("device does not have flashed bitstream")

            new_bitstream = b""
            if args.remove_bitstream:
                logger.info("removing bitstream")
                glasgow_config.bitstream_size = 0
                glasgow_config.bitstream_id   = b"\x00"*16
            elif args.bitstream:
                logger.info("using bitstream from %s", args.bitstream.name)
                with args.bitstream as f:
                    new_bitstream_id = f.read(16)
                    new_bitstream    = f.read()
                    glasgow_config.bitstream_size = len(new_bitstream)
                    glasgow_config.bitstream_id   = new_bitstream_id
            elif args.applet:
                logger.info("generating bitstream for applet %s", args.applet)
                assembly = HardwareAssembly(revision=args.rev)
                applet, _multiplexer = _applet(assembly, args)
                plan = assembly.artifact()
                new_bitstream_id = plan.bitstream_id
                new_bitstream    = plan.get_bitstream()

                # We always build and reflash the bitstream in case the one currently
                # in EEPROM is corrupted. If we only compared the ID, there would be
                # no easy way to recover from that case. There's also no point in
                # storing the bitstream hash (as opposed to Verilog hash) in the ID,
                # as building the bitstream takes much longer than flashing it.
                logger.info("generated bitstream ID %s", new_bitstream_id.hex())
                glasgow_config.bitstream_size = len(new_bitstream)
                glasgow_config.bitstream_id   = new_bitstream_id

            fx2_config.firmware[0] = (0x4000 - GlasgowDeviceConfig.size, glasgow_config.encode())

            if args.remove_firmware:
                logger.info("removing firmware")
                fx2_config.disconnect = False
                new_image = fx2_config.encode()
                # Let FX2 hardware enumerate. This won't load the configuration block
                # into memory automatically, but the firmware has code that does that
                # if it detects a C0 load.
                new_image[0] = 0xC0
            else:
                if args.firmware:
                    logger.warning("using custom firmware from %s", args.firmware.name)
                    with args.firmware as f:
                        for (addr, chunk) in input_data(f, fmt="ihex"):
                            fx2_config.append(addr, chunk)
                else:
                    logger.info("using built-in firmware")
                    for (addr, chunk) in GlasgowDevice.firmware_data():
                        fx2_config.append(addr, chunk)
                fx2_config.disconnect = True
                new_image = fx2_config.encode()

            if new_bitstream:
                logger.info("programming bitstream")
                old_bitstream = await device.read_eeprom("ice", 0, len(new_bitstream))
                if old_bitstream != new_bitstream:
                    for (addr, chunk) in diff_data(old_bitstream, new_bitstream):
                        await device.write_eeprom("ice", addr, chunk)

                    logger.info("verifying bitstream")
                    if await device.read_eeprom("ice", 0, len(new_bitstream)) != new_bitstream:
                        logger.critical("bitstream programming failed")
                        return 1
                else:
                    logger.info("bitstream identical")

            logger.info("programming configuration and firmware")
            old_image = await device.read_eeprom("fx2", 0, len(new_image))
            if old_image != new_image:
                for (addr, chunk) in diff_data(old_image, new_image):
                    await device.write_eeprom("fx2", addr, chunk)

                logger.info("verifying configuration and firmware")
                if await device.read_eeprom("fx2", 0, len(new_image)) != new_image:
                    logger.critical("configuration/firmware programming failed")
                    return 1

                logger.warning("power cycle the device to apply changes")
            else:
                logger.info("configuration and firmware identical")

        if args.action == "build":
            assembly = HardwareAssembly(revision=args.rev)
            applet, target = _applet(assembly, args)
            plan = assembly.artifact()
            if args.type in ("il", "rtlil"):
                logger.info("generating RTLIL for applet %r", args.applet)
                with open(args.filename or args.applet + ".il", "w") as f:
                    f.write(plan.rtlil)
            if args.type in ("zip", "archive"):
                logger.info("generating archive for applet %r", args.applet)
                plan.archive(args.filename or args.applet + ".zip")
            if args.type in ("bin", "bitstream"):
                logger.info("generating bitstream for applet %r", args.applet)
                with open(args.filename or args.applet + ".bin", "wb") as f:
                    f.write(plan.bitstream_id)
                    f.write(plan.get_bitstream())

        if args.action == "test":
            logger.info("testing applet %r", args.applet)
            applet_cls = GlasgowAppletMetadata.get(args.applet).load()
            loader = unittest.TestLoader()
            stream = unittest.runner._WritelnDecorator(sys.stderr)
            result = unittest.TextTestResult(stream=stream, descriptions=True, verbosity=2)
            result.failfast = True
            def startTest(test):
                unittest.TextTestResult.startTest(result, test)
                result.stream.write("\n")
            result.startTest = startTest
            if args.tests == []:
                suite = loader.loadTestsFromTestCase(applet_cls.tests())
                suite.run(result)
            else:
                for test in args.tests:
                    suite = loader.loadTestsFromName(test, module=applet_cls.tests())
                    suite.run(result)
            if not result.wasSuccessful():
                for _, traceback in result.errors + result.failures:
                    print(traceback, end="", file=sys.stderr)
                return 1

        if args.action == "factory":
            if args.serial:
                logger.error(f"--serial is not supported for factory flashing")
                return 1

            device_id = GlasgowDeviceConfig.encode_revision(args.factory_rev)
            glasgow_config = GlasgowDeviceConfig(args.factory_rev, args.factory_serial,
                                           manufacturer=args.factory_manufacturer,
                                           modified_design=(args.factory_modified_design != "no"))
            firmware_data = GlasgowDevice.firmware_data()

            if args.reinitialize:
                vid, pid = VID_QIHW, PID_GLASGOW
            else:
                vid, pid = VID_CYPRESS, PID_FX2
            try:
                fx2_device = FX2Device(vid, pid)
            except FX2DeviceError:
                logger.error(f"device {vid:#06x}:{pid:#06x} not found")
                return 1

            with importlib.resources.files("fx2").joinpath("boot-cypress.ihex").open("r") as f:
                fx2_device.load_ram(input_data(f, fmt="ihex"))

            fx2_config = FX2Config(vendor_id=VID_QIHW, product_id=PID_GLASGOW,
                                   device_id=device_id, i2c_400khz=True, disconnect=True)
            fx2_config.append(0x4000 - glasgow_config.size, glasgow_config.encode())
            for (addr, chunk) in firmware_data:
                fx2_config.append(addr, chunk)
            image = fx2_config.encode()

            logger.info("programming device configuration and firmware")
            fx2_device.write_boot_eeprom(0, image, addr_width=2, page_size=8)

            logger.info("verifying device configuration and firmware")
            if fx2_device.read_boot_eeprom(0, len(image), addr_width=2) != image:
                logger.critical("factory programming failed")
                return 1

            logger.warning("power cycle the device to finish the operation")

        if args.action == "list":
            for serial in sorted(GlasgowDevice.enumerate_serials()):
                print(serial)
            return 0

    # Device-related errors
    except GlasgowDeviceError as e:
        logger.error(e)
        return 1

    # Applet-related errors
    except GatewareBuildError as e:
        UnusedElaboratable._MustUse__silence = True
        applet.logger.error(e)
        return 2

    # Environment-related errors
    except (PluginRequirementsUnmet, PluginLoadError) as e:
        logger.error(e)
        print(e.metadata.description)
        return 3

    except ToolchainNotFound as e:
        return 3

    # User interruption
    except KeyboardInterrupt:
        logger.warning("interrupted")
        return 130 # 128 + SIGINT

    finally:
        if device is not None:
            device.close()

    return 0


# This entry point is invoked via `project.scripts.glasgow` when installing the package with `pipx`.
def run_main():
    exit(asyncio.new_event_loop().run_until_complete(main()))


# This entry point is invoked when running `python -m glasgow.cli`.
if __name__ == "__main__":
    run_main()
