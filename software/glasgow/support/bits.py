import re
import operator
from functools import reduce
import collections.abc


__all__ = ["bits"]


class bits:
    """An immutable bit sequence, like ``bytes`` but for bits.

    This bit sequence is ordered from LSB to MSB; this is the direction in which it is converted
    to and from iterators, and to and from bytes. Note, however, that it is converted to and from
    strings (which should be only used where a human-readable form is required) from MSB to LSB;
    this matches the way integer literals are written, as well as values in datasheets and other
    documentation.
    """
    __slots__ = ["_len_", "_int_"]

    @classmethod
    def from_int(cls, value, length=None):
        value = operator.index(value)
        if length is None:
            if value < 0:
                raise ValueError("invalid negative input for bits(): '{}'".format(value))
            length = value.bit_length()
        else:
            length = operator.index(length)
            value &= ~(-1 << length)
        inst = object.__new__(cls)
        inst._len_ = length
        inst._int_ = value
        return inst

    @classmethod
    def from_str(cls, value):
        value  = re.sub(r"[\s_]", "", value)
        if value:
            if value[0] == "-":
                raise ValueError("invalid negative input for bits(): '{}'".format(value))
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
        value  = 0
        for length, bit in enumerate(iterator):
            value |= bool(bit) << length
        return cls.from_int(value, length + 1)

    @classmethod
    def from_bytes(cls, value, length):
        return cls.from_int(int.from_bytes(value, "little"), length)

    def __new__(cls, value=0, length=None):
        if isinstance(value, cls):
            if length is None:
                return value
            else:
                return cls.from_int(value._int_, length)
        if isinstance(value, int):
            return cls.from_int(value, length)
        if isinstance(value, str):
            if length is not None:
                raise ValueError("invalid input for bits(): when converting from str "
                                 "length must not be provided")
            return cls.from_str(value)
        if isinstance(value, (bytes, bytearray, memoryview)):
            if length is None:
                raise ValueError("invalid input for bits(): when converting from bytes "
                                 "length must be provided")
            return cls.from_bytes(value, length)
        if isinstance(value, collections.abc.Iterable):
            if length is not None:
                raise ValueError("invalid input for bits(): when converting from an iterable "
                                 "length must not be provided")
            return cls.from_iter(value)
        raise TypeError("invalid input for bits(): cannot convert from {}"
                        .format(value.__class__.__name__))

    def __len__(self):
        return self._len_

    def __bool__(self):
        return bool(self._len_)

    def to_int(self):
        return self._int_

    __int__ = to_int

    def to_str(self):
        if self._len_:
            return format(self._int_, "0{}b".format(self._len_))
        return ""

    __str__ = to_str

    def to_bytes(self):
        return self._int_.to_bytes((self._len_ + 7) // 8, "little")

    __bytes__ = to_bytes

    def __repr__(self):
        return "bits('{}')".format(self)

    def __getitem__(self, key):
        if isinstance(key, int):
            if key < 0:
                return (self._int_ >> (self._len_ + key)) & 1
            else:
                return (self._int_ >> key) & 1
        if isinstance(key, slice):
            start, stop, step = key.indices(self._len_)
            assert step == 1
            if stop < start:
                return self.__class__()
            else:
                return self.__class__(self._int_ >> start, stop - start)
        raise TypeError("bits indices must be integers or slices, not {}"
                        .format(key.__class__.__name__))

    def __iter__(self):
        for bit in range(self._len_):
            yield (self._int_ >> bit) & 1

    def __eq__(self, other):
        try:
            other = self.__class__(other)
        except TypeError:
            return False
        return self._len_ == other._len_ and self._int_ == other._int_

    def __add__(self, other):
        other = self.__class__(other)
        return self.__class__(self._int_ | (other._int_ << self._len_),
                              self._len_ + other._len_)

    def __radd__(self, other):
        other = self.__class__(other)
        return other + self

    def __mul__(self, other):
        if isinstance(other, int):
            return self.__class__(reduce(lambda a, b: (a << self._len_) | b,
                                         (self._int_ for _ in range(other)), 0),
                                  self._len_ * other)
        return NotImplemented

    def __rmul__(self, other):
        return self * other

    def __and__(self, other):
        other = self.__class__(other)
        return self.__class__(self._int_ & other._int_, max(self._len_, other._len_))

    def __rand__(self, other):
        other = self.__class__(other)
        return self & other

    def __or__(self, other):
        other = self.__class__(other)
        return self.__class__(self._int_ | other._int_, max(self._len_, other._len_))

    def __ror__(self, other):
        other = self.__class__(other)
        return self | other

    def __xor__(self, other):
        other = self.__class__(other)
        return self.__class__(self._int_ ^ other._int_, max(self._len_, other._len_))

    def __rxor__(self, other):
        other = self.__class__(other)
        return self ^ other

    def reversed(self):
        value = 0
        for bit in range(self._len_):
            value <<= 1
            if (self._int_ >> bit) & 1:
                value |= 1
        return self.__class__(value, self._len_)

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
