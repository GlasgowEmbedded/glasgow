import os
import sys
import ast
import platform
import logging
import argparse
import textwrap
import re
import asyncio
import signal
import unittest
import importlib.metadata
from vcd import VCDWriter
from datetime import datetime

from fx2 import FX2Config, FX2Device, FX2DeviceError, VID_CYPRESS, PID_FX2
from fx2.format import input_data, diff_data

from . import __version__
from .support.logging import *
from .support.asignal import *
from .support.plugin import PluginRequirementsUnmet, PluginLoadError
from .device import GlasgowDeviceError
from .device.config import GlasgowConfig
from .target.toolchain import ToolchainNotFound
from .target.hardware import GlasgowHardwareTarget
from .gateware import GatewareBuildError
from .gateware.analyzer import TraceDecoder
from .device.hardware import VID_QIHW, PID_GLASGOW, GlasgowHardwareDevice
from .access.direct import *
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
        return re.sub(r"((?!\n\n)(?!\n\s+(?:\*|\$|\d+\.)).)+(\n*)?", filler, text, flags=re.S)


def version_info():
    glasgow_version = __version__
    python_version = '.'.join(map(str, sys.version_info[:3]))
    python_implementation = platform.python_implementation()
    python_platform = platform.platform()
    freedesktop_os_name = ""
    if hasattr(platform, "freedesktop_os_release"): # TODO(py3.9): present in 3.10+
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
    parser = argparse.ArgumentParser(formatter_class=TextHelpFormatter)

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
        help="raise TRACE log messages to DEBUG if they begin with 'FILTER: '")
    parser.add_argument(
        "--statistics", dest="show_statistics", default=False, action="store_true",
        help="display performance counters before exiting")

    return parser


