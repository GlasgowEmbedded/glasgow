from .lazy import *


__all__ = ["dump_hex"]


def dump_hex(data):
    def to_hex(data):
        try:
            if dump_hex.limit == 0 or len(data) < dump_hex.limit:
                return data.hex()
            else:
                return "{}... ({} bytes total)".format(
                    data[:dump_hex.limit].hex(), len(data))
        except AttributeError:
            return to_hex(bytes(data))
    return lazy(lambda: to_hex(data))

dump_hex.limit = 64
