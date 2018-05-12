import os
import argparse
import time

from fx2 import FX2DeviceError

from .device import *
from .gateware.test import *


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
        help="raise alert if measured voltage deviates by more than ±PCT%%")
    p_voltage.add_argument(
        "--no-alert", dest="set_alert", default=True, action="store_false",
        help="do not raise an alert if Vsense is out of range of Vio")

    p_download = subparsers.add_parser(
        "download", help="volatile download bitstream to FPGA")
    p_download.add_argument(
        "bitstream", metavar="BITSTREAM", type=argparse.FileType("rb"),
        help="read bitstream from the specified file")

    p_test = subparsers.add_parser(
        "test", help="verify device functionality")

    test_subparsers = p_test.add_subparsers(dest="mode", metavar="MODE")
    test_subparsers.required = True

    p_test_toggle_io = test_subparsers.add_parser(
        "toggle-io", help="toggle all I/O pins at 3.3 V")
    p_test_mirror_i2c = test_subparsers.add_parser(
        "mirror-i2c", help="mirror {SDA,SCL} on A[1:0] at 3.3 V")
    p_test_gen_seq = test_subparsers.add_parser(
        "gen-seq", help="read limit from EP2IN and generate sequence on {EP6OUT,EP8OUT}")

    return parser


def main():
    args = get_argparser().parse_args()

    try:
        firmware_file = os.path.join(os.path.dirname(__file__), "glasgow.ihex")
        device = GlasgowDevice(firmware_file)

        if args.action == "voltage":
            if args.voltage is not None:
                device.reset_alert(args.ports)
                device.poll_alert() # clear any remaining alerts
                device.set_voltage(args.ports, args.voltage)
                if args.set_alert and args.voltage != 0.0:
                    time.sleep(0.050) # let the output capacitor discharge a bit
                    tolerance  = args.tolerance / 100
                    low_volts  = args.voltage * (1 - tolerance)
                    high_volts = args.voltage * (1 + tolerance)
                    device.set_alert(args.ports, low_volts, high_volts)

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

        if args.action == "download":
            device.download_bitstream(args.bitstream.read())

        if args.action == "test":
            if args.mode == "toggle-io":
                device.download_bitstream(TestToggleIO().get_bitstream(debug=True))
                device.set_voltage("AB", 3.3)
            if args.mode == "mirror-i2c":
                device.download_bitstream(TestMirrorI2C().get_bitstream(debug=True))
                device.set_voltage("A", 3.3)
            if args.mode == "gen-seq":
                device.download_bitstream(TestGenSeq().get_bitstream(debug=True))

    except FX2DeviceError as e:
        raise SystemExit(e)


if __name__ == "__main__":
    main()
