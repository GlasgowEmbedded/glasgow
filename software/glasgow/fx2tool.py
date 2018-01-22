import sys
import os
import io
import re
import argparse

from .fx2 import VID_CYPRESS, PID_FX2, FX2Device, FX2DeviceError


def get_argparser():
    def vid_pid(arg):
        match = re.match(r"^([0-9a-f]{1,4}):([0-9a-f]{1,4})$", arg, re.I)
        if not match:
            raise argparse.ArgumentTypeError(f"{arg} is not a VID:PID pair")
        vid = int(match.group(1), 16)
        pid = int(match.group(2), 16)
        return (vid, pid)

    def int_with_base(str):
        return int(str, 0)

    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Cypress FX2/FX2LP bootloader tool")
    parser.add_argument(
        "-d", "--device", type=vid_pid, default=(VID_CYPRESS, PID_FX2),
        help="device VID:PID pair")
    parser.add_argument(
        "-F", "--format", choices=["bin", "hex", "ihex", "auto"], default="auto",
        help="data input/output format")
    parser.add_argument(
        "-S", "--stage2", metavar="FILENAME", type=argparse.FileType("rb"),
        help="load the second stage bootloader before any further action")

    subparsers = parser.add_subparsers(dest="action")
    subparsers.required = True

    p_load = subparsers.add_parser(
        "load", help="load and run firmware")
    p_load.add_argument(
        "firmware", metavar="FIRMWARE", type=argparse.FileType("rb"),
        help="read firmware from the specified file")

    def add_read_args(parser):
        parser.add_argument(
            "-f", "--file", metavar="FILENAME", type=argparse.FileType("wb"), default="-",
            help="write data to the specified file")
        parser.add_argument(
            "address", metavar="ADDRESS", type=int_with_base,
            help="starting address")
        parser.add_argument(
            "length", metavar="LENGTH", type=int_with_base,
            help="amount of bytes to read")

    def add_write_args(parser):
        parser.add_argument(
            "-a", "--offset", metavar="ADDRESS", type=int_with_base, default=0,
            help="starting address")
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "-f", "--file", metavar="FILENAME", type=argparse.FileType("rb"),
            help="read data from the specified file")
        group.add_argument(
            "-d", "--data", metavar="DATA", type=str,
            help="hexadecimal bytes to write")

    p_read_ram = subparsers.add_parser(
        "read_ram", help="read data from internal RAM")
    add_read_args(p_read_ram)

    p_write_ram = subparsers.add_parser(
        "write_ram", help="write data to internal RAM")
    add_write_args(p_write_ram)

    def add_eeprom_args(parser):
        parser.add_argument(
            "-W", "--address-width", metavar="WIDTH", type=int, choices=[1, 2], default=2,
            help="EEPROM address width in bytes")

    p_read_eeprom = subparsers.add_parser(
        "read_eeprom", help="read data from boot EEPROM")
    add_eeprom_args(p_read_eeprom)
    add_read_args(p_read_eeprom)

    p_write_eeprom = subparsers.add_parser(
        "write_eeprom", help="write data to boot EEPROM")
    add_eeprom_args(p_write_eeprom)
    add_write_args(p_write_eeprom)

    return parser


def autodetect_format(file):
    basename, extname = os.path.splitext(file.name)
    if extname in [".hex", ".ihex", ".ihx"]:
        return "ihex"
    elif extname in [".bin"]:
        return "bin"
    elif file.isatty():
        return "hex"
    else:
        raise SystemExit("Specify file format explicitly")


def output_data(fmt, file, data, offset):
    if isinstance(file, io.TextIOWrapper):
        file = file.buffer

    if fmt == "auto":
        fmt = autodetect_format(file)

    if fmt == "bin":
        file.write(data)

    elif fmt == "hex":
        for n, byte in enumerate(data):
            file.write(f"{byte:02x}".encode())
            if n > 0 and n % 16 == 15:
                file.write(b"\n")
            elif n > 0 and n % 8 == 7:
                file.write(b"  ")
            else:
                file.write(b" ")
        if n % 16 != 15:
            file.write(b"\n")

    elif fmt == "ihex":
        pos = 0
        while pos < len(data):
            recoff  = offset + pos
            recdata = data[pos:pos + 0x10]
            record  = [
                len(recdata),
                (recoff >> 8) & 0xff,
                (recoff >> 0) & 0xff,
                0x00,
                *list(recdata)
            ]
            record.append((~sum(record) + 1) & 0xff)
            file.write(b":")
            file.write(bytes(record).hex().encode())
            file.write(b"\n")
            pos += len(recdata)
        file.write(b":00000001ff\n")


