import unittest

from glasgow.support.bits import bits


class BitsTestCase(unittest.TestCase):
    def assertBits(self, value, bit_length, bit_value):
        self.assertIsInstance(value, bits)
        self.assertEqual(value._len_, bit_length)
        self.assertEqual(value._int_, bit_value)

    def test_from_int(self):
        self.assertBits(bits.from_int(0), 0, 0b0)
        self.assertBits(bits.from_int(1), 1, 0b1)
        self.assertBits(bits.from_int(2), 2, 0b10)
        self.assertBits(bits.from_int(2, 5), 5, 0b00010)
        self.assertBits(bits.from_int(0b110, 2), 2, 0b10)
        self.assertBits(bits.from_int(-1, 16), 16, 0xffff)

    def test_from_int_wrong(self):
        with self.assertRaisesRegex(ValueError,
                r"invalid negative input for bits\(\): '-1'"):
            bits.from_int(-1)

    def test_from_str(self):
        self.assertBits(bits.from_str(""), 0, 0b0)
        self.assertBits(bits.from_str("0"), 1, 0b0)
        self.assertBits(bits.from_str("010"), 3, 0b010)
        self.assertBits(bits.from_str("0 1  011_100"), 8, 0b01011100)
        self.assertBits(bits.from_str("+0 1 \t011_100"), 8, 0b01011100)

    def test_from_str_wrong(self):
        with self.assertRaisesRegex(ValueError,
                r"invalid negative input for bits\(\): '-1'"):
            bits.from_str("-1")
        with self.assertRaisesRegex(ValueError,
                r"invalid literal for int\(\) with base 2: '23'"):
            bits.from_str("23")

    def test_from_bytes(self):
        self.assertBits(bits.from_bytes(b"\xa5", 8), 8, 0b10100101)
        self.assertBits(bits.from_bytes(b"\xa5\x01", 9), 9, 0b110100101)
        self.assertBits(bits.from_bytes(b"\xa5\xff", 9), 9, 0b110100101)

    def test_from_iter(self):
        self.assertBits(bits.from_iter(iter([])), 0, 0b0)
        self.assertBits(bits.from_iter(iter([1,1,0,1,0,0,1])), 7, 0b1001011)

    def test_new(self):
        self.assertBits(bits(), 0, 0b0)
        self.assertBits(bits(10), 4, 0b1010)
        self.assertBits(bits(10, 2), 2, 0b10)
        self.assertBits(bits("1001"), 4, 0b1001)
        self.assertBits(bits(b"\xa5\x01", 9), 9, 0b110100101)
        self.assertBits(bits(bytearray(b"\xa5\x01"), 9), 9, 0b110100101)
        self.assertBits(bits(memoryview(b"\xa5\x01"), 9), 9, 0b110100101)
        self.assertBits(bits([1,1,0,1,0,0,1]), 7, 0b1001011)
        self.assertBits(bits(bits("1001"), 2), 2, 0b01)
        some = bits("1001")
        self.assertIs(bits(some), some)

    def test_new_wrong(self):
        with self.assertRaisesRegex(TypeError,
                r"invalid input for bits\(\): cannot convert from float"):
            bits(1.0)
        with self.assertRaisesRegex(ValueError,
                r"invalid input for bits\(\): when converting from str "
                r"length must not be provided"):
            bits("1010", 5)
        with self.assertRaisesRegex(ValueError,
                r"invalid input for bits\(\): when converting from bytes "
                r"length must be provided"):
            bits(b"\xa5")
        with self.assertRaisesRegex(ValueError,
                r"invalid input for bits\(\): when converting from an iterable "
                r"length must not be provided"):
            bits([1,0,1,0], 5)

    def test_len(self):
        self.assertEqual(len(bits(10)), 4)

    def test_bool(self):
        self.assertFalse(bits(""))
        self.assertTrue(bits("1"))
        self.assertTrue(bits("01"))
        self.assertTrue(bits("0"))
        self.assertTrue(bits("00"))

    def test_int(self):
        self.assertEqual(int(bits("1010")), 0b1010)

    def test_str(self):
        self.assertEqual(str(bits("")), "")
        self.assertEqual(str(bits("0000")), "0000")
        self.assertEqual(str(bits("1010")), "1010")
        self.assertEqual(str(bits("01010")), "01010")

    def test_bytes(self):
        self.assertEqual(bytes(bits("")), b"")
        self.assertEqual(bytes(bits("10100101")), b"\xa5")
        self.assertEqual(bytes(bits("110100101")), b"\xa5\x01")

    def test_repr(self):
        self.assertEqual(repr(bits("")), r"bits('')")
        self.assertEqual(repr(bits("1010")), r"bits('1010')")

    def test_getitem_int(self):
        some = bits("10001001011")
        self.assertEqual(some[0], 1)
        self.assertEqual(some[2], 0)
        self.assertEqual(some[5], 0)
        self.assertEqual(some[-1], 1)
        self.assertEqual(some[-2], 0)
        self.assertEqual(some[-5], 1)

    def test_getitem_slice(self):
        some = bits("10001001011")
        self.assertBits(some[:], 11, 0b10001001011)
        self.assertBits(some[2:], 9, 0b100010010)
        self.assertBits(some[2:9], 7, 0b0010010)
        self.assertBits(some[2:-2], 7, 0b0010010)
        self.assertBits(some[3:2], 0, 0b0)

    def test_getitem_wrong(self):
        with self.assertRaisesRegex(TypeError,
                r"bits indices must be integers or slices, not str"):
            bits()["x"]

    def test_iter(self):
        some = bits("10001001011")
        self.assertEqual(list(some), [1,1,0,1,0,0,1,0,0,0,1])

    def test_eq(self):
        self.assertEqual(bits("1010"), 0b1010)
        self.assertEqual(bits("1010"), "1010")
        self.assertEqual(bits("1010"), bits("1010"))
        self.assertNotEqual(bits("0010"), 0b0010)
        self.assertNotEqual(bits("0010"), "010")
        self.assertNotEqual(bits("1010"), bits("01010"))
        self.assertNotEqual(bits("1010"), None)

    def test_add(self):
        self.assertBits(bits("1010") + bits("1110"), 8, 0b11101010)
        self.assertBits(bits("1010") + (0,1,1,1), 8, 0b11101010)
        self.assertBits((0,1,1,1) + bits("1010"), 8, 0b10101110)

    def test_mul(self):
        self.assertBits(bits("1011") * 4, 16, 0b1011101110111011)
        self.assertBits(4 * bits("1011"), 16, 0b1011101110111011)

    def test_and(self):
        self.assertBits(bits("1010") & bits("1100"), 4, 0b1000)
        self.assertBits(bits("1010") & "1100", 4, 0b1000)
        self.assertBits((0,1,0,1) & bits("1100"), 4, 0b1000)

    def test_or(self):
        self.assertBits(bits("1010") | bits("1100"), 4, 0b1110)
        self.assertBits(bits("1010") | "1100", 4, 0b1110)
        self.assertBits((0,1,0,1) | bits("1100"), 4, 0b1110)

    def test_xor(self):
        self.assertBits(bits("1010") ^ bits("1100"), 4, 0b0110)
        self.assertBits(bits("1010") ^ "1100", 4, 0b0110)
        self.assertBits((0,1,0,1) ^ bits("1100"), 4, 0b0110)

    def test_reversed(self):
        self.assertBits(bits("1010").reversed(), 4, 0b0101)

    def test_find(self):
        self.assertEqual(bits("1011").find(bits("11")), 0)
        self.assertEqual(bits("1011").find(bits("10")), 2)
        self.assertEqual(bits("1011").find(bits("01")), 1)
        self.assertEqual(bits("1011").find(bits("00")), -1)

        self.assertEqual(bits("101100101").find(bits("10"), 0), 1)
        self.assertEqual(bits("101100101").find(bits("10"), 2), 4)
        self.assertEqual(bits("101100101").find(bits("10"), 5), 7)
        self.assertEqual(bits("101100101").find(bits("10"), 8), -1)

        self.assertEqual(bits("1011").find(bits((1,0))), 1)
