from amaranth.lib import io


__all__ = ["PortGroup"]


class PortGroup:
    """Group of Amaranth library I/O ports.

    This object is a stand-in for the object returned by the Amaranth :py:`platform.request()`
    function, as expected by the I/O cores.
    """
    def __init__(self, **kwargs):
        for name, port in kwargs.items():
            setattr(self, name, port)

    def __getitem__(self, key):
        return self.__dict__[key]

    def __setattr__(self, name, value):
        if not name.startswith("_"):
            assert value is None or isinstance(value, io.PortLike)
        object.__setattr__(self, name, value)
