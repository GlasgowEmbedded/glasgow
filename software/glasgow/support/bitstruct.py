import sys
import types
from collections import OrderedDict
from bitarray import bitarray


__all__ = ["bitstruct"]


class _bitstruct:
    @staticmethod
    def _check_bytes(action, expected_length, value):
        if len(value) != expected_length:
            raise ValueError("%s requires %d-byte array, got %d-byte (%s)"
                             % (action, expected_length, len(value), value.hex()))

    @staticmethod
    def _check_bitarray(action, expected_width, value):
        assert isinstance(value, bitarray)
        if value.length() != expected_width:
            raise ValueError("%s requires %d-bit bitarray, got %d-bit (%s)"
                             % (action, expected_width, len(value), value.to01()))

    @staticmethod
    def _check_integer(action, expected_width, value):
        assert isinstance(value, int)
        if value < 0:
            raise ValueError("%s requires a non-negative integer, got %d"
                             % (action, value))
        if value.bit_length() > expected_width:
            raise ValueError("%s requires a %d-bit integer, got %d-bit (%d)"
                             % (action, expected_width, value.bit_length(), value))

    @classmethod
    def _define_fields(cls, declared_bits, fields):
        total_bits = sum(width for name, width in fields)
        if total_bits != declared_bits:
            raise TypeError("declared width is %d bits, but sum of field widths is %d bits"
                            % (declared_bits, total_bits))

        cls._size_bits = declared_bits
        cls._size_bytes = (declared_bits + 7) // 8
        cls._named_fields = []
        cls._widths = OrderedDict()

        bit = 0
        for name, width in fields:
            if name is None:
                name = "_padding_%d" % bit
            else:
                cls._named_fields.append(name)

            cls._define_field(name, bit, width)
            bit += width

    @classmethod
    def _define_field(cls, name, start, width):
        cls._widths[name] = width
        end = start + width
        num_bytes = (width + 7) // 8

        @property
        def getter(self):
            return int.from_bytes(self._bits[start:end].tobytes(), "little")

        @getter.setter
        def setter(self, value):
            if isinstance(value, bitarray):
                cls._check_bitarray("field assignment", width, value)
                self._bits[start:end] = b
            else:
                cls._check_integer("field assignment", width, value)
                b = bitarray(endian="little")
                b.frombytes(value.to_bytes(num_bytes, "little"))
                self._bits[start:end] = b[:width]

        setattr(cls, name, setter)

    @classmethod
    def from_bitarray(cls, value):
        cls._check_bitarray("initialization", cls._size_bits, value)
        # Bitarray copy is byte-wise, so endianness of input matters for fractional byte bitarrays.
        assert value.endian() == "little"
        pack = cls()
        pack._bits = bitarray(value, endian="little")
        return pack

    @classmethod
    def from_bytes(cls, value):
        cls._check_bytes("initialization", cls._size_bytes, value)
        b = bitarray(endian="little")
        b.frombytes(value)
        return cls.from_bitarray(b[:cls._size_bits])

    @classmethod
    def from_bytearray(cls, value):
        return cls.from_bytes(bytes(value))

    @classmethod
    def from_int(cls, value):
        cls._check_integer("initialization", cls._size_bits, value)
        return cls.from_bytes(value.to_bytes(cls._size_bytes, "little"))

    @classmethod
    def bit_length(cls):
        return cls._size_bits

    def __init__(self, *args, **kwargs):
        self._bits = bitarray(self._size_bits, endian="little")
        self._bits.setall(0)

        if len(args) + len(kwargs)  > len(self._named_fields):
            raise TypeError("constructor got %d arguments, but bitfield only has %d fields"
                            % (len(args) + len(kwargs), len(self._named_fields)))

        already_set = set()
        for index, value in enumerate(args):
            name = self._named_fields[index]
            setattr(self, name, value)
            already_set.add(name)

        for name, value in kwargs.items():
            if name not in self._widths:
                raise TypeError("keyword argument %s refers to a nonexistent field" % name)
            if name in already_set:
                raise TypeError("field %s already set by a positional argument" % name)
            setattr(self, name, value)

    def to_bitarray(self):
        return bitarray(self._bits, endian="little")

    def to_bytes(self):
        return self._bits.tobytes()

    def to_bytearray(self):
        return bytearray(self.to_bytes())

    def to_int(self):
        return int.from_bytes(self.to_bytes(), "little")

    def copy(self):
        return self.__class__.from_bitarray(self._bits)

    def bits_repr(self, omit_zero=False, omit_padding=True):
        fields = []
        if omit_padding:
            names = self._named_fields
        else:
            names = self._widths.keys()

        for name in names:
            width = self._widths[name]
            value = getattr(self, name)
            if omit_zero and value == 0:
                continue

            fields.append("{}={:0{}b}".format(name, value, width))

        return " ".join(fields)

    def __repr__(self):
        return "<{}.{} {}>".format(self.__module__, self.__class__.__name__, self.bits_repr())

    def __eq__(self, other):
        return self._bits[:] == other._bits[:]

    def __ne__(self, other):
        return self._bits[:] != other._bits[:]


