import os
import sys
import argparse
import tempfile
import shutil

from fx2 import FX2DeviceError

from .device import *
from .gateware.target import TestToggleIO


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
        "toggle-io", help="toggle all I/O pins")

    return parser


def get_bitstream(fragment):
    try:
        build_dir = tempfile.mkdtemp(prefix="glasgow_")
        fragment.build(build_dir=build_dir)
        with open(os.path.join(build_dir, "top.bin"), "rb") as f:
            bitstream = f.read()
        shutil.rmtree(build_dir)
    except:
        print("Keeping build tree as " + build_dir, file=sys.stderr)
        raise
    return bitstream


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
            device.download_bitstream(get_bitstream(TestToggleIO()))


if __name__ == "__main__":
    main()
