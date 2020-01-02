import sys
import types
import textwrap
from collections import OrderedDict

from .bits import *


__all__ = ["bitstruct"]


class _bitstruct:
    __slots__ = ()

    @staticmethod
    def _check_bits_(action, expected_width, value):
        assert isinstance(value, bits)
        if len(value) != expected_width:
            raise ValueError("%s requires %d bits, got %d bits (%s)"
                             % (action, expected_width, len(value), value))

    @staticmethod
    def _check_int_(action, expected_width, value):
        assert isinstance(value, int)
        if value < 0:
            raise ValueError("%s requires a non-negative integer, got %d"
                             % (action, value))
        if value.bit_length() > expected_width:
            raise ValueError("%s requires a %d-bit integer, got %d-bit (%d)"
                             % (action, expected_width, value.bit_length(), value))

    @staticmethod
    def _check_bytes_(action, expected_length, value):
        assert isinstance(value, (bytes, bytearray, memoryview))
        if len(value) != expected_length:
            raise ValueError("%s requires %d bytes, got %d bytes (%s)"
                             % (action, expected_length, len(value), value.hex()))

    @staticmethod
    def _define_fields_(cls, declared_bits, fields):
        total_bits = sum(width for name, width in fields)
        if total_bits != declared_bits:
            raise TypeError("declared width is %d bits, but sum of field widths is %d bits"
                            % (declared_bits, total_bits))

        cls["_size_bits_"]    = declared_bits
        cls["_size_bytes_"]   = (declared_bits + 7) // 8
        cls["_named_fields_"] = []
        cls["_layout_"]       = OrderedDict()

        offset = 0
        for name, width in fields:
            if name is None:
                name = "padding_%d" % offset
            else:
                cls["_named_fields_"].append(name)
            cls["_layout_"][name] = (offset, width)
            offset += width

        cls["__slots__"] = tuple("_f_{}".format(field) for field in cls["_layout_"])

        code = textwrap.dedent(f"""
        def __init__(self, {", ".join(f"{field}=0" for field in cls["_named_fields_"])}):
            {"; ".join(f"self.{field} = 0"
                       for field in cls["_layout_"] if field not in cls["_named_fields_"])}
            {"; ".join(f"self.{field} = {field}"
                       for field in cls["_layout_"] if field in cls["_named_fields_"])}

        @classmethod
        def from_bits(cls, value):
            cls._check_bits_("initialization", cls._size_bits_, value)
            self = object.__new__(cls)
            {"; ".join(f"self._f_{field} = int(value[{offset}:{offset+width}])"
                       for field, (offset, width) in cls["_layout_"].items())}
            return self

        def to_bits(self):
            value = 0
            {"; ".join(f"value |= self._f_{field} << {offset}"
                       for field, (offset, width) in cls["_layout_"].items())}
            return bits(value, self._size_bits_)
        """)

        for field, (offset, width) in cls["_layout_"].items():
            code += textwrap.dedent(f"""
            @property
            def {field}(self):
                return self._f_{field}

            @{field}.setter
            def {field}(self, value):
                if isinstance(value, bits):
                    self._check_bits_("field assignment", {width}, value)
                else:
                    self._check_int_("field assignment", {width}, value)
                self._f_{field} = int(value)
            """)

        methods = {}
        exec(code, globals(), methods)
        for name, method in methods.items():
            cls[name] = method

    @classmethod
    def from_bytes(cls, value):
        cls._check_bytes_("initialization", cls._size_bytes_, value)
        return cls.from_bits(bits(value, cls._size_bits_))

    from_bytearray = from_bytes

    @classmethod
    def from_int(cls, value):
        cls._check_int_("initialization", cls._size_bits_, value)
        return cls.from_bits(bits(value, cls._size_bits_))

    @classmethod
    def bit_length(cls):
        return cls._size_bits_

    def to_int(self):
        return int(self.to_bits())

    __int__ = to_int

    def to_bytes(self):
        return bytes(self.to_bits())

    __bytes__ = to_bytes

    def to_bytearray(self):
        return bytearray(bytes(self.to_bits()))

    def copy(self):
        return self.__class__.from_bits(self.to_bits())

    def bits_repr(self, omit_zero=False, omit_padding=True):
        fields = []
        if omit_padding:
            names = self._named_fields_
        else:
            names = self._layout_.keys()

        for name in names:
            offset, width = self._layout_[name]
            value = getattr(self, name)
            if omit_zero and value == 0:
                continue

            fields.append("{}={:0{}b}".format(name, value, width))

        return " ".join(fields)

    def __repr__(self):
        return "<{}.{} {}>".format(self.__module__, self.__class__.__name__, self.bits_repr())

    def __eq__(self, other):
        return isinstance(other, self.__class__) and self.to_bits() == other.to_bits()


