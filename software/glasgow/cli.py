import os
import argparse

from fx2 import FX2DeviceError

from .device import *
from .gateware.target import TestToggleIO, TestExposeI2C


def get_argparser():
    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers(dest="action", metavar="COMMAND")
    subparsers.required = True

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

    p_test_expose_i2c = test_subparsers.add_parser(
        "expose-i2c", help="mirror {SDA,SCL} on A[1:0] at 3.3 V")

    return parser


def main():
    args = get_argparser().parse_args()

    try:
        firmware_file = os.path.join(os.path.dirname(__file__), "glasgow.ihex")
        device = GlasgowDevice(firmware_file)
    except (FX2DeviceError, GlasgowDeviceError) as e:
        raise SystemExit(e)

    if args.action == "download":
        device.download_bitstream(args.bitstream.read())
    if args.action == "test":
        if args.mode == "toggle-io":
            device.download_bitstream(TestToggleIO().get_bitstream(debug=True))
            device.set_voltage("AB", 3.3)
        if args.mode == "expose-i2c":
            device.download_bitstream(TestExposeI2C().get_bitstream(debug=True))
            device.set_voltage("A", 3.3)


if __name__ == "__main__":
    main()
