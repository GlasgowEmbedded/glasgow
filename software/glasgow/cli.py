import os
import logging
import argparse
import textwrap
import re
import time
from datetime import datetime

from fx2 import VID_CYPRESS, PID_FX2, FX2Config, FX2Device, FX2DeviceError
from fx2.format import input_data, diff_data

from .device import VID_QIHW, PID_GLASGOW, GlasgowConfig, GlasgowDevice
from .target import GlasgowTarget
from .target.test import *
from .applet import GlasgowApplet


logging.addLevelName(5, 'TRACE')
logging.TRACE = 5
logging.Logger.trace = lambda self, msg, *args, **kwargs: \
    self.log(logging.TRACE, msg, *args, **kwargs)


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
        return re.sub(r"((?!\n\n)(?!\n\s+\*).)+(\n*)?", filler, text, flags=re.S)


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

    def add_applet_arg(parser, add_run_args=False, required=False):
        subparsers = add_subparsers(parser, dest="applet", metavar="APPLET")
        subparsers.required = required

        for applet_name, applet in GlasgowApplet.all_applets.items():
            p_applet = subparsers.add_parser(
                applet_name, help=applet.help, description=applet.description,
                formatter_class=TextHelpFormatter)
            applet.add_build_arguments(p_applet)
            if add_run_args:
                applet.add_run_arguments(p_applet)

    parser = argparse.ArgumentParser(formatter_class=TextHelpFormatter)

    parser.add_argument(
        "-v", "--verbose", default=0, action="count",
        help="increase logging verbosity")
    parser.add_argument(
        "-q", "--quiet", default=0, action="count",
        help="decrease logging verbosity")

    subparsers = parser.add_subparsers(dest="action", metavar="COMMAND")
    subparsers.required = True

    p_voltage = subparsers.add_parser(
        "voltage", formatter_class=TextHelpFormatter,
        help="query or set I/O port voltage")
    p_voltage.add_argument(
        "ports", metavar="PORTS", type=str, nargs="?", default="AB",
        help="I/O port set (one or more of: A B, default: all)")
    p_voltage.add_argument(
        "voltage", metavar="VOLTS", type=float, nargs="?", default=None,
        help="I/O port voltage (range: 1.8-5.0)")
    p_voltage.add_argument(
        "--tolerance", metavar="PCT", type=float, default=10.0,
        help="raise alert if measured voltage deviates by more than ±PCT%% (default: %(default)s)")
    p_voltage.add_argument(
        "--no-alert", dest="set_alert", default=True, action="store_false",
        help="do not raise an alert if Vsense is out of range of Vio")

    p_run = subparsers.add_parser(
        "run", formatter_class=TextHelpFormatter,
        help="load an applet bitstream and run applet code")
    p_run.add_argument(
        "--force", default=False, action="store_true",
        help="reload bitstream even if an identical one is loaded")
    g_run_bitstream = p_run.add_mutually_exclusive_group(required=True)
    g_run_bitstream.add_argument(
        "--bitstream", metavar="FILENAME", type=argparse.FileType("rb"),
        help="read bitstream from the specified file")
    add_applet_arg(g_run_bitstream, add_run_args=True)

    p_flash = subparsers.add_parser(
        "flash", formatter_class=TextHelpFormatter,
        help="program FX2 firmware or applet bitstream into EEPROM")

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
    add_applet_arg(g_flash_bitstream, required=False)

    def revision(arg):
        if re.match(r"^[A-Z]$", arg):
            return arg
        else:
            raise argparse.ArgumentTypeError("{} is not a valid revision letter".format(arg))

    def serial(arg):
        if re.match(r"^\d{8}T\d{6}Z$", arg):
            return arg
        else:
            raise argparse.ArgumentTypeError("{} is not a valid serial number".format(arg))

    p_build = subparsers.add_parser(
        "build", formatter_class=TextHelpFormatter,
        help="(advanced) build applet logic and save it as a file")
    p_build.add_argument(
        "-t", "--type", metavar="TYPE", type=str,
        choices=["v", "verilog", "bin", "bitstream"], default="bitstream",
        help="artifact to build (one of: verilog bitstream, default: %(default)s)")
    p_build.add_argument(
        "-f", "--filename", metavar="FILENAME", type=str,
        help="file to save artifact to (default: <applet-name>.{v,bin})")
    add_applet_arg(p_build, required=True)

    p_test = subparsers.add_parser(
        "test", help="(advanced) verify device functionality")

    test_subparsers = p_test.add_subparsers(dest="mode", metavar="MODE")
    test_subparsers.required = True

    p_test_toggle_io = test_subparsers.add_parser(
        "toggle-io", help="output 1 kHz square wave on all I/O pins at 3.3 V")
    p_test_mirror_i2c = test_subparsers.add_parser(
        "mirror-i2c", help="mirror {SDA,SCL} on A[0-1] at 3.3 V")
    p_test_shift_out = test_subparsers.add_parser(
        "shift-out", help="shift bytes from EP2OUT MSB first via {CLK,DO} on A[0-1] at 3.3 V")
    p_test_shift_out.add_argument(
        "--async", default=False, action="store_true",
        help="use asynchronous FIFO")
    p_test_gen_seq = test_subparsers.add_parser(
        "gen-seq", help="read limit from EP4IN and generate sequence on {EP2OUT,EP6OUT}")
    p_test_pll = test_subparsers.add_parser(
        "pll", help="use PLL to output 15 MHz on SYNC port")
    p_test_registers = test_subparsers.add_parser(
        "registers", help="add I2C RW register [0] and RO register [1] = [0] << 1")

    p_factory = subparsers.add_parser(
        "factory", formatter_class=TextHelpFormatter,
        help="(advanced) initial device programming")
    p_factory.add_argument(
        "--revision", metavar="REVISION", type=str,
        default="A",
        help="revision letter (if not specified: %(default)s)")
    p_factory.add_argument(
        "--serial", metavar="SERIAL", type=str,
        default=datetime.now().strftime("%Y%m%dT%H%M%SZ"),
        help="serial number in ISO 8601 format (if not specified: %(default)s)")

    return parser


