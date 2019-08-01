from .lazy import *
from .bits import bits


__all__ = ["dump_hex", "dump_bin"]


def dump_hex(data):
    def to_hex(data):
        try:
            data = memoryview(data)
        except TypeError:
            data = memoryview(bytes(data))
        if dump_hex.limit is None or len(data) < dump_hex.limit:
            return data.hex()
        else:
            return "{}... ({} bytes total)".format(
                data[:dump_hex.limit].hex(), len(data))
    return lazy(lambda: to_hex(data))

dump_hex.limit = 64


def dump_bin(data):
    def to_bin(data):
        data = bits(data)
        if dump_bin.limit is None or len(data) < dump_bin.limit:
            return str(data)[::-1]
        else:
            return "{}... ({} bits total)".format(
                str(data[:dump_bin.limit])[::-1], len(data))
    return lazy(lambda: to_bin(data))

dump_bin.limit = 64
