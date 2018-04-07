import argparse

from . import *


def get_argparser():
    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers(dest="action", metavar="COMMAND")
    subparsers.required = True

    p_check = subparsers.add_parser(
        "check", help="check if firmware is loaded")

    return parser


def main():
    args = get_argparser().parse_args()

    try:
        device = GlasgowDevice()
    except GlasgowDeviceError as e:
        raise SystemExit(e)


if __name__ == "__main__":
    main()
