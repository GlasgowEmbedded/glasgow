import os
import sys
import logging
import argparse
import textwrap
import re
import asyncio
import unittest
import shutil
from vcd import VCDWriter
from datetime import datetime

from fx2 import VID_CYPRESS, PID_FX2, FX2Config
from fx2.format import input_data, diff_data

from ._version import get_versions
from .device import GlasgowDeviceError
from .device.config import GlasgowConfig
from .target.hardware import GlasgowHardwareTarget
from .gateware import GatewareBuildError
from .gateware.analyzer import TraceDecoder
from .device.hardware import VID_QIHW, PID_GLASGOW, GlasgowHardwareDevice
from .access.direct import *
from .applet import *
from .applet.all import *
from .support.logging import *
from .support.pyrepl import *


logger = logging.getLogger(__name__)


class TextHelpFormatter(argparse.HelpFormatter):
    def __init__(self, prog):
        super().__init__(prog, width=120)

    def _fill_text(self, text, width, indent):
        def filler(match):
            text = match[0]

            list_match = re.match(r"(\s*)\*", text)
            if list_match:
                return text

            text = textwrap.fill(text, width,
                                 initial_indent=indent,
                                 subsequent_indent=indent)

            text = re.sub(r"(\w-) (\w)", r"\1\2", text)
            text = text + (match[2] or "")
            return text

        text = textwrap.dedent(text).strip()
        return re.sub(r"((?!\n\n)(?!\n\s+(?:\*|\$|\d+\.)).)+(\n*)?", filler, text, flags=re.S)


