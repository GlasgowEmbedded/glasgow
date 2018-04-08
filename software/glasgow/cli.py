import argparse

from . import *


def get_argparser():
    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers(dest="action", metavar="COMMAND")
    subparsers.required = True

    p_download = subparsers.add_parser(
        "download", help="non-volatile download bitstream to FPGA")
    p_download.add_argument(
        "bitstream", metavar="BITSTREAM", type=argparse.FileType("rb"),
        help="read bitstream from the specified file")

    return parser


def main():
    args = get_argparser().parse_args()

    try:
        device = GlasgowDevice()
    except GlasgowDeviceError as e:
        raise SystemExit(e)

    if args.action == "download":
        device.download_bitstream(args.bitstream.read())


if __name__ == "__main__":
    main()
