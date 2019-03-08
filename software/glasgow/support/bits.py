import sys
import types
import unittest
from collections import OrderedDict
from bitarray import bitarray


__all__ = ["Bitfield"]


class _Bitfield:
    @classmethod
    def _build_fields(cls, size_bits, fields):
        total_width = sum(width for name, width in fields)
        if total_width != size_bits:
            raise TypeError("sum of field widths (%d) does not match declared bitfield width (%d)" % (total_width, size_bits))

        cls._size_bits = size_bits
        cls._size_bytes = (size_bits + 7) // 8
        cls._named_fields = []
        cls._widths = OrderedDict()

        bit = 0
        for name, width in fields:
            if name is None:
                name = "_padding_%d" % bit
            else:
                cls._named_fields.append(name)

            cls._create_field(name, bit, width)
            bit += width

    @classmethod
    def _create_field(cls, name, start, width):
        cls._widths[name] = width
        end = start + width
        num_bytes = (width + 7) // 8
        max_int = (1 << width) - 1

        @property
        def getter(self):
            return int.from_bytes(self._bits[start:end].tobytes(), "little")

        @getter.setter
        def setter(self, value):
            if isinstance(value, bitarray):
                if value.length() != width:
                    raise ValueError("field requires %d-bit bitarray, got %d instead" % (
                        width, value.length()))
                self._bits[start:end] = b
            else:
                if value > max_int or value < 0:
                    raise OverflowError("int %d does not fit in %d bits" % (value, width))
                b = bitarray(endian="little")
                b.frombytes(value.to_bytes(num_bytes, "little"))
                self._bits[start:end] = b[:width]

        setattr(cls, name, setter)

    @classmethod
    def from_int(cls, data):
        if data >= (1 << cls._size_bits) or data < 0:
            raise OverflowError("int %d does not fit in %d bits" % (data, cls._size_bits))
        return cls.from_bytes(data.to_bytes(cls._size_bytes, "little"))

    @classmethod
    def from_bytearray(cls, data):
        return cls.from_bytes(bytes(data))

    @classmethod
    def from_bytes(cls, data):
        if len(data) != cls._size_bytes:
            raise ValueError("need %d bytes to fill Bitfield" % cls._size_bytes)
        b = bitarray(endian="little")
        b.frombytes(data)
        return cls.from_bitarray(b[:cls._size_bits])

    @classmethod
    def from_bitarray(cls, data):
        if data.length() != cls._size_bits:
            raise ValueError("Bitfield requires %d-bit bitarray" % cls._size_bits)
        assert data.endian() == "little"
        pack = cls()
        pack._bits = bitarray(data, endian="little")
        return pack

    @classmethod
    def bit_length(cls):
        return cls._size_bits

    def __init__(self, *args, **kwargs):
        self._bits = bitarray(self._size_bits, endian="little")
        self._bits.setall(0)

        if len(args) > len(self._named_fields):
            raise TypeError("too many arguments for field count (%d > %d)" % (len(args), len(self._named_fields)))

        already_set = set()
        for i, v in enumerate(args):
            field = self._named_fields[i]
            setattr(self, field, v)
            already_set.add(field)

        for k,v in kwargs.items():
            if k not in self._widths:
                raise TypeError("unknown field name %s" % k)
            if k in already_set:
                raise TypeError("got multiple values for field %s" % k)
            setattr(self, k, v)

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
            if omit_zero and not f_value:
                continue

            fields.append("{}={:0{}b}".format(name, value, width))

        return " ".join(fields)

    def __repr__(self):
        return "<{}.{} {}>".format(self.__module__, self.__class__.__name__, self.bits_repr())

    def __eq__(self, other):
        return self._bits[:] == other._bits[:]

    def __ne__(self, other):
        return self._bits[:] != other._bits[:]


def Bitfield(name, size_bits, fields):
    mod = sys._getframe(1).f_globals["__name__"] # see namedtuple()

    cls = types.new_class(name, (_Bitfield,))
    cls.__module__ = mod
    cls._build_fields(size_bits, fields)

    return cls