def create_argparser():
    parser = argparse.ArgumentParser(formatter_class=TextHelpFormatter)

    version = "Glasgow version {version} (Python {python_version})" \
        .format(python_version=".".join(str(n) for n in sys.version_info[:3]),
                **get_versions())

    parser.add_argument(
        "-V", "--version", action="version", version=version,
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
            subparsers = parser.add_subparsers(dest="applet", metavar="APPLET")
        return subparsers

    def add_applet_arg(parser, mode, required=False):
        subparsers = add_subparsers(parser, dest="applet", metavar="APPLET")
        subparsers.required = required

        for applet_name, applet in GlasgowApplet.all_applets.items():
            if mode == "test" and not hasattr(applet, "test_cls"):
                continue
            if mode == "tool" and not hasattr(applet, "tool_cls"):
                continue

            if mode == "tool":
                help        = applet.tool_cls.help
                description = applet.tool_cls.description
            else:
                help        = applet.help
                description = applet.description
            if applet.preview:
                help += " (PREVIEW QUALITY APPLET)"
                description = "    This applet is PREVIEW QUALITY and may CORRUPT DATA or " \
                              "have missing features. Use at your own risk.\n" + description
            if applet.required_revision > "A0":
                help += " (rev{}+)".format(applet.required_revision)
                description += "\n    This applet requires Glasgow rev{} or later." \
                               .format(applet.required_revision)

            p_applet = subparsers.add_parser(
                applet_name, help=help, description=description,
                formatter_class=TextHelpFormatter)

            if mode == "test":
                p_applet.add_argument(
                    "tests", metavar="TEST", nargs="*",
                    help="test cases to run")

            if mode in ("build", "run"):
                access_args = DirectArguments(applet_name=applet_name,
                                              default_port="AB",
                                              pin_count=16)
                if mode == "run":
                    g_applet_build = p_applet.add_argument_group("build arguments")
                    applet.add_build_arguments(g_applet_build, access_args)
                    g_applet_run = p_applet.add_argument_group("run arguments")
                    applet.add_run_arguments(g_applet_run, access_args)
                    # FIXME: this makes it impossiblt to add subparsers in applets
                    # g_applet_interact = p_applet.add_argument_group("interact arguments")
                    # applet.add_interact_arguments(g_applet_interact)
                    applet.add_interact_arguments(p_applet)
                if mode == "build":
                    applet.add_build_arguments(p_applet, access_args)

            if mode == "tool":
                applet.tool_cls.add_arguments(p_applet)

    parser = create_argparser()

    subparsers = parser.add_subparsers(dest="action", metavar="COMMAND")
    subparsers.required = True

    def add_ports_arg(parser):
        parser.add_argument(
            "ports", metavar="PORTS", type=str, nargs="?", default="AB",
            help="I/O port set (one or more of: A B, default: all)")

    def add_voltage_arg(parser, help):
        parser.add_argument(
            "voltage", metavar="VOLTS", type=float, nargs="?", default=None,
            help="%s (range: 1.8-5.0)".format(help))

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

    p_voltage_limit = subparsers.add_parser(
        "voltage-limit", formatter_class=TextHelpFormatter,
        help="limit I/O port voltage as a safety mechanism")
    add_ports_arg(p_voltage_limit)
    add_voltage_arg(p_voltage_limit,
        help="maximum allowed I/O port voltage")

    def add_toolchain_args(parser):
        parser.add_argument(
            "--synthesis-opts", metavar="OPTIONS", type=str, default="",
            help="(advanced) pass OPTIONS to FPGA synthesis toolchain")

    p_run = subparsers.add_parser(
        "run", formatter_class=TextHelpFormatter,
        help="load an applet bitstream and run applet code")
    add_toolchain_args(p_run)
    p_run.add_argument(
        "--rebuild", default=False, action="store_true",
        help="rebuild bitstream even if an identical one is already loaded")
    p_run.add_argument(
        "--trace", metavar="FILENAME", type=argparse.FileType("wt"), default=None,
        help="trace applet I/O to FILENAME")
    add_applet_arg(p_run, mode="run")

    p_run_prebuilt = subparsers.add_parser(
        "run-prebuilt", formatter_class=TextHelpFormatter,
        help="(advanced) load a prebuilt applet bitstream and run applet code")
    p_run_prebuilt.add_argument(
        "bitstream", metavar="FILENAME", type=argparse.FileType("rb"),
        help="read bitstream from the specified file")
    add_applet_arg(p_run_prebuilt, mode="run")

    p_tool = subparsers.add_parser(
        "tool", formatter_class=TextHelpFormatter,
        help="run an offline tool provided with an applet")
    add_applet_arg(p_tool, mode="tool")

    p_flash = subparsers.add_parser(
        "flash", formatter_class=TextHelpFormatter,
        help="program FX2 firmware or applet bitstream into EEPROM")
    add_toolchain_args(p_flash)

    g_flash_firmware = p_flash.add_mutually_exclusive_group()
    g_flash_firmware.add_argument(
        "--firmware", metavar="FILENAME", type=argparse.FileType("rb"),
        help="read firmware from the specified file")
    g_flash_firmware.add_argument(
        "--remove-firmware", default=False, action="store_true",
        help="remove any firmware present")

    g_flash_bitstream = p_flash.add_mutually_exclusive_group()
    g_flash_bitstream.add_argument(
        "--bitstream", metavar="FILENAME", type=argparse.FileType("rb"),
        help="read bitstream from the specified file")
    g_flash_bitstream.add_argument(
        "--remove-bitstream", default=False, action="store_true",
        help="remove any bitstream present")
    add_applet_arg(g_flash_bitstream, mode="build")

    def revision(arg):
        revisions = ["A0", "B0", "C0", "C1"]
        if arg in revisions:
            return arg
        else:
            raise argparse.ArgumentTypeError("{} is not a valid revision (should be one of: {})"
                                             .format(arg, ", ".join(revisions)))

    def serial(arg):
        if re.match(r"^\d{8}T\d{6}Z$", arg):
            return arg
        else:
            raise argparse.ArgumentTypeError("{} is not a valid serial number".format(arg))

    p_build = subparsers.add_parser(
        "build", formatter_class=TextHelpFormatter,
        help="(advanced) build applet logic and save it as a file")
    add_toolchain_args(p_build)

    p_build.add_argument(
        "--rev", metavar="REVISION", type=revision, required=True,
        help="board revision")
    p_build.add_argument(
        "--trace", default=False, action="store_true",
        help="include applet analyzer")
    p_build.add_argument(
        "-t", "--type", metavar="TYPE", type=str,
        choices=["zip", "archive", "v", "verilog", "bin", "bitstream"], default="bitstream",
        help="artifact to build (one of: archive verilog bitstream, default: %(default)s)")
    p_build.add_argument(
        "-f", "--filename", metavar="FILENAME", type=str,
        help="file to save artifact to (default: <applet-name>.{v,bin})")
    add_applet_arg(p_build, mode="build", required=True)

    p_test = subparsers.add_parser(
        "test", formatter_class=TextHelpFormatter,
        help="(advanced) test applet logic without target hardware")
    add_applet_arg(p_test, mode="test", required=True)

    p_factory = subparsers.add_parser(
        "factory", formatter_class=TextHelpFormatter,
        help="(advanced) initial device programming")
    p_factory.add_argument(
        "--force", default=False, action="store_true",
        help="reinitialize the device, even if it is already programmed")
    p_factory.add_argument(
        "--rev", metavar="REVISION", type=revision, required=True,
        help="board revision")
    p_factory.add_argument(
        "--serial", metavar="SERIAL", type=str,
        default=datetime.now().strftime("%Y%m%dT%H%M%SZ"),
        help="serial number in ISO 8601 format (if not specified: %(default)s)")

    return parser


# The name of this function appears in Verilog output, so keep it tidy.
def _applet(revision, args):
    target = GlasgowHardwareTarget(revision=revision,
                                   multiplexer_cls=DirectMultiplexer,
                                   with_analyzer=hasattr(args, "trace") and args.trace)
    applet = GlasgowApplet.all_applets[args.applet]()
    try:
        if revision < applet.required_revision:
            raise GlasgowAppletError("applet requires device rev{}+, rev{} found"
                                     .format(applet.required_revision, revision))
        applet.build(target, args)
    except GlasgowAppletError as e:
        applet.logger.error(e)
        logger.error("failed to build subtarget for applet %r", args.applet)
        raise SystemExit()
    return target, applet


class TerminalFormatter(logging.Formatter):
    LOG_COLORS = {
        "TRACE"   : "\033[37m",
        "DEBUG"   : "\033[36m",
        "INFO"    : "\033[1;37m",
        "WARNING" : "\033[1;33m",
        "ERROR"   : "\033[1;31m",
        "CRITICAL": "\033[1;41m",
    }

    def format(self, record):
        color = self.LOG_COLORS.get(record.levelname, "")
        # glasgow.applet.foo → g.applet.foo
        record.name = record.name.replace("glasgow.", "g.")
        # applet.memory._25x → applet.memory.25x
        record.name = record.name.replace("._", ".")
        return "{}{}\033[0m".format(color, super().format(record))


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


def create_logger(args):
    root_logger = logging.getLogger()

    term_formatter_args = {"style": "{",
        "fmt": "{levelname[0]:s}: {name:s}: {message:s}"}
    term_handler = logging.StreamHandler()
    if sys.stderr.isatty() and sys.platform != 'win32':
        term_handler.setFormatter(TerminalFormatter(**term_formatter_args))
    else:
        term_handler.setFormatter(logging.Formatter(**term_formatter_args))
    root_logger.addHandler(term_handler)

    file_formatter_args = {"style": "{",
        "fmt": "[{asctime:s}] {levelname:s}: {name:s}: {message:s}"}
    file_handler = None
    if args.log_file:
        file_handler = logging.StreamHandler(args.log_file)
        file_handler.setFormatter(logging.Formatter(**file_formatter_args))
        root_logger.addHandler(file_handler)

    level = logging.INFO + args.quiet * 10 - args.verbose * 10
    if level < 0:
        dump_hex.limit = 0

    if args.log_file or args.filter_log:
        term_handler.addFilter(SubjectFilter(level, args.filter_log))
        root_logger.setLevel(logging.TRACE)
    else:
        # By setting the log level on the root logger, we avoid creating LogRecords in the first
        # place instead of filtering them later; we have a *lot* of logging, so this is much
        # more efficient.
        root_logger.setLevel(level)


def _toolchain_opts(args):
    return {"debug": True, "synth_opts": args.synthesis_opts}


async def _main():
    args = get_argparser().parse_args()
    create_logger(args)

    try:
        firmware_file = os.path.join(os.path.dirname(__file__), "glasgow.ihex")
        if args.action in ("build", "test", "tool"):
            pass
        elif args.action == "factory":
            device = GlasgowHardwareDevice(firmware_file, VID_CYPRESS, PID_FX2,
                                           _revision_override=args.rev)
        else:
            device = GlasgowHardwareDevice(firmware_file)

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

            print("Port\tVio\tVlimit\tVsense\tMonitor")
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

        if args.action == "voltage-limit":
            if args.voltage is not None:
                await device.set_voltage_limit(args.ports, args.voltage)

            print("Port\tVio\tVlimit")
            for port in args.ports:
                vio    = await device.get_voltage(port)
                vlimit = await device.get_voltage_limit(port)
                print("{}\t{:.2}\t{:.2}"
                      .format(port, vio, vlimit))

        if args.action in ("run", "run-prebuilt"):
            target, applet = _applet(device.revision, args)
            device.demultiplexer = DirectDemultiplexer(device, target.multiplexer.pipe_count)

            if args.action == "run":
                await device.download_target(target, rebuild=args.rebuild,
                                             toolchain_opts=_toolchain_opts(args))
            if args.action == "run-prebuilt":
                logger.warn("downloading prebuilt bitstream from %s", args.bitstream.name)
                await device.download_bitstream(args.bitstream.read())

            do_trace = hasattr(args, "trace") and args.trace
            if do_trace:
                logger.info("starting applet analyzer")
                await device.write_register(target.analyzer.addr_done, 0)
                analyzer_iface = await device.demultiplexer.claim_interface(
                    target.analyzer, target.analyzer.mux_interface, args=None)
                trace_decoder = TraceDecoder(target.analyzer.event_sources)
                vcd_writer = VCDWriter(args.trace, timescale="1 ns", check_values=False,
                    comment='Generated by Glasgow for bitstream ID %s'
                            % target.get_bitstream_id().hex())

            async def run_analyzer():
                if not do_trace:
                    return

                signals = {}
                strobes = set()
                for field_name, field_trigger, field_width in trace_decoder.events():
                    if field_trigger == "throttle":
                        var_type = "wire"
                        var_init = 0
                    elif field_trigger == "change":
                        var_type = "wire"
                        var_init = "x"
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
                            timestamp += 1e3 # 1us
                            break

                        event_repr = " ".join("{}={}".format(n, v)
                                              for n, v in events.items())
                        target.analyzer.logger.trace("cycle %d: %s", cycle, event_repr)

                        timestamp      = 1e9 * (cycle + 0) // target.sys_clk_freq
                        next_timestamp = 1e9 * (cycle + 1) // target.sys_clk_freq
                        if init:
                            init = False
                            vcd_writer._timestamp = timestamp
                        for name, value in events.items():
                            vcd_writer.change(signals[name], timestamp, value)
                        for name, _value in events.items():
                            if name in strobes:
                                vcd_writer.change(signals[name], next_timestamp, "z")
                        vcd_writer.flush()

                vcd_writer.close(timestamp)

            async def run_applet():
                logger.info("running handler for applet %r", args.applet)
                if applet.preview:
                    logger.warn("applet %r is PREVIEW QUALITY and may CORRUPT DATA", args.applet)
                try:
                    iface = await applet.run(device, args)
                    await applet.interact(device, args, iface)
                except GlasgowAppletError as e:
                    applet.logger.error(str(e))
                finally:
                    if do_trace:
                        await device.write_register(target.analyzer.addr_done, 1)

            done, pending = await asyncio.wait([run_analyzer(), run_applet()],
                                               return_when=asyncio.FIRST_EXCEPTION)
            for task in done:
                await task

            # Work around bugs in python-libusb1 that cause segfaults on interpreter shutdown.
            await device.demultiplexer.flush()

        if args.action == "tool":
            tool = GlasgowApplet.all_applets[args.applet].tool_cls()
            try:
                await tool.run(args)
            except GlasgowAppletError as e:
                tool.logger.error(e)
                raise SystemExit()

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
                    new_bitstream = f.read()
                    glasgow_config.bitstream_size = len(new_bitstream)
                    glasgow_config.bitstream_id   = b"\xff"*16
            elif args.applet:
                logger.info("building bitstream for applet %s", args.applet)
                target, applet = _applet(device.revision, args)
                new_bitstream_id = target.get_bitstream_id()
                new_bitstream = target.get_bitstream(**_toolchain_opts(args))

                # We always build and reflash the bitstream in case the one currently
                # in EEPROM is corrupted. If we only compared the ID, there would be
                # no easy way to recover from that case. There's also no point in
                # storing the bitstream hash (as opposed to Verilog hash) in the ID,
                # as building the bitstream takes much longer than flashing it.
                logger.info("built bitstream ID %s", new_bitstream_id.hex())
                glasgow_config.bitstream_size = len(new_bitstream)
                glasgow_config.bitstream_id   = new_bitstream_id

            fx2_config.firmware[0] = (0x4000 - GlasgowConfig.size, glasgow_config.encode())

            if args.remove_firmware:
                logger.info("removing firmware")
                fx2_config.disconnect = False
                new_image = fx2_config.encode()
                new_image[0] = 0xC0 # see below
            else:
                logger.info("using firmware from %r",
                            args.firmware.name if args.firmware else firmware_file)
                with (args.firmware or open(firmware_file, "rb")) as f:
                    for (addr, chunk) in input_data(f, fmt="ihex"):
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
            if args.type in ("v", "verilog"):
                logger.info("building Verilog for applet %r", args.applet)
                target.get_verilog().write(args.filename or args.applet + ".v")
            if args.type in ("bin", "bitstream"):
                logger.info("building bitstream for applet %r", args.applet)
                with open(args.filename or args.applet + ".bin", "wb") as f:
                    f.write(target.get_bitstream(**_toolchain_opts(args)))
            if args.type in ("zip", "archive"):
                logger.info("building archive for applet %r", args.applet)
                with target.get_build_tree() as tree:
                    if args.filename:
                        basename, = os.path.splitext(args.filename)
                    else:
                        basename = args.applet
                    shutil.make_archive(basename, format="zip", root_dir=tree, logger=logger)

        if args.action == "test":
            logger.info("testing applet %r", args.applet)
            applet = GlasgowApplet.all_applets[args.applet]()
            loader = unittest.TestLoader()
            stream = unittest.runner._WritelnDecorator(sys.stderr)
            result = unittest.TextTestResult(stream=stream, descriptions=True, verbosity=2)
            result.failfast = True
            def startTest(test):
                unittest.TextTestResult.startTest(result, test)
                result.stream.write("\n")
            result.startTest = startTest
            if args.tests == []:
                suite = loader.loadTestsFromTestCase(applet.test_cls)
                suite.run(result)
            else:
                for test in args.tests:
                    suite = loader.loadTestsFromName(test, module=applet.test_cls)
                    suite.run(result)
            if not result.wasSuccessful():
                for _, traceback in result.errors + result.failures:
                    print(traceback, end="", file=sys.stderr)
                return 1

        if args.action == "factory":
            logger.info("reading device configuration")
            header = await device.read_eeprom("fx2", 0, 8 + 4 + GlasgowConfig.size)
            if not re.match(rb"^\xff+$", header):
                if args.force:
                    logger.warning("device already factory-programmed, proceeding anyway")
                else:
                    logger.error("device already factory-programmed")
                    return 1

            fx2_config = FX2Config(vendor_id=VID_QIHW, product_id=PID_GLASGOW,
                                   device_id=GlasgowConfig.encode_revision(args.rev),
                                   i2c_400khz=True)
            glasgow_config = GlasgowConfig(args.rev, args.serial)
            fx2_config.append(0x4000 - GlasgowConfig.size, glasgow_config.encode())

            image = fx2_config.encode()
            # Let FX2 hardware enumerate. This won't load the configuration block
            # into memory automatically, but the firmware has code that does that
            # if it detects a C0 load.
            image[0] = 0xC0

            logger.info("programming device configuration")
            await device.write_eeprom("fx2", 0, image)

            logger.info("verifying device configuration")
            if await device.read_eeprom("fx2", 0, len(image)) != image:
                logger.critical("factory programming failed")
                return 1

    except GlasgowDeviceError as e:
        logger.error(e)
        return 1

    except GatewareBuildError as e:
        applet.logger.error(e)
        return 1

    return 0


def main():
    loop = asyncio.get_event_loop()
    exit(loop.run_until_complete(_main()))


if __name__ == "__main__":
    main()