def get_argparser():
    def add_subparsers(parser, **kwargs):
        if isinstance(parser, argparse._MutuallyExclusiveGroup):
            container = parser._container
            if kwargs.get('prog') is None:
                formatter = container._get_formatter()
                formatter.add_usage(container.usage, [], [], '')
                kwargs['prog'] = formatter.format_help().strip()

            parsers_class = parser._pop_action_class(kwargs, 'parsers')
            subparsers = argparse._SubParsersAction(option_strings=[],
                                                    parser_class=type(container),
                                                    **kwargs)
            parser._add_action(subparsers)
        else:
            subparsers = parser.add_subparsers(**kwargs)
        return subparsers

    def add_applet_arg(parser, mode, required=False):
        subparsers = add_subparsers(parser, dest="applet", metavar="APPLET", required=required)

        for handle, metadata in GlasgowAppletMetadata.all().items():
            if not metadata.loadable:
                # fantastically cursed
                p_applet = subparsers.add_parser(
                    handle, help=metadata.synopsis, description=metadata.description,
                    formatter_class=TextHelpFormatter, prefix_chars='\0', add_help=False)
                p_applet.add_argument("args", nargs="...", help=argparse.SUPPRESS)
                p_applet.add_argument("help", nargs="?", default=p_applet.format_help())
                continue

            applet_cls = metadata.applet_cls

            if mode == "test" and applet_cls.tests() is None:
                continue
            if mode == "tool" and not hasattr(applet_cls, "tool_cls"):
                continue

            if mode == "tool":
                help        = applet_cls.tool_cls.help
                description = applet_cls.tool_cls.description
            else:
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

            if mode == "test":
                p_applet.add_argument(
                    "tests", metavar="TEST", nargs="*",
                    help="test cases to run")

            if mode in ("build", "interact", "repl", "script"):
                access_args = DirectArguments(applet_name=handle,
                                              default_port="AB",
                                              pin_count=16)
                if mode in ("interact", "repl", "script"):
                    g_applet_build = p_applet.add_argument_group("build arguments")
                    applet_cls.add_build_arguments(g_applet_build, access_args)
                    g_applet_run = p_applet.add_argument_group("run arguments")
                    applet_cls.add_run_arguments(g_applet_run, access_args)
                    if mode == "interact":
                        # FIXME: this makes it impossible to add subparsers in applets
                        # g_applet_interact = p_applet.add_argument_group("interact arguments")
                        # applet.add_interact_arguments(g_applet_interact)
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

    subparsers = parser.add_subparsers(dest="action", metavar="COMMAND")
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
        "--no-alert", dest="set_alert", default=True, action="store_false",
        help="do not raise an alert if Vsense is out of range of Vio")

    p_safe = subparsers.add_parser(
        "safe", formatter_class=TextHelpFormatter,
        help="turn off all I/O port voltage regulators and drivers")

    p_voltage_limit = subparsers.add_parser(
        "voltage-limit", formatter_class=TextHelpFormatter,
        help="limit I/O port voltage as a safety mechanism")
    add_ports_arg(p_voltage_limit)
    add_voltage_arg(p_voltage_limit,
        help="maximum allowed I/O port voltage")

    def add_build_args(parser):
        parser.add_argument(
            "--override-required-revision", default=False, action="store_true",
            help="(advanced) override applet revision requirement")

    def add_run_args(parser):
        add_build_args(parser)

        g_run_bitstream = parser.add_mutually_exclusive_group()
        g_run_bitstream.add_argument(
            "--reload", default=False, action="store_true",
            help="(advanced) reload bitstream even if an identical one is already loaded")
        g_run_bitstream.add_argument(
            "--prebuilt", default=False, action="store_true",
            help="(advanced) load prebuilt applet bitstream from ./<applet-name.bin>")
        g_run_bitstream.add_argument(
            "--prebuilt-at", dest="bitstream", metavar="BITSTREAM-FILE",
            type=argparse.FileType("rb"),
            help="(advanced) load prebuilt applet bitstream from BITSTREAM-FILE")

        parser.add_argument(
            "--trace", metavar="VCD-FILE", type=argparse.FileType("wt"),
            help="trace applet I/O to VCD-FILE")

    p_run = subparsers.add_parser(
        "run", formatter_class=TextHelpFormatter,
        help="run an applet and interact through its command-line interface")
    add_run_args(p_run)
    add_applet_arg(p_run, mode="interact", required=True)

    p_repl = subparsers.add_parser(
        "repl", formatter_class=TextHelpFormatter,
        help="run an applet and open a REPL to use its programming interface")
    add_run_args(p_repl)
    add_applet_arg(p_repl, mode="repl", required=True)

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
    add_applet_arg(p_script, mode="script", required=True)

    p_tool = subparsers.add_parser(
        "tool", formatter_class=TextHelpFormatter,
        help="run an offline tool provided with an applet")
    add_applet_arg(p_tool, mode="tool", required=True)

    p_flash = subparsers.add_parser(
        "flash", formatter_class=TextHelpFormatter,
        help="program FX2 firmware or applet bitstream into EEPROM")
    add_build_args(p_flash)

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
    add_applet_arg(g_flash_bitstream, mode="build")

    p_build = subparsers.add_parser(
        "build", formatter_class=TextHelpFormatter,
        help="(advanced) build applet logic and save it as a file")
    add_build_args(p_build)

    p_build.add_argument(
        "--rev", metavar="REVISION", type=revision, required=True,
        help="board revision")
    p_build.add_argument(
        "--trace", default=False, action="store_true",
        help="include applet analyzer")
    p_build.add_argument(
        "-t", "--type", metavar="TYPE", type=str,
        choices=["zip", "archive", "il", "rtlil", "bin", "bitstream"], default="bitstream",
        help="artifact to build (one of: archive rtlil bitstream, default: %(default)s)")
    p_build.add_argument(
        "-f", "--filename", metavar="FILENAME", type=str,
        help="file to save artifact to (default: <applet-name>.{zip,il,bin})")
    add_applet_arg(p_build, mode="build", required=True)

    p_test = subparsers.add_parser(
        "test", formatter_class=TextHelpFormatter,
        help="(advanced) test applet logic without target hardware")
    add_applet_arg(p_test, mode="test", required=True)

    def factory_serial(arg):
        if re.match(r"^\d{8}T\d{6}Z$", arg):
            return arg
        else:
            raise argparse.ArgumentTypeError(f"{arg} is not a valid serial number")

    def factory_manufacturer(arg):
        if len(arg) <= 23:
            return arg
        else:
            raise argparse.ArgumentTypeError("f{arg} is too long for the manufacturer field")

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
def _applet(revision, args):
    target = GlasgowHardwareTarget(revision=revision,
                                   multiplexer_cls=DirectMultiplexer,
                                   with_analyzer=hasattr(args, "trace") and args.trace)
    applet = GlasgowAppletMetadata.get(args.applet).applet_cls()
    try:
        message = ("applet requires device rev{}+, rev{} found"
                   .format(applet.required_revision, revision))
        if revision < applet.required_revision:
            if args.override_required_revision:
                applet.logger.warn(message)
            else:
                raise GlasgowAppletError(message)
        applet.build(target, args)
    except GlasgowAppletError as e:
        applet.logger.error(e)
        logger.error("failed to build subtarget for applet %r", args.applet)
        raise SystemExit()
    return target, applet


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
            if record.msg.startswith(subject + ": "):
                levelno = logging.DEBUG
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
    if level < 0:
        dump_hex.limit = dump_bin.limit = dump_seq.limit = dump_mapseq.limit = None

    if args.log_file or args.filter_log:
        term_handler.addFilter(SubjectFilter(level, args.filter_log))
        root_logger.setLevel(logging.TRACE)
    else:
        # By setting the log level on the root logger, we avoid creating LogRecords in the first
        # place instead of filtering them later; we have a *lot* of logging, so this is much
        # more efficient.
        root_logger.setLevel(level)


