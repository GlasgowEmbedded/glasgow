import sys
import types
import unittest
from bitarray import bitarray
from ctypes import c_ubyte, c_uint64, LittleEndianStructure, Union


__all__ = ["Bitfield"]


class _PackedUnion(Union):
    @classmethod
    def from_bytes(cls, data):
        data = bytes(data)
        pack = cls()
        pack._bytes_[:] = data
        return pack

    @classmethod
    def from_bytearray(cls, data):
        data = bytearray(data)
        pack = cls()
        pack._bytes_[:] = data
        return pack

    @classmethod
    def from_bitarray(cls, data):
        data = bitarray(data, endian="little")
        return cls.from_bytes(data.tobytes())

    def __init__(self, *args, **kwargs):
        _, bits_cls = self._fields_[0]

        arg_index = 0
        fields = {}
        for f_name, f_type, f_width in bits_cls._fields_:
            if arg_index == len(args):
                break

            if not f_name.startswith("_reserved_"):
                assert f_name not in fields
                fields[f_name] = args[arg_index]
                arg_index += 1

        fields.update(kwargs)

        super().__init__(bits_cls(**fields))

    def as_bytes(self):
        return bytes(self._bytes_)

    def as_bytearray(self):
        return bytearray(self._bytes_)

    def as_bitarray(self):
        data = bitarray(endian="little")
        data.frombytes(self.as_bytes())
        return data

    def _bits_repr_(self):
        fields = []
        for f_name, f_type, f_width in self._bits_._fields_:
            if f_name.startswith("_reserved_"):
                continue
            fields.append("{}={:0{}b}".format(f_name, getattr(self._bits_, f_name), f_width))
        return " ".join(fields)

    def __repr__(self):
        return "<{}.{} {}>".format(self.__module__, self.__class__.__name__, self._bits_repr_())

    def __eq__(self, other):
        return self._bytes_[:] == other._bytes_[:]

    def __ne__(self, other):
        return self._bytes_[:] != other._bytes_[:]


def Bitfield(name, size_bytes, fields):
    mod = sys._getframe(1).f_globals["__name__"] # see namedtuple()

    reserved = 0
    def make_reserved():
        nonlocal reserved
        reserved += 1
        return "_reserved_{}".format(reserved)

    bits_cls = types.new_class(name + "_bits_", (LittleEndianStructure,))
    bits_cls.__module__ = mod
    bits_cls._packed_ = True
    bits_cls._fields_ = [(make_reserved() if f_name is None else f_name, c_uint64, f_width)
                         for f_name, f_width in fields]

    pack_cls = types.new_class(name, (_PackedUnion,))
    pack_cls.__module__ = mod
    pack_cls._packed_ = True
    pack_cls._anonymous_ = ("_bits_",)
    pack_cls._fields_ = [("_bits_", bits_cls),
                         ("_bytes_", c_ubyte * size_bytes)]

    return pack_cls

# -------------------------------------------------------------------------------------------------

class BitfieldTestCase(unittest.TestCase):
    def test_definition(self):
        bf = Bitfield("bf", 2, [("a", 3), ("b", 5)])
        self.assertEqual(bf.__name__, "bf")
        self.assertEqual(bf.__module__, __name__)
        x = bf(1, 2)
        self.assertEqual(x.a, 1)
        self.assertEqual(x.b, 2)

    def test_large(self):
        bf = Bitfield("bf", 8, [("a", 64)])

    def test_reserved(self):
        bf = Bitfield("bf", 8, [(None, 1), ("a", 1)])
        x = bf(1)
        self.assertEqual(repr(x), "<%s.bf a=1>" % __name__)

    def test_bytes(self):
        bf = Bitfield("bf", 2, [("a", 3), ("b", 5)])
        x = bf(1, 2)
        self.assertIsInstance(x.as_bytes(), bytes)
        self.assertEqual(x.as_bytes(), b"\x11\x00")
        self.assertEqual(bf.from_bytes(x.as_bytes()), x)

    def test_bytearray(self):
        bf = Bitfield("bf", 2, [("a", 3), ("b", 5)])
        x = bf(1, 2)
        self.assertIsInstance(x.as_bytearray(), bytearray)
        self.assertEqual(x.as_bytearray(), bytearray(b"\x11\x00"))
        self.assertEqual(bf.from_bytearray(x.as_bytearray()), x)

    def test_bitaray(self):
        bf = Bitfield("bf", 2, [("a", 3), ("b", 5)])
        x = bf(1, 2)
        self.assertIsInstance(x.as_bitarray(), bitarray)
        self.assertEqual(x.as_bitarray().endian(), "little")
        self.assertEqual(x.as_bitarray(), bitarray(b"1000100000000000", endian="little"))
        self.assertEqual(bf.from_bitarray(x.as_bitarray()), x)

    def test_repr(self):
        bf = Bitfield("bf", 2, [("a", 3), ("b", 5)])
        x = bf(1, 2)
        self.assertEqual(repr(x), "<%s.bf a=001 b=00010>" % __name__)
