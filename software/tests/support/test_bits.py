import unittest

from glasgow.support.bits import bits, bitarray, _byte_len


class BitsTestCase(unittest.TestCase):
    def assertBits(self, value, bit_length, bit_value):
        self.assertIsInstance(value, bits)
        self.assertEqual(value._len, bit_length)
        self.assertEqual(value._bytes, bit_value.to_bytes(_byte_len(bit_length), 'little'))

    def test_from_int(self):
        self.assertBits(bits.from_int(0), 0, 0b0)
        self.assertBits(bits.from_int(1), 1, 0b1)
        self.assertBits(bits.from_int(2), 2, 0b10)
        self.assertBits(bits.from_int(2, 5), 5, 0b00010)
        self.assertBits(bits.from_int(0b110, 2), 2, 0b10)
        self.assertBits(bits.from_int(-1, 16), 16, 0xffff)
        self.assertBits(bits.from_int(-1, 5), 5, 0x1f)

    def test_from_int_wrong(self):
        with self.assertRaisesRegex(ValueError,
                r"invalid negative input for bits\(\): '-1'"):
            bits.from_int(-1)

    def test_from_str(self):
        self.assertBits(bits.from_str(""), 0, 0b0)
        self.assertBits(bits.from_str("0"), 1, 0b0)
        self.assertBits(bits.from_str("010"), 3, 0b010)
        self.assertBits(bits.from_str("0 1  011_100"), 8, 0b01011100)
        self.assertBits(bits.from_str("0 1 \t011_100"), 8, 0b01011100)

    def test_from_str_wrong(self):
        with self.assertRaisesRegex(ValueError,
                r"invalid input for bits\(\): '-1'"):
            bits.from_str("-1")
        with self.assertRaisesRegex(ValueError,
                r"invalid input for bits\(\): '23'"):
            bits.from_str("23")

    def test_from_bytes(self):
        self.assertBits(bits.from_bytes(b"\xa5", 8), 8, 0b10100101)
        self.assertBits(bits.from_bytes(b"\xa5\x01", 9), 9, 0b110100101)
        self.assertBits(bits.from_bytes(b"\xa5\x01"), 16, 0b110100101)

    def test_from_bytes_wrong(self):
        with self.assertRaisesRegex(ValueError,
                r"wrong padding in the last byte"):
            bits.from_bytes(b"\xa5\xff", 9)
        with self.assertRaisesRegex(ValueError,
                r"wrong bytes length 2 for bits of length 20"):
            bits.from_bytes(b"\xa5\xff", 20)

    def test_from_iter(self):
        self.assertBits(bits.from_iter(iter([])), 0, 0b0)
        self.assertBits(bits.from_iter(iter([1,1,0,1,0,0,1])), 7, 0b1001011)
        self.assertBits(bits.from_iter(iter([1,1,0,1,0,0,1,1])), 8, 0b11001011)
        self.assertBits(bits.from_iter(iter([1,1,0,1,0,0,1,1,1,0,1,0,0,1,1])), 15, 0b110010111001011)
        self.assertBits(bits.from_iter(iter([True, False, True])), 3, 0b101)

    def test_from_iter_wrong(self):
        with self.assertRaisesRegex(ValueError,
                r"bits can only contain 0 and 1"):
            bits.from_iter([0, 2, 1])

    def test_new(self):
        self.assertBits(bits(), 0, 0b0)
        self.assertBits(bits(10), 4, 0b1010)
        self.assertBits(bits(10, 2), 2, 0b10)
        self.assertBits(bits("1001"), 4, 0b1001)
        self.assertBits(bits(b"\xa5\x01", 9), 9, 0b110100101)
        self.assertBits(bits(bytearray(b"\xa5\x01"), 9), 9, 0b110100101)
        self.assertBits(bits(memoryview(b"\xa5\x01"), 9), 9, 0b110100101)
        self.assertBits(bits(b"\xa5\x01"), 16, 0b0000000110100101)
        self.assertBits(bits([1,1,0,1,0,0,1]), 7, 0b1001011)
        some = bits("1001")
        self.assertIs(bits(some), some)
        self.assertIsNot(bitarray(some), some)

    def test_new_wrong(self):
        with self.assertRaisesRegex(TypeError,
                r"invalid input for bits\(\): cannot convert from float"):
            bits(1.0)
        with self.assertRaisesRegex(ValueError,
                r"invalid input for bits\(\): when converting from bits "
                r"length must not be provided"):
            bits(bits("1010"), 5)
        with self.assertRaisesRegex(ValueError,
                r"invalid input for bits\(\): when converting from str "
                r"length must not be provided"):
            bits("1010", 5)
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
        self.assertEqual(int(bits("000100100011")), 0x123)

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
        self.assertBits(some[::-1], 11, 0b11010010001)
        self.assertBits(some[2:], 9, 0b100010010)
        self.assertBits(some[2:9], 7, 0b0010010)
        self.assertBits(some[2:-2], 7, 0b0010010)
        self.assertBits(some[3:2], 0, 0b0)
        self.assertBits(some[::2], 6, 0b101001)
        self.assertBits(some[1::2], 5, 0b00011)
        some = bits(b'\xaa\x99\x55\x66')
        self.assertBits(some[8:24], 16, 0b0101010110011001)
        self.assertBits(some[23:7:-1], 16, 0b1001100110101010)
        self.assertBits(some[::-1], 32, 0b01010101100110011010101001100110)

    def test_getitem_wrong(self):
        with self.assertRaisesRegex(TypeError,
                r"bits indices must be integers or slices, not str"):
            bits()["x"]

    def test_iter(self):
        some = bits("10001001011")
        self.assertEqual(list(some), [1,1,0,1,0,0,1,0,0,0,1])

    def test_eq(self):
        self.assertEqual(bits("1010"), bits("1010"))
        self.assertNotEqual(bits("1010"), 0b1010)
        self.assertNotEqual(bits("1010"), "1010")
        self.assertNotEqual(bits("1010"), bits("01010"))
        self.assertNotEqual(bits("1010"), None)

    def test_add(self):
        self.assertBits(bits("1010") + bits("1110"), 8, 0b11101010)
        self.assertBits(bits("1010") + (0,1,1,1), 8, 0b11101010)
        self.assertBits((0,1,1,1) + bits("1010"), 8, 0b10101110)
        self.assertEqual(bits(b"\x10\x32") + bits(b"\x54\x06", 12), bits(b"\x10\x32\x54\x06", 28))
        self.assertEqual("01010101" + bits("1010"), bits("101001010101"))

    def test_mul(self):
        self.assertBits(bits("1011") * 4, 16, 0b1011101110111011)
        self.assertBits(4 * bits("1011"), 16, 0b1011101110111011)
        self.assertEqual(bits(b"\x55\xaa") * 4, bits(b"\x55\xaa" * 4))

    def test_and(self):
        self.assertBits(bits("1010") & bits("1100"), 4, 0b1000)
        self.assertBits(bits("1010") & "1100", 4, 0b1000)
        self.assertBits((0,1,0,1) & bits("1100"), 4, 0b1000)

    def test_and_wrong(self):
        with self.assertRaisesRegex(ValueError, r'mismatched bitwise operator widths'):
            bits("10101") & bits("1100")

    def test_or(self):
        self.assertBits(bits("1010") | bits("1100"), 4, 0b1110)
        self.assertBits(bits("1010") | "1100", 4, 0b1110)
        self.assertBits((0,1,0,1) | bits("1100"), 4, 0b1110)

    def test_xor(self):
        self.assertBits(bits("1010") ^ bits("1100"), 4, 0b0110)
        self.assertBits(bits("1010") ^ "1100", 4, 0b0110)
        self.assertBits((0,1,0,1) ^ bits("1100"), 4, 0b0110)

    def test_not(self):
        self.assertBits(~bits(), 0, 0)
        self.assertBits(~bits("1010"), 4, 0b0101)
        self.assertBits(~bits("01010101"), 8, 0b10101010)
        self.assertBits(~bits("001100100001"), 12, 0b110011011110)

    def test_reversed(self):
        self.assertBits(bits("1010").reversed(), 4, 0b0101)
        self.assertBits(bits("10101100").reversed(), 8, 0b00110101)
        self.assertEqual(bits(b"\x99\x55").reversed(), bits(b"\xaa\x99"))

    def test_byte_reversed(self):
        self.assertBits(bits("10101100").byte_reversed(), 8, 0b00110101)
        self.assertEqual(bits(b"\x99\x55").byte_reversed(), bits(b"\x99\xaa"))

    def test_find(self):
        self.assertEqual(bits("1011").find(bits("11")), 0)
        self.assertEqual(bits("1011").find(bits("10")), 2)
        self.assertEqual(bits("1011").find(bits("01")), 1)
        self.assertEqual(bits("1011").find(bits("00")), -1)
        self.assertEqual(bits("1011").find(1), 0)
        self.assertEqual(bits("1011").find(0), 2)

        self.assertEqual(bits("101100101").find(bits("10"), 0), 1)
        self.assertEqual(bits("101100101").find(bits("10"), 2), 4)
        self.assertEqual(bits("101100101").find(bits("10"), 5), 7)
        self.assertEqual(bits("101100101").find(bits("10"), 8), -1)

        self.assertEqual(bits("101100101").find(bits("10"), 2, 4), -1)
        self.assertEqual(bits("101100101").find(bits("10"), 2, 5), 4)

        self.assertEqual(bits("1011").find((1,0)), 1)
        self.assertEqual(bits("1011").find("01"), 1)

    def test_index(self):
        self.assertEqual(bits("1011").index(bits("11")), 0)
        self.assertEqual(bits("1011").index(bits("10")), 2)
        self.assertEqual(bits("1011").index(bits("01")), 1)
        with self.assertRaises(ValueError):
            bits("1011").index(bits("00"))


