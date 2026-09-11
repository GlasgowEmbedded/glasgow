import enum
import unittest

from glasgow.support.bits import bits
from glasgow.support.bitstruct import bitstruct


class Choice(enum.IntEnum):
    ZERO = 0
    ONE = 1
    THREE = 3


class BitstructTestCase(unittest.TestCase):
    def test_definition(self):
        class bs(bitstruct, width=10):
            a: int  = 3
            b: int  = 5
            _1: int = 2

        self.assertEqual(bs.__name__, "bs")
        self.assertEqual(bs.__module__, __name__)

        x = bs(1, 2)
        self.assertEqual(x.a, 1)
        self.assertEqual(x.b, 2)
        self.assertEqual(bs.bit_length(), 10)
        self.assertEqual(x.bit_length(), 10)

    def test_definition_misuse(self):
        with self.assertRaises(TypeError):
            class missing_width(bitstruct):
                a: int = 1

        with self.assertRaises(TypeError):
            class wrong_total(bitstruct, width=10):
                a: int = 3
                b: int = 5

        with self.assertRaises(TypeError):
            class missing_field_width(bitstruct, width=1):
                a: int

        for invalid_width in (0, -1, 1.0, True):
            with self.subTest(invalid_width=invalid_width), self.assertRaises(TypeError):
                class invalid(bitstruct, width=1):
                    a: int = invalid_width

        with self.assertRaises(TypeError):
            class unsupported_type(bitstruct, width=1):
                a: float = 1

        with self.assertRaises(TypeError):
            class wide_bool(bitstruct, width=2):
                a: bool = 2

        with self.assertRaises(TypeError):
            class reserved_name(bitstruct, width=1):
                to_int: int = 1

        with self.assertRaises(TypeError):
            class duplicate_padding(bitstruct, width=2):
                _1: int = 1
                _1: int = 1

        class base(bitstruct, width=1):
            a: int = 1

        with self.assertRaises(TypeError):
            class subclass(base, width=1):
                b: int = 1

    def test_int_enum_definition_misuse(self):
        class Negative(enum.IntEnum):
            NEGATIVE = -1

        with self.assertRaises(TypeError):
            class negative_enum(bitstruct, width=1):
                value: Negative = 1

        class TooWide(enum.IntEnum):
            FOUR = 4

        with self.assertRaises(TypeError):
            class wide_enum(bitstruct, width=2):
                value: TooWide = 2

    def test_construction_misuse(self):
        class bs(bitstruct, width=10):
            a: int  = 3
            b: int  = 5
            _1: int = 2

        with self.assertRaises(TypeError):
            bs(1, 2, b=3)
        with self.assertRaises(TypeError):
            bs(c=3)
        with self.assertRaises(TypeError):
            bs(1, 2, 3)

        x = bs()
        with self.assertRaises(ValueError):
            x.a = -1
        with self.assertRaises(ValueError):
            x.a = 8
        with self.assertRaises(ValueError):
            x.a = bits("1")
        with self.assertRaises(ValueError):
            x.a = bits("1111")
        with self.assertRaises(TypeError):
            x.a = "1"

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
            bs.from_int(1 << 10)

    def test_kwargs(self):
        class bs(bitstruct, width=8):
            a: int = 3
            b: int = 5

        x = bs(a=1, b=2)
        self.assertEqual(x.a, 1)
        self.assertEqual(x.b, 2)

    def test_bool(self):
        class bs(bitstruct, width=1):
            flag: bool = 1

        self.assertIs(bs().flag, False)
        self.assertIs(bs(flag=True).flag, True)
        self.assertIs(bs(flag=1).flag, True)
        self.assertEqual(bs(flag=True).to_int(), 1)

    def test_int_enum(self):
        class bs(bitstruct, width=2):
            choice: Choice = 2

        self.assertIs(bs().choice, Choice.ZERO)
        self.assertIs(bs(choice=1).choice, Choice.ONE)
        self.assertIs(bs.from_int(3).choice, Choice.THREE)

        with self.assertRaises(ValueError):
            bs.from_int(2)

        with self.assertRaises(ValueError):
            bs(choice=2)

    def test_postponed_annotation(self):
        class bs(bitstruct, width=1):
            a: "int" = 1

        self.assertEqual(bs(a=1).a, 1)

    def test_large(self):
        class bs(bitstruct, width=72):
            _1: int = 8
            a: int  = 64

        val = (3 << 62) + 1
        x = bs(val)
        self.assertEqual(x.to_int(), val << 8)

    def test_huge(self):
        class bs(bitstruct, width=2080):
            e: int = 32
            m: int = 2048

        x = bs(65537, (30 << 2048) // 31)
        self.assertEqual(x.e, 65537)
        self.assertEqual(x.m, (30 << 2048) // 31)

    def test_padding(self):
        class bs(bitstruct, width=64):
            _1: int = 1
            a: int  = 1
            _2: int = 62

        x = bs(1)
        self.assertEqual(repr(x), f"<{__name__}.bs a=1>")
        with self.assertRaises(AttributeError):
            _ = x._1

        decoded = bs.from_int((1 << 63) | 1)
        self.assertEqual(decoded.to_int(), (1 << 63) | 1)
        self.assertIn("_1=1", decoded.bits_repr(omit_padding=False))
        self.assertIn("_2=" + "1" + "0" * 61, decoded.bits_repr(omit_padding=False))

    def test_bytes(self):
        class bs(bitstruct, width=8):
            a: int = 3
            b: int = 5

        x = bs(1, 2)
        self.assertIsInstance(x.to_bytes(), bytes)
        self.assertEqual(x.to_bytes(), b"\x11")
        self.assertEqual(bs.from_bytes(x.to_bytes()), x)

    def test_bytearray(self):
        class bs(bitstruct, width=8):
            a: int = 3
            b: int = 5

        x = bs(1, 2)
        self.assertIsInstance(x.to_bytearray(), bytearray)
        self.assertEqual(x.to_bytearray(), bytearray(b"\x11"))
        self.assertEqual(bs.from_bytearray(x.to_bytearray()), x)

    def test_int(self):
        class bs(bitstruct, width=8):
            a: int = 3
            b: int = 5

        x = bs(1, 2)
        self.assertIsInstance(x.to_int(), int)
        self.assertEqual(x.to_int(), 17)
        self.assertEqual(bs.from_int(x.to_int()), x)

    def test_bits(self):
        class bs(bitstruct, width=10):
            a: int = 3
            b: int = 7

        x = bs(1, 2)
        self.assertIsInstance(x.to_bits(), bits)
        self.assertEqual(x.to_bits(), bits("0000010001"))
        self.assertEqual(bs.from_bits(x.to_bits()), x)

    def test_repr(self):
        class bs(bitstruct, width=8):
            a: int = 3
            b: int = 5

        x = bs(1, 2)
        self.assertEqual(repr(x), f"<{__name__}.bs a=001 b=00010>")

    def test_copy(self):
        class bs(bitstruct, width=8):
            a: int = 3
            b: int = 5

        x1 = bs(1, 2)
        x2 = x1.copy()
        self.assertFalse(x1 is x2)
        self.assertEqual(x1, x2)

    def test_slots(self):
        class bs(bitstruct, width=8):
            a: int = 8

        x = bs()
        with self.assertRaises(AttributeError):
            _ = x.b
        with self.assertRaises(AttributeError):
            x.b = 1