async def _main():
    # Handle log messages emitted during construction of the argument parser (e.g. by the plugin
    # subsystem).
    term_handler = create_logger()

    args = get_argparser().parse_args()
    configure_logger(args, term_handler)

    device = None
    try:
        if args.action not in ("build", "test", "tool", "factory", "list"):
            device = GlasgowHardwareDevice(args.serial)

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
            target, applet = _applet(device.revision, args)
            device.demultiplexer = DirectDemultiplexer(device, target.multiplexer.pipe_count)
            plan = target.build_plan()

            if args.prebuilt or args.bitstream:
                bitstream_file = args.bitstream or open(f"{args.applet}.bin", "rb")
                with bitstream_file:
                    await device.download_prebuilt(plan, bitstream_file)
            else:
                await device.download_target(plan, reload=args.reload)

            do_trace = hasattr(args, "trace") and args.trace
            if do_trace:
                logger.info("starting applet analyzer")
                await device.write_register(target.analyzer.addr_done, 0)
                analyzer_iface = await device.demultiplexer.claim_interface(
                    target.analyzer, target.analyzer.mux_interface, args=None)
                trace_decoder = TraceDecoder(target.analyzer.event_sources)
                # Use the coarsest possible timescale to improve performance with sigrok.
                vcd_writer = VCDWriter(args.trace, timescale="10 ns", check_values=False,
                    comment='Generated by Glasgow for bitstream ID %s'
                            % plan.bitstream_id.hex())

            async def run_analyzer():
                signals = {}
                strobes = set()
                for field_name, field_trigger, field_width in trace_decoder.events():
                    if field_trigger == "throttle":
                        var_type = "wire"
                        var_init = 0
                    elif field_trigger == "change":
                        var_type = "wire"
                        var_init = "x" * field_width
                    elif field_trigger == "strobe":
                        if field_width > 0:
                            var_type = "tri"
                            var_init = "z"
                        else:
                            var_type = "event"
                            var_init = ""
                    else:
                        assert False
                    signals[field_name] = vcd_writer.register_var(
                        scope="", name=field_name, var_type=var_type,
                        size=field_width, init=var_init)
                    if field_trigger == "strobe":
                        strobes.add(field_name)

                init = True
                while not trace_decoder.is_done():
                    trace_decoder.process(await analyzer_iface.read())
                    for cycle, events in trace_decoder.flush():
                        if events == "overrun":
                            target.analyzer.logger.error("FIFO overrun, shutting down")

                            for name in signals:
                                vcd_writer.change(signals[name], next_timestamp, "x")
                            next_timestamp += 100 # 1us
                            break

                        event_repr = " ".join(f"{n}={v}"
                                              for n, v in events.items())
                        target.analyzer.logger.trace("cycle %d: %s", cycle, event_repr)

                        timestamp      = int(1e8 * (cycle + 0) // target.sys_clk_freq)
                        next_timestamp = int(1e8 * (cycle + 1) // target.sys_clk_freq)
                        if init:
                            init = False
                            vcd_writer._timestamp = timestamp
                        for name, value in events.items():
                            vcd_writer.change(signals[name], timestamp, value)
                        for name, _value in events.items():
                            if name in strobes:
                                vcd_writer.change(signals[name], next_timestamp, "z")
                        vcd_writer.flush()

                vcd_writer.close(next_timestamp)

            async def run_applet():
                logger.info("running handler for applet %r", args.applet)
                if applet.preview:
                    logger.warn("applet %r is PREVIEW QUALITY and may CORRUPT DATA", args.applet)
                try:
                    iface = await applet.run(device, args)
                    if args.action in ("repl", "script"):
                        if len(args.script_args) > 0 and args.script_args[0] == "--":
                            args.script_args = args.script_args[1:]
                    if args.action == "run":
                        return await applet.interact(device, args, iface)
                    elif args.action == "repl":
                        await applet.repl(device, args, iface)
                    elif args.action == "script":
                        if args.script_file:
                            code = compile(args.script_file.read(), filename=args.script_file.name,
                                mode="exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
                        else:
                            code = compile(args.script_cmd, filename="<command>",
                                mode="exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
                        future = eval(code, {"iface":iface, "device":device, "args":args})
                        if future is not None:
                            await future

                except GlasgowAppletError as e:
                    applet.logger.error(str(e))
                    return 1
                except asyncio.CancelledError:
                    return 130 # 128 + SIGINT
                finally:
                    await device.demultiplexer.flush()
                    if args.show_statistics:
                        device.demultiplexer.statistics()

            async def wait_for_sigint():
                await wait_for_signal(signal.SIGINT)
                logger.debug("Ctrl+C pressed, terminating")

            if do_trace:
                analyzer_task = asyncio.ensure_future(run_analyzer())

            tasks = []
            tasks.append(applet_task := asyncio.ensure_future(run_applet()))
            if args.action != "repl":
                tasks.append(asyncio.ensure_future(wait_for_sigint()))

            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.wait(tasks, return_when=asyncio.ALL_COMPLETED)

            # If the applet task has raised an exception, retrieve it here in case any of the await
            # statements above will fail; if we don't, asyncio will unnecessarily complain.
            applet_task.exception()

            if do_trace:
                await device.write_register(target.analyzer.addr_done, 1)
                await analyzer_task

            await device.demultiplexer.cancel()

            return applet_task.result()

        if args.action == "tool":
            tool = GlasgowAppletMetadata.get(args.applet).tool_cls()
            try:
                return await tool.run(args)
            except GlasgowAppletError as e:
                tool.logger.error(e)
                return 1

        if args.action == "flash":
            logger.info("reading device configuration")
            header = await device.read_eeprom("fx2", 0, 8 + 4 + GlasgowConfig.size)
            header[0] = 0xC2 # see below

            fx2_config = FX2Config.decode(header, partial=True)
            if (len(fx2_config.firmware) != 1 or
                    fx2_config.firmware[0][0] != 0x4000 - GlasgowConfig.size or
                    len(fx2_config.firmware[0][1]) != GlasgowConfig.size):
                raise SystemExit("Unrecognized or corrupted configuration block")
            glasgow_config = GlasgowConfig.decode(fx2_config.firmware[0][1])

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
                target, applet = _applet(device.revision, args)
                plan = target.build_plan()
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

            fx2_config.firmware[0] = (0x4000 - GlasgowConfig.size, glasgow_config.encode())

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
                    logger.warn("using custom firmware from %s", args.firmware.name)
                    with args.firmware as f:
                        for (addr, chunk) in input_data(f, fmt="ihex"):
                            fx2_config.append(addr, chunk)
                else:
                    logger.info("using built-in firmware")
                    for (addr, chunk) in GlasgowHardwareDevice.firmware_data():
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
            else:
                logger.info("configuration and firmware identical")

        if args.action == "build":
            target, applet = _applet(args.rev, args)
            plan = target.build_plan()
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
            applet = GlasgowAppletMetadata.get(args.applet).applet_cls()
            loader = unittest.TestLoader()
            stream = unittest.runner._WritelnDecorator(sys.stderr)
            result = unittest.TextTestResult(stream=stream, descriptions=True, verbosity=2)
            result.failfast = True
            def startTest(test):
                unittest.TextTestResult.startTest(result, test)
                result.stream.write("\n")
            result.startTest = startTest
            if args.tests == []:
                suite = loader.loadTestsFromTestCase(applet.tests())
                suite.run(result)
            else:
                for test in args.tests:
                    suite = loader.loadTestsFromName(test, module=applet.tests())
                    suite.run(result)
            if not result.wasSuccessful():
                for _, traceback in result.errors + result.failures:
                    print(traceback, end="", file=sys.stderr)
                return 1

        if args.action == "factory":
            if args.serial:
                logger.error(f"--serial is not supported for factory flashing")
                return 1

            device_id = GlasgowConfig.encode_revision(args.factory_rev)
            glasgow_config = GlasgowConfig(args.factory_rev, args.factory_serial,
                                           manufacturer=args.factory_manufacturer,
                                           modified_design=(args.factory_modified_design != "no"))
            firmware_data = GlasgowHardwareDevice.firmware_data()

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
            for serial in sorted(GlasgowHardwareDevice.enumerate_serials()):
                print(serial)
            return 0

    # Device-related errors
    except GlasgowDeviceError as e:
        logger.error(e)
        return 1

    # Applet-related errors
    except GatewareBuildError as e:
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
        logger.warn("interrupted")
        return 130 # 128 + SIGINT

    finally:
        if device is not None:
            device.close()

    return 0


def main():
    loop = asyncio.get_event_loop()
    exit(loop.run_until_complete(_main()))


if __name__ == "__main__":
    main()