def input_data(fmt, file, data, offset):
    if isinstance(file, io.TextIOWrapper):
        file = file.buffer

    if file is None:
        fmt = "hex"
        data = data.encode()
    else:
        data = file.read()

    if fmt == "auto":
        fmt = autodetect_format(file)

    if fmt == "bin":
        return [(offset, data)]

    elif fmt == "hex":
        try:
            hexdata = re.sub(r"\s*", "", data.decode())
            bindata = bytes.fromhex(hexdata)
        except ValueError as e:
            raise SystemExit("Invalid hexadecimal data")
        return [(offset, bindata)]

    elif fmt == "ihex":
        RE_HDR = re.compile(rb":([0-9a-f]{8})", re.I)
        RE_WS  = re.compile(rb"\s*")

        resoff = 0
        resbuf = []
        res = []

        pos = 0
        while pos < len(data):
            match = RE_HDR.match(data, pos)
            if match is None:
                raise SystemExit(f"Invalid record header at offset {pos}")
            *rechdr, = bytes.fromhex(match.group(1).decode())
            reclen, recoffh, recoffl, rectype = rechdr

            recdatahex = data[match.end(0):match.end(0)+(reclen+1)*2]
            if len(recdatahex) < (reclen + 1) * 2:
                raise SystemExit(f"Truncated record at offset {pos}")
            try:
                *recdata, recsum = bytes.fromhex(recdatahex.decode())
            except ValueError:
                raise SystemExit(f"Invalid record data at offset {pos}")
            if sum(rechdr + recdata + [recsum]) & 0xff != 0:
                raise SystemExit(f"Invalid record checksum at offset {pos}")
            if rectype not in [0x00, 0x01]:
                raise SystemExit(f"Unknown record type at offset {pos}")
            if rectype == 0x01:
                break

            recoff = (recoffh << 8) | recoffl
            if resoff + len(resbuf) == recoff:
                resbuf += recdata
            else:
                if len(resbuf) > 0:
                    res.append((offset + resoff, resbuf))
                resoff  = recoff
                resbuf  = recdata

            match = RE_WS.match(data, match.end(0) + len(recdatahex))
            pos = match.end(0)

        if len(resbuf) > 0:
            res.append((offset + resoff, resbuf))

        return res


def load(device, fmt, firmware):
    data = input_data(fmt, firmware, None, 0)
    device.cpu_reset(True)
    for address, chunk in data:
        device.write_ram(address, chunk)
    device.cpu_reset(False)


def main():
    args = get_argparser().parse_args()

    try:
        vid, pid = args.device
        device = FX2Device(vid, pid)
    except FX2DeviceError as e:
        raise SystemExit(e)

    if args.stage2:
        load(device, "auto", args.stage2)

    if args.action == "load":
        load(device, args.format, args.firmware)

    elif args.action == "read_ram":
        device.cpu_reset(True)
        data = device.read_ram(args.address, args.length)
        output_data(args.format, args.file, data, args.address)

    elif args.action == "write_ram":
        data = input_data(args.format, args.file, args.data, args.offset)
        device.cpu_reset(True)
        for address, chunk in data:
            device.write_ram(address, chunk)

    elif args.action == "read_eeprom":
        device.cpu_reset(False)
        data = device.read_eeprom(args.address, args.length, args.address_width)
        output_data(args.format, args.file, data, args.address)

    elif args.action == "write_eeprom":
        data = input_data(args.format, args.file, args.data, args.offset)
        device.cpu_reset(False)
        for address, chunk in data:
            device.write_eeprom(address, chunk, args.address_width)


if __name__ == "__main__":
    main()