# -------------------------------------------------------------------------------------------------

class BitfieldTestCase(unittest.TestCase):
    def test_definition(self):
        bf = Bitfield("bf", 10, [("a", 3), ("b", 5), (None, 2)])
        self.assertEqual(bf.__name__, "bf")
        self.assertEqual(bf.__module__, __name__)
        x = bf(1, 2)
        self.assertEqual(x.a, 1)
        self.assertEqual(x.b, 2)
        self.assertEqual(bf.bit_length(), 10)
        self.assertEqual(x.bit_length(), 10)

    def test_misuse(self):
        with self.assertRaises(TypeError):
            Bitfield("bf", 10, [("a", 3), ("b", 5)])

        bf = Bitfield("bf", 10, [("a", 3), ("b", 5), (None, 2)])

        with self.assertRaises(TypeError):
            bf(1, 2, b=3)

        with self.assertRaises(TypeError):
            bf(c=3)

        x = bf()
        with self.assertRaises(OverflowError):
            x.a = -1
        with self.assertRaises(OverflowError):
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
        with self.assertRaises(OverflowError):
            bf.from_int(-1)
        with self.assertRaises(OverflowError):
            bf.from_int(1<<10)

    def test_kwargs(self):
        bf = Bitfield("bf", 8, [("a", 3), ("b", 5)])
        x = bf(a=1, b=2)
        self.assertEqual(x.a, 1)
        self.assertEqual(x.b, 2)

    def test_large(self):
        bf = Bitfield("bf", 72, [(None, 8), ("a", 64)])
        val = (3 << 62) + 1
        x = bf(val)
        self.assertEqual(x.to_int(), val << 8)

    def test_huge(self):
        bf = Bitfield("bf", 2080, [("e", 32), ("m", 2048)])
        x = bf(65537, (30<<2048) // 31)
        self.assertEqual(x.e, 65537)
        self.assertEqual(x.m, (30<<2048) // 31)

    def test_reserved(self):
        bf = Bitfield("bf", 64, [(None, 1), ("a", 1), (None, 62)])
        x = bf(1)
        self.assertEqual(repr(x), "<%s.bf a=1>" % __name__)

    def test_bytes(self):
        bf = Bitfield("bf", 8, [("a", 3), ("b", 5)])
        x = bf(1, 2)
        self.assertIsInstance(x.to_bytes(), bytes)
        self.assertEqual(x.to_bytes(), b"\x11")
        self.assertEqual(bf.from_bytes(x.to_bytes()), x)

    def test_bytearray(self):
        bf = Bitfield("bf", 8, [("a", 3), ("b", 5)])
        x = bf(1, 2)
        self.assertIsInstance(x.to_bytearray(), bytearray)
        self.assertEqual(x.to_bytearray(), bytearray(b"\x11"))
        self.assertEqual(bf.from_bytearray(x.to_bytearray()), x)

    def test_int(self):
        bf = Bitfield("bf", 8, [("a", 3), ("b", 5)])
        x = bf(1, 2)
        self.assertIsInstance(x.to_int(), int)
        self.assertEqual(x.to_int(), 17)
        self.assertEqual(bf.from_int(x.to_int()), x)

    def test_bitaray(self):
        bf = Bitfield("bf", 10, [("a", 3), ("b", 7)])
        x = bf(1, 2)
        self.assertIsInstance(x.to_bitarray(), bitarray)
        self.assertEqual(x.to_bitarray().endian(), "little")
        self.assertEqual(x.to_bitarray(), bitarray(b"1000100000", endian="little"))
        self.assertEqual(bf.from_bitarray(x.to_bitarray()), x)

    def test_repr(self):
        bf = Bitfield("bf", 8, [("a", 3), ("b", 5)])
        x = bf(1, 2)
        self.assertEqual(repr(x), "<%s.bf a=001 b=00010>" % __name__)

    def test_copy(self):
        bf = Bitfield("bf", 8, [("a", 3), ("b", 5)])
        x1 = bf(1, 2)
        x2 = x1.copy()
        self.assertFalse(x1 is x2)
        self.assertEqual(x1, x2)
