__all__ = ["lazy"]


class lazy:
    """
    A wrapper for lazily evaluating an expression.

    E.g. ``obj = slow_operation()`` can generally be replaced with
    ``obj = lazy(lambda: slow_operation())``, which would only perform ``slow_operation()`` when
    its result is actually requested.
    """

    __slots__ = ["_object_", "_thunk_"]

    def __init__(self, thunk):
        self.__class__.__dict__["_object_"].__set__(self, None)
        self.__class__.__dict__["_thunk_" ].__set__(self, thunk)

    def _force_(self):
        if self._thunk_:
            self.__class__.__dict__["_object_"].__set__(self, self._thunk_())
            self.__class__.__dict__["_thunk_" ].__set__(self, None)

    def __getattr__(self, attr):
        self._force_()
        return getattr(self._object_, attr)

    def __setattr__(self, attr, value):
        self._force_()
        setattr(self._object_, attr, value)

    def __delattr__(self, attr):
        self._force_()
        delattr(self._object_, attr)

    def __bool__(self):
        self._force_()
        if self._object_:
            return True
        else:
            return False

    def __repr__(self):
        if self._thunk_:
            rep = repr(self._thunk_)
        else:
            rep = repr(self._object_)
        return f"<lazy {rep}>"


def define_specials():
    def define_special(name):
        def forward(self, *args, **kwargs):
            self._force_()
            return getattr(self._object_, name)(*args, **kwargs)
        forward.__name__ = name
        setattr(lazy, name, forward)

    # See https://docs.python.org/3/reference/datamodel.html#special-lookup
    # Note that the loop body has to be in a separate function because of local variable scoping.
    for name in [
        "__str__", "__bytes__", "__format__", "__lt__", "__le__", "__eq__", "__ne__", "__gt__",
        "__ge__", "__hash__", "__dir__", "__call__", "__len__", "__length_hint__",
        "__getitem__", "__setitem__", "__delitem__", "__iter__", "__reversed__", "__contains__",
        "__add__", "__sub__", "__mul__", "__matmul__", "__truediv__", "__floordiv__", "__mod__",
        "__divmod__", "__pow__", "__lshift__", "__rshift__", "__and__", "__xor__", "__or__",
        "__radd__", "__rsub__", "__rmul__", "__rmatmul__", "__rtruediv__", "__rfloordiv__", "__rmod__",
        "__rdivmod__", "__rpow__", "__rlshift__", "__rrshift__", "__rand__", "__rxor__", "__ror__",
        "__iadd__", "__isub__", "__imul__", "__imatmul__", "__itruediv__", "__ifloordiv__", "__imod__",
        "__ipow__", "__ilshift__", "__irshift__", "__iand__", "__ixor__", "__ior__", "__neg__",
        "__pos__", "__abs__", "__invert__", "__complex__", "__int__", "__float__", "__index__",
        "__round__", "__trunc__", "__floor__", "__ceil__", "__enter__", "__exit__", "__await__",
        "__aiter__", "__anext__", "__aenter__", "__aexit__"
    ]:
        define_special(name)


define_specials()
del define_specials
