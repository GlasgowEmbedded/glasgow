import re
import itertools
import operator
from collections.abc import Sequence, MutableSequence, Iterable
from typing_extensions import Self


__all__ = ["bits", "bitarray"]


def _byte_len(l):
    return (l + 7) // 8

_byterev_lut = bytes(
    sum(
        ((byte >> bit) & 1) << (7 - bit)
        for bit in range(8)
    )
    for byte in range(0x100)
)

class _bits_base(Sequence):
    __slots__ = ("_len", "_bytes")

    @classmethod
    def from_int(cls, value, length=None) -> Self:
        """Creates bits from an integer. If ``length`` is given, the integer will be
        masked to the target width. Otherwise, the smallest possible width will be
        used that does not mask off any bits of the integer, and the value must not
        be negative.
        """
        value = operator.index(value)
        if length is None:
            if value < 0:
                raise ValueError(f"invalid negative input for {cls.__name__}(): '{value}'")
            length = value.bit_length()
        else:
            length = operator.index(length)
            value &= ~(-1 << length)
        inst = object.__new__(cls)
        inst._len = length
        inst._bytes = cls._bytestype(value.to_bytes(_byte_len(length), 'little'))
        return inst

    @classmethod
    def from_str(cls, value) -> Self:
        """Creates bits from a string. Any whitespace or ``_`` characters in the string
        will be discarded. The string must consist only of ``0`` and ``1`` characters.
        The bits in the string are treated as MSB-first.
        """
        value  = re.sub(r"[\s_]", "", value)
        if not re.match(r"^[01]*$", value):
            raise ValueError(f"invalid input for {cls.__name__}(): '{value}'")
        return cls.from_iter(int(x) for x in reversed(value))

    @classmethod
    def from_iter(cls, iterator) -> Self:
        """Creates bits from an iterator of bit values (ie. ints of value 0 and 1).
        The bits in the iterator are treated as LSB-first."""
        nbits = 0

        def make_bytes():
            nonlocal nbits
            byte = 0
            for bit in iterator:
                bit = operator.index(bit)
                if bit not in (0, 1):
                    raise ValueError(f"{cls.__name__} can only contain 0 and 1")
                byte |= bit << (nbits % 8)
                nbits += 1
                if nbits % 8 == 0:
                    yield byte
                    byte = 0
            if nbits % 8 != 0:
                yield byte
            return

        res = object.__new__(cls)
        res._bytes = cls._bytestype(make_bytes())
        res._len = nbits
        return res

    @classmethod
    def from_bytes(cls, value, length=None) -> Self:
        """Creates bits from a bytes (or bytes-like) object. The bits in each byte are
        collected LSB-first, and the bytes are collected in order.  If ``length`` is not
        specified, it is assumed to be ``8 * len(value)``.  Otherwise, the predicate
        ``8 * len(value) - 7 <= length <= 8 * len(value)`` must hold, and extra MSBs of
        the last byte (if any) will be treated as padding.  The padding bits must be 0.
        In other words, the value given here must be a byte string that would have been
        produced by ``to_bytes``.
        """
        value = cls._bytestype(value)
        if length is None:
            length = len(value) * 8
        if len(value) != _byte_len(length):
            raise ValueError(f"wrong bytes length {len(value)} for {cls.__name__} of length {length}")
        if length % 8:
            mask = -1 << (length % 8)
            if value[-1] & (-1 << (length % 8)):
                raise ValueError("wrong padding in the last byte")
        res = object.__new__(cls)
        res._bytes = value
        res._len = length
        return res

    def __new__(cls, value=0, length=None) -> Self:
        """Creates a new bits instance.  The valid arguments for ``value`` are:

        - another bits or bitarray instance (``length`` must not be provided)
        - int (``length`` may be provided or not, see ``from_int``)
        - str (``length`` must not be provided, see ``from_str``)
        - bytes, bytearray, memoryview (``length`` may be provided or not, see ``from_bytes``)
        - an iterable of 0 and 1 other than the above (``length`` must not be provided, see ``from_iter``)
        """
        if isinstance(value, _bits_base):
            if length is not None:
                raise ValueError(f"invalid input for {cls.__name__}(): when converting from bits "
                                 "length must not be provided")
            if cls is bits and type(value) is bits:
                return value
            res = object.__new__(cls)
            res._bytes = cls._bytestype(value._bytes)
            res._len = value._len
            return res
        if isinstance(value, int):
            return cls.from_int(value, length)
        if isinstance(value, str):
            if length is not None:
                raise ValueError(f"invalid input for {cls.__name__}(): when converting from str "
                                 "length must not be provided")
            return cls.from_str(value)
        if isinstance(value, (bytes, bytearray, memoryview)):
            return cls.from_bytes(value, length)
        if isinstance(value, Iterable):
            if length is not None:
                raise ValueError(f"invalid input for {cls.__name__}(): when converting from an iterable "
                                 "length must not be provided")
            return cls.from_iter(value)
        raise TypeError(f"invalid input for {cls.__name__}(): cannot convert from {value.__class__.__name__}")

    def __len__(self) -> int:
        return self._len

    def __bool__(self) -> bool:
        return bool(self._len)

    def __eq__(self, other) -> bool:
        if not isinstance(other, _bits_base):
            return False
        return self._len == other._len and self._bytes == other._bytes

    def __getitem__(self, key) -> Self | int:
        if isinstance(key, slice):
            start, stop, step = key.indices(self._len)
            if not range(start, stop, step):
                # get empty slices out of the way first
                return self.__class__()
            elif step == -1 and start % 8 == 7 and stop % 8 == 7:
                # byte-aligned reverse fastpath
                res = object.__new__(self.__class__)
                bstart = start // 8
                bstop = None if stop == -1 else stop // 8
                res._bytes = self._bytes[bstart:bstop:-1].translate(_byterev_lut)
                res._len = start - stop
                return res
            elif step == 1 and start % 8 == 0 and (stop % 8 == 0 or stop == self._len):
                # byte-aligned normal fastpath (stop either byte-aligned,
                # or matches end of sequence)
                res = object.__new__(self.__class__)
                res._bytes = self._bytes[start // 8 : (stop + 7) // 8]
                res._len = stop - start
                return res
            else:
                # slow path
                return self.from_iter(self[i] for i in range(start, stop, step))
        else:
            try:
                key = operator.index(key)
            except:
                raise TypeError(f"{self.__class__.__name__} indices must be integers or slices, not {key.__class__.__name__}")
            if key < 0:
                key += self._len
            if key not in range(self._len):
                raise IndexError(f"{self.__class__.__name__} index out of range")
            return (self._bytes[key // 8] >> (key % 8)) & 1

    def to_int(self) -> int:
        """Returns the value of this bit string as an integer."""
        return int.from_bytes(self._bytes, 'little')

    def to_str(self) -> str:
        """Returns the bit string as a human-readable string (MSB-first)."""
        return ''.join(str(x) for x in reversed(self))

    def to_bytes(self) -> bytes:
        """Returns the bits packed into bytes. The bits are packed into bytes LSB-first.
        If the length of the bit string is not divisible by 8, the last byte will have
        padding bits at MSB with a value of 0."""
        return bytes(self._bytes)

    __int__ = to_int
    __str__ = to_str
    __bytes__ = to_bytes

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}('{self}')"

    def __add__(self, other) -> Self:
        if isinstance(other, (str, Iterable)):
            other = bits(other)
        elif not isinstance(other, _bits_base):
            return NotImplemented
        if self._len % 8 == 0:
            res = object.__new__(self.__class__)
            res._bytes = self._bytes + other._bytes
            res._len = self._len + other._len
            return res
        return self.from_iter(itertools.chain(self, other))

    def __radd__(self, other) -> Self:
        if isinstance(other, (str, Iterable)):
            other = bits(other)
        elif not isinstance(other, _bits_base):
            return NotImplemented
        if other._len % 8 == 0:
            res = object.__new__(self.__class__)
            res._bytes = other._bytes + self._bytes
            res._len = other._len + self._len
            return res
        return self.from_iter(itertools.chain(other, self))

    def __mul__(self, other) -> Self:
        if not isinstance(other, int):
            return NotImplemented
        if self._len % 8 == 0:
            res = object.__new__(self.__class__)
            res._bytes = self._bytes * other
            res._len = self._len * other
            return res
        return self.from_iter(itertools.chain.from_iterable(itertools.repeat(self, other)))

    __rmul__ = __mul__

    def _bitop(self, other, op):
        if isinstance(other, int):
            other = bits(other, self._len)
        elif not isinstance(other, _bits_base):
            other = bits(other)
        if len(other) != len(self):
            raise ValueError("mismatched bitwise operator widths")
        res = object.__new__(self.__class__)
        res._bytes = self._bytestype(op(a, b) for (a, b) in zip(self._bytes, other._bytes))
        res._len = self._len
        return res

    def __and__(self, other) -> Self:
        return self._bitop(other, operator.__and__)

    __rand__ = __and__

    def __or__(self, other) -> Self:
        return self._bitop(other, operator.__or__)

    __ror__ = __or__

    def __xor__(self, other) -> Self:
        return self._bitop(other, operator.__xor__)

    __rxor__ = __xor__

    def __invert__(self) -> Self:
        if self._len % 8 == 0:
            pad_idx = None
        else:
            pad_idx = self._len // 8
            pad_mask = ~(-1 << self._len % 8)
        res = object.__new__(self.__class__)
        res._bytes = self._bytestype(
            ~x & pad_mask if i == pad_idx else ~x & 0xff
            for i, x in enumerate(self._bytes)
        )
        res._len = self._len
        return res

    def reversed(self) -> Self:
        """Returns a reversed copy of this bit string. Equivalent to ``from_iter(reversed(self))``."""
        if self._len % 8 == 0:
            res = object.__new__(self.__class__)
            res._bytes = self._bytes.translate(_byterev_lut)[::-1]
            res._len = self._len
            return res
        else:
            return self.from_iter(reversed(self))

    def byte_reversed(self) -> Self:
        """Returns a copy of this bit string with bits reversed within each byte.
        The length of this bit string must be divisible by 8."""
        if self._len % 8 == 0:
            res = object.__new__(self.__class__)
            res._bytes = self._bytes.translate(_byterev_lut)
            res._len = self._len
            return res
        else:
            raise ValueError(f"byte_reversed requires {self.__class__.__name__} of length divisible by 8")

    def find(self, needle, start=0, end=None) -> int:
        """Returns the start index of the first occurence of a given bit string within this
        bit string. If the ``needle`` is an ``str`` or an iterator, it is first converted
        to ``bits``. If ``needle`` is an integer, it must hava a value of 0 or 1, and is
        converted to single-bit ``bits``. If ``start`` and ``end`` are given, only start positions in
        ``range(start, end)`` are checked. If no occurence is found, the result is ``-1``."""
        if isinstance(needle, (str, Iterable)):
            needle = bits(needle)
        elif not isinstance(needle, _bits_base):
            needle = bits([needle])
        if end is None:
            end = self._len
        end = min(end, self._len - (needle._len - 1))
        for i in range(start, end):
            if all(self[i + j] == needle[j] for j in range(needle._len)):
               return i
        return -1

    def index(self, *args, **kwargs) -> int:
        """Like ``find``, but raises ``ValueError`` when the substring is not found."""
        res = self.find(*args, **kwargs)
        if res == -1:
            raise ValueError("substring not found")
        return res


class bits(_bits_base):
    """An immutable bit sequence, like ``bytes`` but for bits.

    This bit sequence is ordered from LSB to MSB; this is the direction in which it is converted
    to and from iterators, and to and from bytes. Note, however, that it is converted to and from
    strings (which should be only used where a human-readable form is required) from MSB to LSB;
    this matches the way integer literals are written, as well as values in datasheets and other
    documentation.
    """

    __slots__ = ()
    _bytestype = bytes

    def __hash__(self) -> int:
        return hash((self._len, self._bytes))

class bitarray(_bits_base, MutableSequence):
    """A mutable bit sequence, like ``bytearray`` but for bits.

    Works like ``bits``, but has additional mutation methods and cannot be hashed.
    """

    __slots__ = ()
    _bytestype = bytearray

    def _fix_padding(self):
        if self._len % 8 != 0:
            self._bytes[-1] &= ~(-1 << (self._len % 8))

    def _resize(self, length):
        blen = _byte_len(length)
        if length < self._len:
            del self._bytes[blen:]
            self._len = length
            self._fix_padding()
        elif length > self._len:
            self._bytes += bytes(blen - len(self._bytes))
            self._len = length

    def __setitem__(self, key, value) -> None:
        if isinstance(key, slice):
            start, stop, step = key.indices(self._len)
            rng = range(start, stop, step)
            if isinstance(value, int):
                value = bits(value, len(rng))
            elif isinstance(value, str):
                value = bits(value)
            elif not isinstance(value, _bits_base):
                raise TypeError("invalid type for bitarray slice assignment")
            if step != 1:
                # generic slow path
                if len(rng) != len(value):
                    raise ValueError(f"atempt to assign sequence of size {len(value)} to extended slice of size {len(rng)}")
                for di, bit in zip(rng, value):
                    self[di] = bit
            elif start % 8 == 0 and stop % 8 == 0 and value._len % 8 == 0:
                # byte-aligned fastpath with aligned ends
                self._bytes[start // 8 : stop // 8] = value._bytes
                self._len += value._len - (stop - start)
            elif start % 8 == 0 and stop == self._len:
                # byte-aligned fastpath with no tail
                self._bytes[start // 8 :] = value._bytes
                self._len = start + value._len
            elif stop - start == value._len:
                # slow-ish path, no resize
                for di, bit in zip(rng, value):
                    self[di] = bit
            elif stop == self._len:
                # slow-ish path, extend/truncate
                self._resize(start + value._len)
                for di, bit in enumerate(value, start=start):
                    self[di] = bit
            else:
                # slow path
                tail = self[stop:]
                self._resize(start)
                self += value
                self += tail
        else:
            try:
                key = operator.index(key)
            except:
                raise TypeError(f"{self.__class__.__name__} indices must be integers or slices, not {key.__class__.__name__}")
            value = operator.index(value)
            if value not in (0, 1):
                raise ValueError("bit value must be 0 or 1")
            if key < 0:
                key += self._len
            if key not in range(self._len):
                raise IndexError("bits index out of range")
            if value:
                self._bytes[key // 8] |= 1 << (key % 8)
            else:
                self._bytes[key // 8] &= ~(1 << (key % 8))

    def __delitem__(self, key) -> None:
        if isinstance(key, slice):
            start, stop, step = key.indices(self._len)
            if not range(start, stop, step):
                # get empty slices out of the way first
                return
            elif step != 1:
                # insane slow path
                res = self.from_iter(
                    x
                    for (i, x) in enumerate(self)
                    if i not in range(start, stop, step)
                )
                self._bytes = res._bytes
                self._len = res._len
            elif start % 8 == 0 and (stop % 8 == 0 or stop == self._len):
                # byte-aligned normal fastpath (stop either byte-aligned,
                # or matches end of sequence)
                if stop == self._len:
                    self._len = start
                else:
                    self._len -= stop - start
                del self._bytes[start // 8 : (stop + 7) // 8]
            elif stop == self._len:
                # simple trim
                self._resize(start)
            else:
                # slow path
                tail = self[stop:]
                self._resize(start)
                self += tail
        else:
            try:
                key = operator.index(key)
            except:
                raise TypeError(f"{self.__class__.__name__} indices must be integers or slices, not {key.__class__.__name__}")
            if key < 0:
                key += self._len
            if key not in range(self._len):
                raise IndexError("bits index out of range")
            del self[key:key+1]

    def insert(self, index, value) -> None:
        index = operator.index(index)
        value = operator.index(value)
        if value not in (0, 1):
            raise ValueError("wrong value for bitarray")
        if index < 0:
            index += self._len
        if index == self._len:
            if self._len % 8 == 0:
                self._bytes.append(0)
            self._len += 1
            self[index] = value
        else:
            self[index:index] = bits(value, 1)

    def clear(self) -> None:
        self._bytes.clear()
        self._len = 0

    def reverse(self) -> None:
        """Reverses the bits of the bitarray in-place."""
        if self._len % 8 == 0:
            self._bytes = self._bytes.translate(_byterev_lut)
            self._bytes.reverse()
        else:
            super().reverse()

    def byte_reverse(self) -> None:
        """Reverses the bits within every byte of this bitarray in-place. The length
        of this bitarray must be divisible by 8."""
        if self._len % 8 == 0:
            self._bytes = self._bytes.translate(_byterev_lut)
        else:
            raise ValueError("byte_reverse requires a bitstream of length divisible by 8")

    def extend(self, values) -> None:
        if isinstance(values, (str, _bits_base)):
            self[self._len:] = values
        else:
            super().extend(values)

    def __imul__(self, other) -> Self:
        other = operator.index(other)
        if self._len % 8 == 0 or other == 0:
            self._bytes *= other
            self._len *= other
        elif other < 0:
            raise ValueError("cannot multiply bitarray by negative count")
        elif other != 1:
            val = self[:]
            for _ in range(other - 1):
                self += val
        return self

    def _ibitop(self, other, op):
        if isinstance(other, int):
            other = bits(other, self._len)
        elif not isinstance(other, _bits_base):
            other = bits(other)
        if len(other) != len(self):
            raise ValueError("mismatched bitwise operator widths")
        for i, b in enumerate(other._bytes):
            self._bytes[i] = op(self._bytes[i], b)
        return self

    def __iand__(self, other) -> Self:
        return self._ibitop(other, operator.__and__)

    def __ior__(self, other) -> Self:
        return self._ibitop(other, operator.__or__)

    def __ixor__(self, other) -> Self:
        return self._ibitop(other, operator.__xor__)

    def setall(self, value) -> None:
        """Sets all bits of this bitarray to the given value."""
        value = operator.index(value)
        if value not in (0, 1):
            raise ValueError("bit value must be 0 or 1")
        if value:
            self._bytes = bytearray(b"\xff" * len(self._bytes))
            self._fix_padding()
        else:
            self._bytes = bytearray(len(self._bytes))