class BitarrayTestCase(unittest.TestCase):
    def assertBitarray(self, value, bit_length, bit_value):
        self.assertIsInstance(value, bitarray)
        self.assertEqual(value._len, bit_length)
        self.assertEqual(value._bytes, bit_value.to_bytes(_byte_len(bit_length), 'little'))

    def test_new(self):
        self.assertBitarray(bitarray(), 0, 0b0)
        self.assertBitarray(bitarray(10), 4, 0b1010)
        self.assertBitarray(bitarray(10, 2), 2, 0b10)
        self.assertBitarray(bitarray("1001"), 4, 0b1001)
        self.assertBitarray(bitarray(b"\xa5\x01", 9), 9, 0b110100101)
        self.assertBitarray(bitarray(bytearray(b"\xa5\x01"), 9), 9, 0b110100101)
        self.assertBitarray(bitarray(memoryview(b"\xa5\x01"), 9), 9, 0b110100101)
        self.assertBitarray(bitarray(b"\xa5\x01"), 16, 0b0000000110100101)
        self.assertBitarray(bitarray([1,1,0,1,0,0,1]), 7, 0b1001011)
        some = bitarray("1001")
        self.assertIsNot(bitarray(some), some)
        self.assertIsNot(bits(some), some)

    def test_setitem(self):
        some = bitarray("001100100001")
        some[1] = 1
        self.assertBitarray(some, 12, 0b001100100011)
        some[1] = 0
        self.assertBitarray(some, 12, 0b001100100001)
        some[-1] = 1
        self.assertBitarray(some, 12, 0b101100100001)
        some[11] = 0
        self.assertBitarray(some, 12, 0b001100100001)

    def test_setitem_wrong(self):
        some = bitarray("001100100001")
        with self.assertRaises(IndexError):
            some[12] = 0
        with self.assertRaises(IndexError):
            some[-13] = 0
        with self.assertRaises(ValueError):
            some[0] = 2
        with self.assertRaises(TypeError):
            some[0] = "0"
        with self.assertRaises(TypeError):
            some["0"] = 0
        with self.assertRaises(TypeError):
            some[::] = 0.0
        with self.assertRaises(ValueError):
            some[6:2:-1] = "00000"

    def test_setitem_slice(self):
        some = bitarray(b"\xaa\x99\x55\x66")
        some[:] = bits("1010")
        self.assertBitarray(some, 4, 0b1010)

        some = bitarray(b"\xaa\x99\x55\x66")
        some[16:] = bits("1010")
        self.assertBitarray(some, 20, 0b10101001100110101010)

        some = bitarray(b"\xaa\x99\x55\x66")[:-3]
        some[16:24] = bits(b"\x77\x88")
        self.assertBitarray(some, 37, int.from_bytes(b"\xaa\x99\x77\x88\x06", "little"))

        some = bitarray("01010101")
        some[2:6] = bits("1010")
        self.assertBitarray(some, 8, 0b01101001)

        some = bitarray("01010101")
        some[2:6] = bits("101010")
        self.assertBitarray(some, 10, 0b0110101001)

        some = bitarray("01010101")
        some[4:] = bits()
        self.assertBitarray(some, 4, 0b0101)

        some = bitarray("010101")
        some[6:] = bits("1111")
        self.assertBitarray(some, 10, 0b1111010101)

        some = bitarray("010101")
        some[6:] = "1001"
        self.assertBitarray(some, 10, 0b1001010101)

        some = bitarray("11111111")
        some[2:6] = 2
        self.assertBitarray(some, 8, 0b11001011)

        some = bitarray("0000")
        some[::-1] = bits("1010")
        self.assertBitarray(some, 4, 0b0101)

        some = bitarray("0000")
        some[2::-2] = "11"
        self.assertBitarray(some, 4, 0b0101)

    def test_delitem(self):
        some = bitarray("01010101")
        del some[2]
        self.assertBitarray(some, 7, 0b0101001)
        del some[-2]
        self.assertBitarray(some, 6, 0b001001)

        some = bitarray("01101001")
        del some[3:2]
        self.assertBitarray(some, 8, 0b01101001)
        del some[2:6]
        self.assertBitarray(some, 4, 0b0101)

        some = bitarray("01011010")
        del some[::-2]
        self.assertBitarray(some, 4, 0b1100)
        some = bitarray("01011010")
        del some[::2]
        self.assertBitarray(some, 4, 0b0011)

        some = bitarray(b"\xaa\x99\x55\x66")
        del some[20:]
        self.assertBitarray(some, 20, 0b01011001100110101010)
        some = bitarray(b"\xaa\x99\x55\x66")
        del some[16:]
        self.assertBitarray(some, 16, 0b1001100110101010)
        some = bitarray(b"\xaa\x99\x55\x66")
        del some[8:24]
        self.assertBitarray(some, 16, 0b0110011010101010)

    def test_delitem_wrong(self):
        some = bitarray("001100100001")
        with self.assertRaises(IndexError):
            del some[12]
        with self.assertRaises(IndexError):
            del some[-13]
        with self.assertRaises(TypeError):
            del some["0"]

    def test_insert(self):
        some = bitarray("01010101")
        some.insert(4, 1)
        self.assertBitarray(some, 9, 0b010110101)

        some = bitarray("01010101")
        some.append(1)
        self.assertBitarray(some, 9, 0b101010101)
        some.append(1)
        self.assertBitarray(some, 10, 0b1101010101)
        some.append(0)
        self.assertBitarray(some, 11, 0b01101010101)
        some.insert(-1, 1)
        self.assertBitarray(some, 12, 0b011101010101)

    def test_insert_wrong(self):
        some = bitarray("01010101")
        with self.assertRaises(TypeError):
            some.insert("a", 1)
        with self.assertRaises(TypeError):
            some.insert(0, "a")
        with self.assertRaises(ValueError):
            some.insert(0, 2)

    def test_clear(self):
        some = bitarray("1010")
        some.clear()
        self.assertBitarray(some, 0, 0)

    def test_setall(self):
        some = bitarray("101010101010")
        some.setall(1)
        self.assertBitarray(some, 12, 0b111111111111)

        some = bitarray("101010101010")
        some.setall(0)
        self.assertBitarray(some, 12, 0)

    def test_reverse(self):
        some = bitarray("101001")
        some.reverse()
        self.assertBitarray(some, 6, 0b100101)

        some = bitarray(b"\xaa\x99\x55\x66")
        some.reverse()
        self.assertEqual(some, bits(b"\x66\xaa\x99\x55"))

    def test_byte_reverse(self):
        some = bitarray("101001")
        with self.assertRaises(ValueError):
            some.byte_reverse()

        some = bitarray(b"\xaa\x99\x55\x66")
        some.byte_reverse()
        self.assertEqual(some, bits(b"\x55\x99\xaa\x66"))

    def test_extend(self):
        some = bitarray("1011")
        some += [1, 0]
        self.assertBitarray(some, 6, 0b011011)

    def test_imul(self):
        some = bitarray("1011")
        some *= 1
        self.assertBitarray(some, 4, 0b1011)
        some *= 3
        self.assertBitarray(some, 12, 0b101110111011)
        some *= 0
        self.assertBitarray(some, 0, 0)

        some = bitarray(b"\x55\xaa")
        some *= 3
        self.assertEqual(some, bits(b"\x55\xaa\x55\xaa\x55\xaa"))

    def test_imul_wrong(self):
        some = bitarray("1011")
        with self.assertRaises(TypeError):
            some *= "a"
        with self.assertRaises(ValueError):
            some *= -1

    def test_iand(self):
        some = bitarray("1010")
        some &= 0xc
        self.assertBitarray(some, 4, 0b1000)

    def test_ior(self):
        some = bitarray("1010")
        some |= 0xc
        self.assertBitarray(some, 4, 0b1110)

    def test_ixor(self):
        some = bitarray("1010")
        some ^= 0xc
        self.assertBitarray(some, 4, 0b0110)
