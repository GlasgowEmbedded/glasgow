import os
import argparse
import textwrap
import re
import time
from datetime import datetime

from fx2 import VID_CYPRESS, PID_FX2, FX2Config, FX2Device, FX2DeviceError
from fx2.format import input_data, diff_data

from .device import VID_QIHW, PID_GLASGOW, GlasgowConfig, GlasgowDevice
from .gateware.target import GlasgowTarget
from .gateware.test import *
from .applet import GlasgowApplet


class TextHelpFormatter(argparse.HelpFormatter):
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
    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers(dest="action", metavar="COMMAND")
    subparsers.required = True

    p_voltage = subparsers.add_parser(
        "voltage", help="query or set I/O port voltage")
    p_voltage.add_argument(
        "ports", metavar="PORTS", type=str, nargs='?', default="AB",
        help="I/O port set (one or more of: A B, default: all)")
    p_voltage.add_argument(
        "voltage", metavar="VOLTS", type=float, nargs='?', default=None,
        help="I/O port voltage (range: 1.8-5.0)")
    p_voltage.add_argument(
        "--tolerance", metavar="PCT", type=float, default=10.0,
        help="raise alert if measured voltage deviates by more than ±PCT%% (default: %(default)s)")
    p_voltage.add_argument(
        "--no-alert", dest="set_alert", default=True, action="store_false",
        help="do not raise an alert if Vsense is out of range of Vio")

    p_run = subparsers.add_parser(
        "run", help="run an applet")
    p_run.add_argument(
        "--no-build", dest="build_bitstream", default=True, action="store_false",
        help="do not rebuild bitstream")
    p_run.add_argument(
        "--no-execute", dest="run_applet", default=True, action="store_false",
        help="do not execute applet code")

    run_subparsers = p_run.add_subparsers(dest="applet", metavar="APPLET")
    run_subparsers.required = True

    for applet_name, applet in GlasgowApplet.all_applets.items():
        p_applet = run_subparsers.add_parser(
            applet_name, help=applet.help, description=applet.description,
            formatter_class=TextHelpFormatter)
        applet.add_arguments(p_applet)

    p_test = subparsers.add_parser(
        "test", help="verify device functionality")

    test_subparsers = p_test.add_subparsers(dest="mode", metavar="MODE")
    test_subparsers.required = True

    p_test_toggle_io = test_subparsers.add_parser(
        "toggle-io", help="output 1 kHz square wave on all I/O pins at 3.3 V")
    p_test_mirror_i2c = test_subparsers.add_parser(
        "mirror-i2c", help="mirror {SDA,SCL} on A[0-1] at 3.3 V")
    p_test_shift_out = test_subparsers.add_parser(
        "shift-out", help="shift bytes from EP2OUT MSB first via {CLK,DO} on A[0-1] at 3.3 V")
    p_test_gen_seq = test_subparsers.add_parser(
        "gen-seq", help="read limit from EP4IN and generate sequence on {EP2OUT,EP6OUT}")
    p_test_pll = test_subparsers.add_parser(
        "pll", help="use PLL to output 15 MHz on SYNC port")

    p_test_download = subparsers.add_parser(
        "download", help="download arbitrary bitstream to FPGA")
    p_test_download.add_argument(
        "bitstream", metavar="BITSTREAM", type=argparse.FileType("rb"),
        help="read bitstream from the specified file")

    p_flash = subparsers.add_parser(
        "flash", help="program FX2 firmware into EEPROM")
    g_flash_firmware = p_flash.add_mutually_exclusive_group()
    g_flash_firmware.add_argument(
        "-f", "--firmware", metavar="FILENAME", type=argparse.FileType("rb"),
        help="read firmware from the specified file")
    g_flash_firmware.add_argument(
        "-n", "--no-firmware", default=False, action="store_true",
        help="remove any firmware present")

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

    p_factory = subparsers.add_parser(
        "factory", help="initial device programming")
    p_factory.add_argument(
        "--revision", metavar="REVISION", type=str,
        default="A",
        help="revision letter (if not specified: %(default)s)")
    p_factory.add_argument(
        "--serial", metavar="SERIAL", type=str,
        default=datetime.now().strftime("%Y%m%dT%H%M%SZ"),
        help="serial number in ISO 8601 format (if not specified: %(default)s)")

    return parser


def main():
    args = get_argparser().parse_args()

    try:
        firmware_file = os.path.join(os.path.dirname(__file__), "glasgow.ihex")
        if args.action == "factory":
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
            applet = GlasgowApplet.all_applets[args.applet](spec="A")
            target = GlasgowTarget(in_count=1, out_count=1)
            applet.build(target)
            if args.build_bitstream:
                device.download_bitstream(target.get_bitstream(debug=True))
            if args.run_applet:
                applet.run(device, args)

        if args.action == "test":
            if args.mode == "toggle-io":
                device.download_bitstream(TestToggleIO().get_bitstream(debug=True))
                device.set_voltage("AB", 3.3)

            if args.mode == "mirror-i2c":
                device.download_bitstream(TestMirrorI2C().get_bitstream(debug=True))
                device.set_voltage("A", 3.3)

            if args.mode == "shift-out":
                device.download_bitstream(TestShiftOut().get_bitstream(debug=True))
                device.set_voltage("A", 3.3)

            if args.mode == "gen-seq":
                device.download_bitstream(TestGenSeq().get_bitstream(debug=True))

            if args.mode == "pll":
                device.download_bitstream(TestPLL().get_bitstream(debug=True))

            if args.mode == "download":
                device.download_bitstream(args.bitstream.read())

        if args.action == "flash":
            header = device.read_eeprom(0, 0, 8 + 4 + GlasgowConfig.size)
            header[0] = 0xC2 # see below

            fx2_config = FX2Config.decode(header, partial=True)
            if (len(fx2_config.firmware) != 1 or
                    len(fx2_config.firmware[0][1]) != GlasgowConfig.size):
                raise SystemExit("Unrecognized or corrupted configuration block")

            if args.no_firmware:
                fx2_config.disconnect = False
                new_image = fx2_config.encode()
                new_image[0] = 0xC0 # see below
            else:
                with open(args.firmware or firmware_file, "rb") as f:
                    for (addr, chunk) in input_data(f, fmt="ihex"):
                        fx2_config.append(addr, chunk)
                fx2_config.disconnect = True
                new_image = fx2_config.encode()

            old_image = device.read_eeprom(0, 0, len(new_image))
            for (addr, chunk) in diff_data(old_image, new_image):
                device.write_eeprom(0, addr, chunk)

        if args.action == "factory":
            header = device.read_eeprom(0, 0, 8 + 4 + GlasgowConfig.size)
            if not re.match(rb"^\xff+$", header):
                raise SystemExit("Device already factory-programmed")

            fx2_config = FX2Config(vendor_id=VID_QIHW, product_id=PID_GLASGOW,
                                   device_id=1 + ord(args.revision) - ord('A'),
                                   i2c_400khz=True)
            glasgow_config = GlasgowConfig(args.revision, args.serial)
            fx2_config.append(0x4000 - GlasgowConfig.size, glasgow_config.encode())

            image = fx2_config.encode()
            image[0] = 0xC0 # let FX2 hardware enumerate

            device.write_eeprom(0, 0, image)
            if device.read_eeprom(0, 0, len(image)) != image:
                raise SystemExit("Factory programming failed")

    except FX2DeviceError as e:
        raise SystemExit(e)


if __name__ == "__main__":
    main()