def bitstruct(name, size_bits, fields):
    mod = sys._getframe(1).f_globals["__name__"] # see namedtuple()

    cls = types.new_class(name, (_bitstruct,))
    cls.__module__ = mod
    cls._define_fields(size_bits, fields)

    return cls

# -------------------------------------------------------------------------------------------------

import unittest


class BitstructTestCase(unittest.TestCase):
    def test_definition(self):
        bf = bitstruct("bf", 10, [("a", 3), ("b", 5), (None, 2)])
        self.assertEqual(bf.__name__, "bf")
        self.assertEqual(bf.__module__, __name__)
        x = bf(1, 2)
        self.assertEqual(x.a, 1)
        self.assertEqual(x.b, 2)
        self.assertEqual(bf.bit_length(), 10)
        self.assertEqual(x.bit_length(), 10)

    def test_misuse(self):
        with self.assertRaises(TypeError):
            bitstruct("bf", 10, [("a", 3), ("b", 5)])

        bf = bitstruct("bf", 10, [("a", 3), ("b", 5), (None, 2)])

        with self.assertRaises(TypeError):
            bf(1, 2, b=3)

        with self.assertRaises(TypeError):
            bf(c=3)

        x = bf()
        with self.assertRaises(ValueError):
            x.a = -1
        with self.assertRaises(ValueError):
            x.a = 8
        with self.assertRaises(ValueError):
            x.a = bitarray("1")
        with self.assertRaises(ValueError):
            x.a = bitarray("1111")

        with self.assertRaises(ValueError):
            bf.from_bytes(bytes(3))
        with self.assertRaises(ValueError):
            bf.from_bytes(bytes(1))
        with self.assertRaises(ValueError):
            bf.from_bytearray(bytes(3))
        with self.assertRaises(ValueError):
            bf.from_bytearray(bytes(1))
        with self.assertRaises(ValueError):
            bf.from_bitarray(bitarray(9))
        with self.assertRaises(ValueError):
            bf.from_bitarray(bitarray(11))
        with self.assertRaises(ValueError):
            bf.from_int(-1)
        with self.assertRaises(ValueError):
            bf.from_int(1<<10)

    def test_kwargs(self):
        bf = bitstruct("bf", 8, [("a", 3), ("b", 5)])
        x = bf(a=1, b=2)
        self.assertEqual(x.a, 1)
        self.assertEqual(x.b, 2)

    def test_large(self):
        bf = bitstruct("bf", 72, [(None, 8), ("a", 64)])
        val = (3 << 62) + 1
        x = bf(val)
        self.assertEqual(x.to_int(), val << 8)

    def test_huge(self):
        bf = bitstruct("bf", 2080, [("e", 32), ("m", 2048)])
        x = bf(65537, (30<<2048) // 31)
        self.assertEqual(x.e, 65537)
        self.assertEqual(x.m, (30<<2048) // 31)

    def test_reserved(self):
        bf = bitstruct("bf", 64, [(None, 1), ("a", 1), (None, 62)])
        x = bf(1)
        self.assertEqual(repr(x), "<%s.bf a=1>" % __name__)

    def test_bytes(self):
        bf = bitstruct("bf", 8, [("a", 3), ("b", 5)])
        x = bf(1, 2)
        self.assertIsInstance(x.to_bytes(), bytes)
        self.assertEqual(x.to_bytes(), b"\x11")
        self.assertEqual(bf.from_bytes(x.to_bytes()), x)

    def test_bytearray(self):
        bf = bitstruct("bf", 8, [("a", 3), ("b", 5)])
        x = bf(1, 2)
        self.assertIsInstance(x.to_bytearray(), bytearray)
        self.assertEqual(x.to_bytearray(), bytearray(b"\x11"))
        self.assertEqual(bf.from_bytearray(x.to_bytearray()), x)

    def test_int(self):
        bf = bitstruct("bf", 8, [("a", 3), ("b", 5)])
        x = bf(1, 2)
        self.assertIsInstance(x.to_int(), int)
        self.assertEqual(x.to_int(), 17)
        self.assertEqual(bf.from_int(x.to_int()), x)

    def test_bitaray(self):
        bf = bitstruct("bf", 10, [("a", 3), ("b", 7)])
        x = bf(1, 2)
        self.assertIsInstance(x.to_bitarray(), bitarray)
        self.assertEqual(x.to_bitarray().endian(), "little")
        self.assertEqual(x.to_bitarray(), bitarray(b"1000100000", endian="little"))
        self.assertEqual(bf.from_bitarray(x.to_bitarray()), x)

    def test_repr(self):
        bf = bitstruct("bf", 8, [("a", 3), ("b", 5)])
        x = bf(1, 2)
        self.assertEqual(repr(x), "<%s.bf a=001 b=00010>" % __name__)

    def test_copy(self):
        bf = bitstruct("bf", 8, [("a", 3), ("b", 5)])
        x1 = bf(1, 2)
        x2 = x1.copy()
        self.assertFalse(x1 is x2)
        self.assertEqual(x1, x2)
