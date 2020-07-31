import operator

from .lazy import *
from .bits import bits


__all__ = ["dump_hex", "dump_bin", "dump_seq", "dump_mapseq"]


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


def dump_seq(joiner, data):
    def to_seq(data):
        try:
            data_length = len(data)
        except TypeError:
            try:
                data_length = data.__length_hint__()
            except AttributeError:
                data_length = None
        if dump_seq.limit is None or (data_length is not None and
                                      data_length < dump_seq.limit):
            return joiner.join(data)
        else:
            return "{}... ({} elements total)".format(
                joiner.join(elem for elem, _ in zip(data, range(dump_seq.limit))),
                data_length or "?")
    return lazy(lambda: to_seq(data))

dump_seq.limit = 16


def dump_mapseq(joiner, mapper, data):
    def to_mapseq(data):
        try:
            data_length = len(data)
        except TypeError:
            try:
                data_length = data.__length_hint__()
            except AttributeError:
                data_length = None
        if dump_mapseq.limit is None or (data_length is not None and
                                         data_length < dump_mapseq.limit):
            return joiner.join(map(mapper, data))
        else:
            return "{}... ({} elements total)".format(
                joiner.join(mapper(elem) for elem, _ in zip(data, range(dump_mapseq.limit))),
                data_length or "?")
    return lazy(lambda: to_mapseq(data))

dump_mapseq.limit = 16
