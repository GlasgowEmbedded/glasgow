import enum
import types
import typing
from typing import Self

from glasgow.support.bits import bits


__all__ = ["bitstruct"]


class _bitstruct_annotations(dict):
    def __setitem__(self, name, annotation):
        if name in self:
            raise TypeError(f"duplicate bitstruct field {name!r}")

        super().__setitem__(name, annotation)


class _bitstruct_namespace(dict):
    def __setitem__(self, name, value):
        if name == "__annotations__" and not isinstance(value, _bitstruct_annotations):
            value = _bitstruct_annotations(value)
        elif name in self and not name.startswith("__"):
            raise TypeError(f"duplicate bitstruct attribute {name!r}")

        super().__setitem__(name, value)


class _bitstruct_meta(type):
    @classmethod
    def __prepare__(mcls, name, bases, *, width=None, **kwargs):
        return _bitstruct_namespace()

    def __new__(mcls, name, bases, namespace, *, width=None):
        if not bases:
            return super().__new__(mcls, name, bases, namespace)

        if len(bases) != 1 or hasattr(bases[0], "_layout_"):
            raise TypeError("a bitstruct cannot extend another bitstruct or use mixins")
        if width is None:
            raise TypeError(f"bitstruct {name!r} does not specify a width")
        if type(width) is not int or width <= 0:
            raise TypeError(f"bitstruct {name!r} width must be a positive integer, not {width!r}")
        if "__slots__" in namespace:
            raise TypeError(f"bitstruct {name!r} cannot define __slots__")

        annotations = namespace.get("__annotations__", {})
        if not annotations and "__annotate_func__" in namespace:
            # Python 3.14 defers annotation evaluation (PEP 649). The
            # annotation function is sufficient here to recover declaration
            # order; types are resolved on the completed class below.
            import annotationlib

            annotations = namespace["__annotate_func__"](annotationlib.Format.VALUE)

        layout = {}
        named_fields = []
        offset = 0
        for field_name in annotations:
            if field_name not in namespace:
                raise TypeError(f"bitstruct field {field_name!r} does not specify a width")

            field_width = namespace.pop(field_name)
            if type(field_width) is not int or field_width <= 0:
                raise TypeError(
                    f"bitstruct field {field_name!r} width must be a positive integer, "
                    f"not {field_width!r}"
                )

            if not field_name.startswith("_"):
                for base in bases:
                    if hasattr(base, field_name):
                        raise TypeError(
                            f"bitstruct field {field_name!r} conflicts with an existing attribute"
                        )
                named_fields.append(field_name)
            layout[field_name] = (offset, field_width)
            offset += field_width

        if offset != width:
            raise TypeError(
                f"declared width is {width} bits, but sum of field widths is {offset} bits"
            )

        namespace["__slots__"] = tuple(f"_f_{field_name}" for field_name in layout)
        cls = super().__new__(mcls, name, bases, namespace)

        try:
            resolved_annotations = typing.get_type_hints(cls)
        except Exception as error:
            raise TypeError(f"could not resolve annotations for bitstruct {name!r}") from error

        field_types = {}
        for field_name, (_offset, field_width) in layout.items():
            field_type = resolved_annotations[field_name]
            if field_type is bool:
                if field_width != 1:
                    raise TypeError(
                        f"boolean bitstruct field {field_name!r} must be 1 bit wide, "
                        f"not {field_width} bits"
                    )
            elif field_type is int:
                # Nothing to do
                pass
            elif not (isinstance(field_type, type) and issubclass(field_type, enum.IntEnum)):
                raise TypeError(
                    f"bitstruct field {field_name!r} has unsupported type {field_type!r}"
                )
            else:
                for member in field_type:
                    if member.value < 0 or member.value.bit_length() > field_width:
                        raise TypeError(
                            f"member {field_type.__name__}.{member.name} does not fit in "
                            f"{field_width}-bit field {field_name!r}"
                        )

            field_types[field_name] = field_type

        cls._size_bits_ = width
        cls._size_bytes_ = (width + 7) // 8
        cls._named_fields_ = tuple(named_fields)
        cls._layout_ = types.MappingProxyType(layout)
        cls._field_types_ = types.MappingProxyType(field_types)

        for field_name in named_fields:
            field_width = layout[field_name][1]

            def getter(self, field_name=field_name):
                return getattr(self, f"_f_{field_name}")

            def setter(self, value, field_name=field_name, field_width=field_width):
                setattr(
                    self, f"_f_{field_name}", self._coerce_field_(field_name, field_width, value)
                )

            setattr(cls, field_name, property(getter, setter))

        return cls