# The name of this function appears in Verilog output, so keep it tidy.
def _applet(args):
    target = GlasgowTarget()
    applet = GlasgowApplet.all_applets[args.applet]()
    applet.build(target, args)
    return applet, target


def main():
    args = get_argparser().parse_args()

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO + args.quiet * 10 - args.verbose * 10)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(levelname)5s] %(name)s: %(message)s"))
    root_logger.addHandler(handler)

    try:
        firmware_file = os.path.join(os.path.dirname(__file__), "glasgow.ihex")
        if args.action in ("build",):
            pass
        elif args.action == "factory":
            device = GlasgowDevice(firmware_file, VID_CYPRESS, PID_FX2)
        else:
            device = GlasgowDevice(firmware_file)

        if args.action == "voltage":
            if args.voltage is not None:
                device.reset_alert(args.ports)
                device.poll_alert() # clear any remaining alerts
                try:
                    device.set_voltage(args.ports, args.voltage)
                except:
                    device.set_voltage(args.ports, 0.0)
                    raise
                if args.set_alert and args.voltage != 0.0:
                    time.sleep(0.050) # let the output capacitor discharge a bit
                    device.set_alert_tolerance(args.ports, args.voltage, args.tolerance / 100)

            print("Port\tVio\tVsense\tRange")
            alerts = device.poll_alert()
            for port in args.ports:
                vio = device.get_voltage(port)
                vsense = device.measure_voltage(port)
                alert = device.get_alert(port)
                if port in alerts:
                    notice = " (ALERT)"
                else:
                    notice = ""
                print("{}\t{:.2}\t{:.3}\t{:.2}-{:.2}{}"
                      .format(port, vio, vsense, alert[0], alert[1], notice))

        if args.action == "run":
            if args.applet:
                applet, target = _applet(args)

                bitstream_id = target.get_bitstream_id()
                if device.bitstream_id() == bitstream_id and not args.force:
                    logger.info("device already has bitstream ID %s", bitstream_id.hex())
                else:
                    logger.info("building bitstream ID %s for applet %s",
                                bitstream_id.hex(), args.applet)
                    device.download_bitstream(target.get_bitstream(debug=True), bitstream_id)

                logger.info("running handler for applet %s", args.applet)
                applet.run(device, args)

            else:
                with args.bitstream as f:
                    logger.info("downloading bitstream from %s", f.name)
                    device.download_bitstream(f.read())

        if args.action == "flash":
            logger.info("reading device configuration")
            header = device.read_eeprom("fx2", 0, 8 + 4 + GlasgowConfig.size)
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
                applet, target = _applet(args)
                new_bitstream_id = target.get_bitstream_id()
                new_bitstream = target.get_bitstream()

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
                logger.info("using firmware from %s",
                            args.firmware.name if args.firmware else firmware_file)
                with (args.firmware or open(firmware_file, "rb")) as f:
                    for (addr, chunk) in input_data(f, fmt="ihex"):
                        fx2_config.append(addr, chunk)
                fx2_config.disconnect = True
                new_image = fx2_config.encode()

            if new_bitstream:
                logger.info("programming bitstream")
                old_bitstream = device.read_eeprom("ice", 0, len(new_bitstream))
                if old_bitstream != new_bitstream:
                    for (addr, chunk) in diff_data(old_bitstream, new_bitstream):
                        device.write_eeprom("ice", addr, chunk)

                    logger.info("verifying bitstream")
                    if device.read_eeprom("ice", 0, len(new_bitstream)) != new_bitstream:
                        raise SystemExit("Bitstream programming failed")
                else:
                    logger.info("bitstream identical")

            logger.info("programming configuration and firmware")
            old_image = device.read_eeprom("fx2", 0, len(new_image))
            if old_image != new_image:
                for (addr, chunk) in diff_data(old_image, new_image):
                    device.write_eeprom("fx2", addr, chunk)

                logger.info("verifying configuration and firmware")
                if device.read_eeprom("fx2", 0, len(new_image)) != new_image:
                    raise SystemExit("Configuration/firmware programming failed")
            else:
                logger.info("configuration and firmware identical")

        if args.action == "build":
            applet, target = _applet(args)
            logger.info("building bitstream for applet %s", args.applet)
            if args.type in ("v", "verilog"):
                target.get_verilog().write(args.filename or args.applet + ".v")
            if args.type in ("bin", "bitstream"):
                with open(args.filename or args.applet + ".bin", "wb") as f:
                    f.write(target.get_bitstream(debug=True))

        if args.action == "test":
            if args.mode == "toggle-io":
                device.download_bitstream(TestToggleIO().get_bitstream(debug=True))
                device.set_voltage("AB", 3.3)

            if args.mode == "mirror-i2c":
                device.download_bitstream(TestMirrorI2C().get_bitstream(debug=True))
                device.set_voltage("A", 3.3)

            if args.mode == "shift-out":
                device.download_bitstream(TestShiftOut(async=args.async)
                                          .get_bitstream(debug=True))
                device.set_voltage("A", 3.3)

            if args.mode == "gen-seq":
                device.download_bitstream(TestGenSeq().get_bitstream(debug=True))

            if args.mode == "pll":
                device.download_bitstream(TestPLL().get_bitstream(debug=True))

            if args.mode == "registers":
                device.download_bitstream(TestRegisters().get_bitstream(debug=True))

        if args.action == "factory":
            logger.info("reading device configuration")
            header = device.read_eeprom("fx2", 0, 8 + 4 + GlasgowConfig.size)
            if not re.match(rb"^\xff+$", header):
                raise SystemExit("Device already factory-programmed")

            fx2_config = FX2Config(vendor_id=VID_QIHW, product_id=PID_GLASGOW,
                                   device_id=1 + ord(args.revision) - ord('A'),
                                   i2c_400khz=True)
            glasgow_config = GlasgowConfig(args.revision, args.serial)
            fx2_config.append(0x4000 - GlasgowConfig.size, glasgow_config.encode())

            image = fx2_config.encode()
            # Let FX2 hardware enumerate. This won't load the configuration block
            # into memory automatically, but the firmware has code that does that
            # if it detects a C0 load.
            image[0] = 0xC0

            logger.info("programming device configuration")
            device.write_eeprom("fx2", 0, image)

            logger.info("verifying device configuration")
            if device.read_eeprom("fx2", 0, len(image)) != image:
                raise SystemExit("Factory programming failed")

    except (ValueError, FX2DeviceError) as e:
        raise SystemExit(e)


if __name__ == "__main__":
    main()
