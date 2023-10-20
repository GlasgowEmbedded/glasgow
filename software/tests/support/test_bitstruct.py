import unittest

from glasgow.support.bits import bits
from glasgow.support.bitstruct import bitstruct


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