class bitstruct(metaclass=_bitstruct_meta):
    """Base class for mutable fixed-width bit-field structures.

    Define fields using annotated class attributes, where the assigned value is
    the field width in bits. Fields are laid out least-significant first in
    declaration order, and their widths must add up to the structure's declared
    ``width``.

    Field annotations may be ``int``, ``bool``, or an ``IntEnum`` subclass.
    Boolean fields must be exactly one bit wide. Enum fields are decoded
    strictly, so an encoded value without a corresponding member raises
    ``ValueError``.

    Names beginning with an underscore designate padding. Padding names must be
    unique, are not accepted by the constructor, and are not exposed as
    attributes.

    For example::

        class Status(bitstruct, width=8):
            ready: bool = 1
            mode: Mode = 2
            count: int = 3
            _0: int = 2

    Instances may be initialized using positional or keyword field values and
    converted to or from integers, bytes, and ``bits`` values.
    """

    __slots__ = ()
    _size_bits_: int
    _size_bytes_: int
    _named_fields_: tuple[str, ...]
    _layout_: types.MappingProxyType[str, tuple[int, int]]
    _field_types_: types.MappingProxyType[str, type[int]]

    @staticmethod
    def _check_bits_(action, expected_width: int, value: bits):
        if not isinstance(value, bits):
            raise TypeError(f"{action} requires a bits value, not {type(value).__name__}")

        if len(value) != expected_width:
            raise ValueError(
                f"{action} requires {expected_width} bits, got {len(value)} bits ({value})"
            )

    @staticmethod
    def _check_int_(action, expected_width: int, value: int):
        if not isinstance(value, int):
            raise TypeError(f"{action} requires an integer, not {type(value).__name__}")

        if value < 0:
            raise ValueError(f"{action} requires a non-negative integer, got {value}")

        if value.bit_length() > expected_width:
            raise ValueError(
                f"{action} requires a {expected_width}-bit integer, "
                f"got {value.bit_length()}-bit ({value})"
            )

    @staticmethod
    def _check_bytes_(action, expected_length: int, value: bytes | bytearray | memoryview):
        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise TypeError(f"{action} requires a bytes-like value, not {type(value).__name__}")

        if len(value) != expected_length:
            raise ValueError(
                f"{action} requires {expected_length} bytes, got {len(value)} bytes ({value.hex()})"
            )

    @classmethod
    def _coerce_field_(cls, name, width, value):
        if isinstance(value, bits):
            cls._check_bits_("field assignment", width, value)
            value = int(value)
        else:
            cls._check_int_("field assignment", width, value)

        field_type = cls._field_types_[name]
        if field_type is bool:
            return bool(value)
        elif field_type is int:
            return int(value)
        else:
            return field_type(value)

    def __init__(self, *args, **kwargs):
        if len(args) > len(self._named_fields_):
            raise TypeError(
                f"{self.__class__.__name__}() takes at most {len(self._named_fields_)} "
                f"positional arguments ({len(args)} given)"
            )

        values = dict(zip(self._named_fields_, args))
        for name, value in kwargs.items():
            if name not in self._named_fields_:
                raise TypeError(
                    f"{self.__class__.__name__}() got an unexpected keyword argument {name!r}"
                )

            if name in values:
                raise TypeError(
                    f"{self.__class__.__name__}() got multiple values for argument {name!r}"
                )

            values[name] = value

        for name in self._named_fields_:
            setattr(self, name, values.get(name, 0))

        for name in self._layout_:
            if name.startswith("_"):
                setattr(self, f"_f_{name}", 0)

    @classmethod
    def from_bits(cls, value: bits) -> Self:
        cls._check_bits_("initialization", cls._size_bits_, value)
        self = object.__new__(cls)
        for name, (offset, width) in cls._layout_.items():
            field_value = int(value[offset : offset + width])
            if name.startswith("_"):
                setattr(self, f"_f_{name}", field_value)
            else:
                setattr(self, name, field_value)

        return self

    def to_bits(self) -> bits:
        value = 0
        for name, (offset, _width) in self._layout_.items():
            value |= int(getattr(self, f"_f_{name}")) << offset

        return bits(value, self._size_bits_)

    @classmethod
    def from_bytes(cls, value: bytes | bytearray | memoryview) -> Self:
        cls._check_bytes_("initialization", cls._size_bytes_, value)
        return cls.from_bits(bits(value, cls._size_bits_))

    from_bytearray = from_bytes

    @classmethod
    def from_int(cls, value: int) -> Self:
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
        names = self._named_fields_ if omit_padding else self._layout_

        for name in names:
            _offset, width = self._layout_[name]
            value = getattr(self, f"_f_{name}")
            if omit_zero and value == 0:
                continue

            fields.append(f"{name}={value:0{width}b}")

        return " ".join(fields)

    def __repr__(self) -> str:
        return f"<{self.__module__}.{self.__class__.__name__} {self.bits_repr()}>"

    def __eq__(self, other: Self) -> bool:
        return isinstance(other, self.__class__) and self.to_bits() == other.to_bits()
