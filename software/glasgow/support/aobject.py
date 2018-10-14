__all__ = ["aobject"]


class aobject(object):
    """
    Base class for objects with an async ``__init__`` method.

    Creating an instance of ``aobject`` requires awaiting, e.g. ``await aobject()``.
    """
    async def __new__(cls, *a, **kw):
        instance = super().__new__(cls)
        await instance.__init__(*a, **kw)
        return instance

    async def __init__(self):
        pass
