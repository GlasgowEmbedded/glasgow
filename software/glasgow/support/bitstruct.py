import sys
import types
import textwrap
from typing import Self
from collections.abc import Callable

from glasgow.support.bits import bits


__all__ = ["bitstruct"]


class _bitstruct:
    __slots__ = ()
    _size_bits_: int
    _size_bytes_: int
    _named_fields_: list[str]
    _layout_: dict[str, tuple[int, int]]

    @staticmethod
    def _check_bits_(action, expected_width: int, value: bits):
        assert isinstance(value, bits)
        if len(value) != expected_width:
            raise ValueError(
                f"{action} requires {expected_width} bits, got {len(value)} bits ({value})")

    @staticmethod
    def _check_int_(action, expected_width: int, value: int):
        assert isinstance(value, int)
        if value < 0:
            raise ValueError(f"{action} requires a non-negative integer, got {value}")
        if value.bit_length() > expected_width:
            raise ValueError(
                f"{action} requires a {expected_width}-bit integer, "
                f"got {value.bit_length()}-bit ({value})")

    @staticmethod
    def _check_bytes_(action, expected_length: int, value: bytes | bytearray | memoryview):
        assert isinstance(value, (bytes, bytearray, memoryview))
        if len(value) != expected_length:
            raise ValueError(
                f"{action} requires {expected_length} bytes, "
                f"got {len(value)} bytes ({value.hex()})")

    @staticmethod
    def _define_fields_(ty, declared_bits, fields):
        total_bits = sum(width for name, width in fields)
        if total_bits != declared_bits:
            raise TypeError(
                f"declared width is {declared_bits} bits, but "
                f"sum of field widths is {total_bits} bits")

        ty["_size_bits_"]    = declared_bits
        ty["_size_bytes_"]   = (declared_bits + 7) // 8
        ty["_named_fields_"] = []
        ty["_layout_"]       = {}

        offset = 0
        for name, width in fields:
            if name is None:
                name = f"padding_{offset}"
            else:
                ty["_named_fields_"].append(name)
            ty["_layout_"][name] = (offset, width)
            offset += width

        ty["__slots__"] = tuple(f"_f_{field}" for field in ty["_layout_"])

        code = textwrap.dedent(f"""
        def __init__(self, {", ".join(f"{field}=0" for field in ty["_named_fields_"])}):
            {"; ".join(f"self.{field} = 0"
                       for field in ty["_layout_"] if field not in ty["_named_fields_"])}
            {"; ".join(f"self.{field} = {field}"
                       for field in ty["_layout_"] if field in ty["_named_fields_"])}

        @classmethod
        def from_bits(cls, value):
            cls._check_bits_("initialization", cls._size_bits_, value)
            self = object.__new__(cls)
            {"; ".join(f"self._f_{field} = int(value[{offset}:{offset+width}])"
                       for field, (offset, width) in ty["_layout_"].items())}
            return self

        def to_bits(self):
            value = 0
            {"; ".join(f"value |= self._f_{field} << {offset}"
                       for field, (offset, width) in ty["_layout_"].items())}
            return bits(value, self._size_bits_)
        """)

        for field, (_offset, width) in ty["_layout_"].items():
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
            ty[name] = method

    from_bits: Callable[[bits], Self]
    to_bits: Callable[[], bits]

    @classmethod
    def from_bytes(cls, value) -> Self:
        cls._check_bytes_("initialization", cls._size_bytes_, value)
        return cls.from_bits(bits(value, cls._size_bits_))

    from_bytearray = from_bytes

    @classmethod
    def from_int(cls, value) -> Self:
        cls._check_int_("initialization", cls._size_bits_, value)
        return cls.from_bits(bits(value, cls._size_bits_))

    @classmethod
    def bit_length(cls) -> int:
        return cls._size_bits_

    def to_int(self) -> int:
        return int(self.to_bits())

    __int__ = to_int

    def to_bytes(self) -> bytes:
        return bytes(self.to_bits())

    __bytes__ = to_bytes

    def to_bytearray(self) -> bytearray:
        return bytearray(bytes(self.to_bits()))

    def copy(self) -> Self:
        return self.__class__.from_bits(self.to_bits())

    def bits_repr(self, omit_zero=False, omit_padding=True) -> str:
        fields = []
        if omit_padding:
            names = self._named_fields_
        else:
            names = self._layout_.keys()

        for name in names:
            _offset, width = self._layout_[name]
            value = getattr(self, name)
            if omit_zero and value == 0:
                continue

            fields.append(f"{name}={value:0{width}b}")

        return " ".join(fields)

    def __repr__(self) -> str:
        return f"<{self.__module__}.{self.__class__.__name__} {self.bits_repr()}>"

    def __eq__(self, other: Self) -> bool:
        return isinstance(other, self.__class__) and self.to_bits() == other.to_bits()


def bitstruct(name, size_bits, fields) -> type[_bitstruct]:
    mod = sys._getframe(1).f_globals["__name__"] # see namedtuple()

    cls = types.new_class(name, (_bitstruct,),
        exec_body=lambda ns: _bitstruct._define_fields_(ns, size_bits, fields))
    cls.__module__ = mod

    return cls
