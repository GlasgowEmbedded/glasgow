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

        cls["__slots__"] = tuple(f"_f_{field}" for field in cls["_layout_"])

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
        return f"<{self.__module__}.{self.__class__.__name__} {self.bits_repr()}>"

    def __eq__(self, other):
        return isinstance(other, self.__class__) and self.to_bits() == other.to_bits()


def bitstruct(name, size_bits, fields):
    mod = sys._getframe(1).f_globals["__name__"] # see namedtuple()

    cls = types.new_class(name, (_bitstruct,),
        exec_body=lambda ns: _bitstruct._define_fields_(ns, size_bits, fields))
    cls.__module__ = mod

    return cls