def bitstruct(name, size_bits, fields):
    mod = sys._getframe(1).f_globals["__name__"] # see namedtuple()

    cls = types.new_class(name, (_bitstruct,),
        exec_body=lambda ns: _bitstruct._define_fields_(ns, size_bits, fields))
    cls.__module__ = mod

    return cls

# -------------------------------------------------------------------------------------------------

import unittest


class BitstructTestCase(unittest.TestCase):
    def test_definition(self):
        bs = bitstruct("bs", 10, [("a", 3), ("b", 5), (None, 2)])
        self.assertEqual(bs.__name__, "bs")
        self.assertEqual(bs.__module__, __name__)
        x = bs(1, 2)
        self.assertEqual(x.a, 1)
        self.assertEqual(x.b, 2)
        self.assertEqual(bs.bit_length(), 10)
        self.assertEqual(x.bit_length(), 10)

    def test_misuse(self):
        with self.assertRaises(TypeError):
            bitstruct("bs", 10, [("a", 3), ("b", 5)])

        bs = bitstruct("bs", 10, [("a", 3), ("b", 5), (None, 2)])

        with self.assertRaises(TypeError):
            bs(1, 2, b=3)

        with self.assertRaises(TypeError):
            bs(c=3)

        x = bs()
        with self.assertRaises(ValueError):
            x.a = -1
        with self.assertRaises(ValueError):
            x.a = 8
        with self.assertRaises(ValueError):
            x.a = bits("1")
        with self.assertRaises(ValueError):
            x.a = bits("1111")

        with self.assertRaises(ValueError):
            bs.from_bytes(bytes(3))
        with self.assertRaises(ValueError):
            bs.from_bytes(bytes(1))
        with self.assertRaises(ValueError):
            bs.from_bits(bits(0, 9))
        with self.assertRaises(ValueError):
            bs.from_bits(bits(0, 11))
        with self.assertRaises(ValueError):
            bs.from_int(-1)
        with self.assertRaises(ValueError):
            bs.from_int(1<<10)

    def test_kwargs(self):
        bs = bitstruct("bs", 8, [("a", 3), ("b", 5)])
        x = bs(a=1, b=2)
        self.assertEqual(x.a, 1)
        self.assertEqual(x.b, 2)

    def test_large(self):
        bs = bitstruct("bs", 72, [(None, 8), ("a", 64)])
        val = (3 << 62) + 1
        x = bs(val)
        self.assertEqual(x.to_int(), val << 8)

    def test_huge(self):
        bs = bitstruct("bs", 2080, [("e", 32), ("m", 2048)])
        x = bs(65537, (30<<2048) // 31)
        self.assertEqual(x.e, 65537)
        self.assertEqual(x.m, (30<<2048) // 31)

    def test_reserved(self):
        bs = bitstruct("bs", 64, [(None, 1), ("a", 1), (None, 62)])
        x = bs(1)
        self.assertEqual(repr(x), "<%s.bs a=1>" % __name__)

    def test_bytes(self):
        bs = bitstruct("bs", 8, [("a", 3), ("b", 5)])
        x = bs(1, 2)
        self.assertIsInstance(x.to_bytes(), bytes)
        self.assertEqual(x.to_bytes(), b"\x11")
        self.assertEqual(bs.from_bytes(x.to_bytes()), x)

    def test_bytearray(self):
        bs = bitstruct("bs", 8, [("a", 3), ("b", 5)])
        x = bs(1, 2)
        self.assertIsInstance(x.to_bytearray(), bytearray)
        self.assertEqual(x.to_bytearray(), bytearray(b"\x11"))
        self.assertEqual(bs.from_bytearray(x.to_bytearray()), x)

    def test_int(self):
        bs = bitstruct("bs", 8, [("a", 3), ("b", 5)])
        x = bs(1, 2)
        self.assertIsInstance(x.to_int(), int)
        self.assertEqual(x.to_int(), 17)
        self.assertEqual(bs.from_int(x.to_int()), x)

    def test_bits(self):
        bs = bitstruct("bs", 10, [("a", 3), ("b", 7)])
        x = bs(1, 2)
        self.assertIsInstance(x.to_bits(), bits)
        self.assertEqual(x.to_bits(), bits("0000010001"))
        self.assertEqual(bs.from_bits(x.to_bits()), x)

    def test_repr(self):
        bs = bitstruct("bs", 8, [("a", 3), ("b", 5)])
        x = bs(1, 2)
        self.assertEqual(repr(x), "<%s.bs a=001 b=00010>" % __name__)

    def test_copy(self):
        bs = bitstruct("bs", 8, [("a", 3), ("b", 5)])
        x1 = bs(1, 2)
        x2 = x1.copy()
        self.assertFalse(x1 is x2)
        self.assertEqual(x1, x2)

    def test_slots(self):
        bs = bitstruct("bs", 8, [("a", 8)])
        x  = bs()
        with self.assertRaises(AttributeError):
            x.b
        with self.assertRaises(AttributeError):
            x.b = 1
