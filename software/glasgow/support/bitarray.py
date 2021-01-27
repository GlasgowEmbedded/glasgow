import re
import operator
from functools import reduce
import collections.abc
from array import array


__all__ = ["bitarray"]


class bitarray:
    """A mutable class to efficiently represent an array of booleans
    
    This bit sequence is ordered from LSB to MSB; this is the direction in which it is converted
    to and from iterators, and to and from bytes. Note, however, that it is converted to and from
    strings (which should be only used where a human-readable form is required) from MSB to LSB;
    this matches the way integer literals are written, as well as values in datasheets and other
    documentation.
    """
    __slots__ = ["_len_", "_array_"]
    
    @staticmethod
    def __copy_bit_slice(src, start=0, length=None, dst=None):
        # Reduce larger-than-byte start bit offsets to a single case
        if start // 8:
            src = memoryview(src)[start//8:]
            start %= 8
        # Length is limited by the size of the input data. From it we also
        # compute the number of bytes needed to retrieve the requested slice
        if length is None:
            length = 8 * len(src) - start
        else:
            length = min(length, 8*len(src)-start)
        src_bytes = ((length + start - 1) // 8) + 1
        dst_bytes = ((length - 1) // 8) + 1
        rem_bits = length % 8
        if dst is None:
            dst = array('B', bytes(dst_bytes))
        if length == 0:
            return dst
        # Perform actual copy considering that the start bit might be
        # aligned to byte boundaries. In that case it is done with a
        # regular copy, otherwise we have to merge adjacent bytes.
        out = memoryview(dst)
        if start == 0:
            out[:dst_bytes] = src[:dst_bytes]
        else:
            for i in range(src_bytes-1):
                out[i] = ((src[i] >> start) | (src[i+1] << (8-start))) & 0xFF
            if src_bytes == dst_bytes:
                out[dst_bytes-1] = src[dst_bytes-1] >> start
        # Mask the last byte when length is not multiple of a byte.
        if rem_bits:
            out[dst_bytes-1] &= ~(-1 << rem_bits)
        return dst

    @classmethod
    def from_int(cls, value, length=None):
        value = operator.index(value)
        if length is None:
            if value < 0:
                raise ValueError("invalid negative input for bitarray(): '{}'".format(value))
            length = value.bit_length()
        else:
            length = operator.index(length)
            value &= ~(-1 << length)
        bytelen = (length - 1) // 8 + 1
        return cls.from_bytes(value.to_bytes(bytelen, "little"), length)
    
    @classmethod
    def from_str(cls, value):
        value  = re.sub(r"[\s_]", "", value)
        if value:
            if value[0] == "-":
                raise ValueError("invalid negative input for bitarray(): '{}'".format(value))
            elif value[0] == "+":
                length = len(value) - 1
            else:
                length = len(value)
            return cls.from_int(int(value, 2), length)
        else:
            return cls.from_int(0)

    @classmethod
    def from_iter(cls, iterator):
        length = -1
        value = array('B')
        byte, pos = 0, 0
        for length, bit in enumerate(iterator):
            byte |= bool(bit) << pos
            pos += 1
            if pos == 8:
                value.append(byte)
                byte, pos = 0, 0
        if pos > 0:
            value.append(byte)  # add remaining bits
        return cls.from_bytes(value, length + 1)

    @classmethod
    def from_bytes(cls, value, length):
        inst = object.__new__(cls)
        inst._len_ = length
        byte_len = (length - 1) // 8 + 1
        inst._array_ = array('B', bytes(byte_len))
        cls.__copy_bit_slice(value, 0, length, inst._array_)
        return inst
            
    def __new__(cls, value=0, length=None):
        if isinstance(value, cls):
            if length is None or length == value._len_:
                return value
            else:
                return cls.from_bytes(value._array_, length)
        if isinstance(value, int):
            return cls.from_int(value, length)
        if isinstance(value, str):
            if length is not None:
                raise ValueError("invalid input for bitarray(): when converting from str "
                                 "length must not be provided")
            return cls.from_str(value)
        if isinstance(value, (bytes, bytearray, memoryview, array)):
            if length is None:
                raise ValueError("invalid input for bitarray(): when converting from bytes "
                                 "length must be provided")
            return cls.from_bytes(value, length)
        if isinstance(value, collections.abc.Iterable):
            if length is not None:
                raise ValueError("invalid input for bitarray(): when converting from an iterable "
                                 "length must not be provided")
            return cls.from_iter(value)
        raise TypeError("invalid input for bitarray(): cannot convert from {}"
                        .format(value.__class__.__name__))

    def __len__(self):
        return self._len_

    def __bool__(self):
        return bool(self._len_)

    def to_int(self):
        return int.from_bytes(self._array_, "little")

    __int__ = to_int

    def to_str(self):
        if self._len_:
            return format(self.to_int(), "0{}b".format(self._len_))
        return ""

    __str__ = to_str

    def to_bytes(self):
        return self._array_.tobytes()

    __bytes__ = to_bytes

    def __repr__(self):
        return "bitarray('{}')".format(self)
    
    def __getbit(self, pos):
        return (self._array_[pos // 8] >> (pos % 8)) & 1
    
    def __setbit(self, pos, value):
        if bool(value):
            self._array_[pos // 8] |= 1 << (pos % 8)
        else:
            self._array_[pos // 8] &= ~(1 << (pos % 8))

    def __getitem__(self, key):
        if isinstance(key, int):
            if key < 0:
                key += self._len_
            elif key >= self._len_:
                raise IndexError("bitarray index out of range")
            return self.__getbit(key)
        if isinstance(key, slice):
            start, stop, step = key.indices(self._len_)
            assert step == 1
            if stop < start:
                return self.__class__()
            else:
                return self.__class__(self.__copy_bit_slice(self._array_, start, stop - start), stop - start)
        raise TypeError("bitarray indices must be integers or slices, not {}"
                        .format(key.__class__.__name__))
    
    def __setitem__(self, key, value):
        if isinstance(key, int):
            if key < 0:
                key += self._len_
            elif key >= self._len_:
                raise IndexError("bitarray assignment index out of range")
            self.__setbit(key, value)
            return
        if isinstance(key, slice):
            start, stop, step = key.indices(self._len_)
            assert step == 1
            if stop < start:
                return
            else:
                other = self.__class__(value, stop - start)
                for i, v in enumerate(other):
                    self.__setbit(start+i, v)
                return
        raise NotImplementedError
    
    def setall(self, value):
        value_int = ~(-1 << self._len_) if bool(value) else 0
        value_bytes = value_int.to_bytes(len(self._array_), "little")
        self._array_ = array('B', value_bytes)

    def __iter__(self):
        for bit in range(self._len_):
            yield self.__getbit(bit)

    def __eq__(self, other):
        try:
            other = self.__class__(other)
        except TypeError:
            return False
        return self._len_ == other._len_ and self._array_ == other._array_   

    def __iadd__(self, other):
        other = self.__class__(other)
        offset = self._len_ % 8
        self._len_ += other._len_
        if offset == 0:
            self._array_.extend(other._array_)
            return self
        else:
            # Merge the adjacent byte of the two buffers first
            self._array_[-1] &= ~(-1 << offset)
            self._array_[-1] |= (other._array_[0] << offset) & 0xFF
            if other._len_ < 8 - offset:
                return self
            # Now append the remaining bytes with a bit offset to 
            # discard the set of already copied bits
            rem_bits = other._len_ - (8 - offset)
            rem_bytes = (rem_bits - 1) // 8 + 1
            prev_array_len = len(self._array_)
            self._array_.frombytes(bytes(rem_bytes)) # extend buffer
            self_arr = memoryview(self._array_)      # avoid copies
            self.__copy_bit_slice(other._array_, 8-offset, 
                              rem_bits, self_arr[prev_array_len:])
            return self
        
    def __add__(self, other):
        new = self.__class__(self._array_, self._len_)
        new += other
        return new

    def __radd__(self, other):
        other = self.__class__(other)
        return other + self
    
    def __mul__(self, other):
        if isinstance(other, int):
            return reduce(operator.add, (self for _ in range(other-1)), self)
        return NotImplemented

    def __rmul__(self, other):
        return self * other
    
    def __bitop(self, other, op, clear_top=False):
        other = self.__class__(other)
        # Only perform operation in-place when the other bitarray is smaller
        if other._len_ > self._len_:
            a, b = array('B', other._array_), self._array_
        else:
            a, b = self._array_, other._array_
        for i in range(len(b)):
            a[i] = op(a[i], b[i])
        if clear_top:
            memoryview(a)[len(b):] = bytes(len(a)-len(b))
        self._array_ = a
        self._len_ = max(self._len_, other._len_)
        return self
    
    def __iand__(self, other):
        return self.__bitop(other, operator.and_, True)

    def __and__(self, other):
        other = self.__class__(other)
        a, b = (other, self) if other._len_ > self._len_ else (self, other)
        new = self.__class__(a._array_, a._len_)
        new &= b
        return new

    def __rand__(self, other):
        other = self.__class__(other)
        return self & other

    def __ior__(self, other):
        return self.__bitop(other, operator.or_)

    def __or__(self, other):
        other = self.__class__(other)
        a, b = (other, self) if other._len_ > self._len_ else (self, other)
        new = self.__class__(a._array_, a._len_)
        new |= b
        return new
    
    def __ror__(self, other):
        other = self.__class__(other)
        return self | other

    def __ixor__(self, other):
        return self.__bitop(other, operator.xor)

    def __xor__(self, other):
        other = self.__class__(other)
        a, b = (other, self) if other._len_ > self._len_ else (self, other)
        new = self.__class__(a._array_, a._len_)
        new ^= b
        return new
    
    def __rxor__(self, other):
        other = self.__class__(other)
        return self ^ other
    
    @staticmethod
    def __build_revbyte_table():
        # From 'Bit Twiddling Hacks' by Sean Eron Anderson
        return bytes([((i * 0x0202020202 & 0x010884422010) % 1023) & 0xFF for i in range(256)])

    def byte_reverse(self):
        """ In-place byte reversal """
        if not hasattr(self.byte_reverse, "table"):  # only build once
            self.byte_reverse.__func__.table = self.__build_revbyte_table()
        table = self.byte_reverse.table
        for i in range(len(self._array_)):
            self._array_[i] = table[self._array_[i]]
        if self._len_ % 8:
            self._array_[-1] &= ~(-1 << (self._len_ % 8))
        return self

    def byte_reversed(self):
        new = self.__class__(self._array_, self._len_)
        return new.byte_reverse()

    def reversed(self):
        if self._len_ % 8:
            # Adding zero padding in the low bits allows easier bit reversal
            # for the cases where bit length is not multiple of byte size
            out = self.__class__(0, 8-(self._len_%8)) + self
        else:
            out = self.__class__(self._array_, self._len_)
        out._array_.reverse()   # Reverse byte order (last to first)
        out.byte_reverse()      # Reverse bit order in every byte
        out._len_ = self._len_  # Truncate possible length extension due to padding
        return out

    def find(self, sub, start=0, end=-1):
        sub = self.__class__(sub)
        if start < 0:
            start = self._len_ - start
        if end < 0:
            end = self._len_ - end
        for pos in range(start, end):
            if self[pos:pos + len(sub)] == sub:
                return pos
        else:
            return -1

# -------------------------------------------------------------------------------------------------

import unittest


class BitarrayTestCase(unittest.TestCase):
    def assertBits(self, value, bit_length, bit_value):
        self.assertIsInstance(value, bitarray)
        self.assertEqual(value._len_, bit_length)
        byte_length = (bit_length - 1) // 8 + 1
        self.assertEqual(value.to_bytes(), bit_value.to_bytes(byte_length, "little"))

    def test_from_int(self):
        self.assertBits(bitarray.from_int(0), 0, 0b0)
        self.assertBits(bitarray.from_int(1), 1, 0b1)
        self.assertBits(bitarray.from_int(2), 2, 0b10)
        self.assertBits(bitarray.from_int(2, 5), 5, 0b00010)
        self.assertBits(bitarray.from_int(0b110, 2), 2, 0b10)
        self.assertBits(bitarray.from_int(-1, 16), 16, 0xffff)

    def test_from_int_wrong(self):
        with self.assertRaisesRegex(ValueError,
                r"invalid negative input for bitarray\(\): '-1'"):
            bitarray.from_int(-1)

    def test_from_str(self):
        self.assertBits(bitarray.from_str(""), 0, 0b0)
        self.assertBits(bitarray.from_str("0"), 1, 0b0)
        self.assertBits(bitarray.from_str("010"), 3, 0b010)
        self.assertBits(bitarray.from_str("0 1  011_100"), 8, 0b01011100)
        self.assertBits(bitarray.from_str("+0 1 \t011_100"), 8, 0b01011100)

    def test_from_str_wrong(self):
        with self.assertRaisesRegex(ValueError,
                r"invalid negative input for bitarray\(\): '-1'"):
            bitarray.from_str("-1")
        with self.assertRaisesRegex(ValueError,
                r"invalid literal for int\(\) with base 2: '23'"):
            bitarray.from_str("23")

    def test_from_bytes(self):
        self.assertBits(bitarray.from_bytes(b"\xa5", 8), 8, 0b10100101)
        self.assertBits(bitarray.from_bytes(b"\xa5\x01", 9), 9, 0b110100101)
        self.assertBits(bitarray.from_bytes(b"\xa5\xff", 9), 9, 0b110100101)

    def test_from_iter(self):
        self.assertBits(bitarray.from_iter(iter([])), 0, 0b0)
        self.assertBits(bitarray.from_iter(iter([1,1,0,1,0,0,1])), 7, 0b1001011)

    def test_new(self):
        self.assertBits(bitarray(), 0, 0b0)
        self.assertBits(bitarray(10), 4, 0b1010)
        self.assertBits(bitarray(10, 2), 2, 0b10)
        self.assertBits(bitarray("1001"), 4, 0b1001)
        self.assertBits(bitarray(b"\xa5\x01", 9), 9, 0b110100101)
        self.assertBits(bitarray(bytearray(b"\xa5\x01"), 9), 9, 0b110100101)
        self.assertBits(bitarray(memoryview(b"\xa5\x01"), 9), 9, 0b110100101)
        self.assertBits(bitarray([1,1,0,1,0,0,1]), 7, 0b1001011)
        self.assertBits(bitarray(bitarray("1001"), 2), 2, 0b01)
        some = bitarray("1001")
        self.assertIs(bitarray(some), some)

    def test_new_wrong(self):
        with self.assertRaisesRegex(TypeError,
                r"invalid input for bitarray\(\): cannot convert from float"):
            bitarray(1.0)
        with self.assertRaisesRegex(ValueError,
                r"invalid input for bitarray\(\): when converting from str "
                r"length must not be provided"):
            bitarray("1010", 5)
        with self.assertRaisesRegex(ValueError,
                r"invalid input for bitarray\(\): when converting from bytes "
                r"length must be provided"):
            bitarray(b"\xa5")
        with self.assertRaisesRegex(ValueError,
                r"invalid input for bitarray\(\): when converting from an iterable "
                r"length must not be provided"):
            bitarray([1,0,1,0], 5)

    def test_len(self):
        self.assertEqual(len(bitarray(10)), 4)

    def test_bool(self):
        self.assertFalse(bitarray(""))
        self.assertTrue(bitarray("1"))
        self.assertTrue(bitarray("01"))
        self.assertTrue(bitarray("0"))
        self.assertTrue(bitarray("00"))

    def test_int(self):
        self.assertEqual(int(bitarray("1010")), 0b1010)

    def test_str(self):
        self.assertEqual(str(bitarray("")), "")
        self.assertEqual(str(bitarray("0000")), "0000")
        self.assertEqual(str(bitarray("1010")), "1010")
        self.assertEqual(str(bitarray("01010")), "01010")

    def test_bytes(self):
        self.assertEqual(bytes(bitarray("")), b"")
        self.assertEqual(bytes(bitarray("10100101")), b"\xa5")
        self.assertEqual(bytes(bitarray("110100101")), b"\xa5\x01")

    def test_repr(self):
        self.assertEqual(repr(bitarray("")), r"bitarray('')")
        self.assertEqual(repr(bitarray("1010")), r"bitarray('1010')")

    def test_getitem_int(self):
        some = bitarray("10001001011")
        self.assertEqual(some[0], 1)
        self.assertEqual(some[2], 0)
        self.assertEqual(some[5], 0)
        self.assertEqual(some[-1], 1)
        self.assertEqual(some[-2], 0)
        self.assertEqual(some[-5], 1)

    def test_getitem_slice(self):
        some = bitarray("10001001011")
        self.assertBits(some[:], 11, 0b10001001011)
        self.assertBits(some[2:], 9, 0b100010010)
        self.assertBits(some[2:9], 7, 0b0010010)
        self.assertBits(some[2:-2], 7, 0b0010010)
        self.assertBits(some[3:2], 0, 0b0)

    def test_getitem_wrong(self):
        with self.assertRaisesRegex(TypeError,
                r"bitarray indices must be integers or slices, not str"):
            bitarray()["x"]
            
    def test_setitem_int(self):
        some = bitarray("10001001011")
        some[0] = 0
        some[5] = 1
        some[-1] = 0
        self.assertEqual(some[0], 0)
        self.assertEqual(some[5], 1)
        self.assertEqual(some[-1], 0)
        self.assertEqual(some[-1], some[10])
        self.assertEqual(some, bitarray("00001101010"))
        
    def test_setitem_slice(self):
        some = bitarray("10001001011")
        some[:] = 0b01010101010
        self.assertBits(some[:], 11, 0b01010101010)
        some[2:9] = 0b010001011
        self.assertBits(some[:], 11, 0b01000101110)
        self.assertBits(some[2:], 9, 0b010001011)
        some[1:-1] = 0
        self.assertBits(some[:], 11, 0)
        
    def test_setitem_wrong(self):
        with self.assertRaisesRegex(TypeError,
                r"bitarray indices must be integers or slices, not str"):
            bitarray()["x"]

    def test_setall(self):
        some = bitarray("10001001011")
        some.setall(0)
        self.assertBits(some[:], 11, 0b00000000000)
        some.setall(1)
        self.assertBits(some[:], 11, 0b11111111111)

    def test_iter(self):
        some = bitarray("10001001011")
        self.assertEqual(list(some), [1,1,0,1,0,0,1,0,0,0,1])

    def test_eq(self):
        self.assertEqual(bitarray("1010"), 0b1010)
        self.assertEqual(bitarray("1010"), "1010")
        self.assertEqual(bitarray("1010"), bitarray("1010"))
        self.assertNotEqual(bitarray("0010"), 0b0010)
        self.assertNotEqual(bitarray("0010"), "010")
        self.assertNotEqual(bitarray("1010"), bitarray("01010"))
        self.assertNotEqual(bitarray("1010"), None)

    def test_add(self):
        self.assertBits(bitarray("1010") + bitarray("1110"), 8, 0b11101010)
        self.assertBits(bitarray("1010") + (0,1,1,1), 8, 0b11101010)
        self.assertBits((0,1,1,1) + bitarray("1010"), 8, 0b10101110)

    def test_mul(self):
        self.assertBits(bitarray("1011") * 4, 16, 0b1011101110111011)
        self.assertBits(4 * bitarray("1011"), 16, 0b1011101110111011)

    def test_and(self):
        self.assertBits(bitarray("1010") & bitarray("1100"), 4, 0b1000)
        self.assertBits(bitarray("1010") & "1100", 4, 0b1000)
        self.assertBits((0,1,0,1) & bitarray("1100"), 4, 0b1000)

    def test_or(self):
        self.assertBits(bitarray("1010") | bitarray("1100"), 4, 0b1110)
        self.assertBits(bitarray("1010") | "1100", 4, 0b1110)
        self.assertBits((0,1,0,1) | bitarray("1100"), 4, 0b1110)

    def test_xor(self):
        self.assertBits(bitarray("1010") ^ bitarray("1100"), 4, 0b0110)
        self.assertBits(bitarray("1010") ^ "1100", 4, 0b0110)
        self.assertBits((0,1,0,1) ^ bitarray("1100"), 4, 0b0110)
        
    def test_byte_reversed(self):
        self.assertBits(bitarray("10101010_11010101").byte_reversed(), 16, 0b0101010110101011)
        self.assertBits(bitarray("10101010_1101").byte_reversed(), 12, 0b10110101)

    def test_reversed(self):
        self.assertBits(bitarray("1010").reversed(), 4, 0b0101)

    def test_find(self):
        self.assertEqual(bitarray("1011").find(bitarray("11")), 0)
        self.assertEqual(bitarray("1011").find(bitarray("10")), 2)
        self.assertEqual(bitarray("1011").find(bitarray("01")), 1)
        self.assertEqual(bitarray("1011").find(bitarray("00")), -1)

        self.assertEqual(bitarray("101100101").find(bitarray("10"), 0), 1)
        self.assertEqual(bitarray("101100101").find(bitarray("10"), 2), 4)
        self.assertEqual(bitarray("101100101").find(bitarray("10"), 5), 7)
        self.assertEqual(bitarray("101100101").find(bitarray("10"), 8), -1)

        self.assertEqual(bitarray("1011").find(bitarray((1,0))), 1)
