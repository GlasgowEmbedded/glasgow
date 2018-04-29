import os
import sys
import argparse
import tempfile
import shutil

from .device import *
from .gateware.target import GlasgowTest


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
        device = GlasgowDevice()
    except GlasgowDeviceError as e:
        raise SystemExit(e)

    if args.action == "download":
        device.download_bitstream(args.bitstream.read())
    if args.action == "test":
        device.download_bitstream(get_bitstream(GlasgowTest()))


if __name__ == "__main__":
    main()
