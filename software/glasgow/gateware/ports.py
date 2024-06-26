from amaranth.lib import io


__all__ = ["PortGroup"]


class PortGroup:
    """Group of Amaranth library I/O ports.

    This object is a stand-in for the object returned by the Amaranth :py:`platform.request()`
    function, as expected by the I/O cores.
    """
    def __init__(self, **kwargs):
        for name, port in kwargs.items():
            assert port is None or isinstance(port, io.PortLike)
        self.__dict__.update(kwargs)
