from amaranth import *
from amaranth.lib import io


__all__ = ['Pads']


class Pads:
    """Deprecated in favor of :class:`glasgow.gateware.ports.PortGroup`."""
    def __init__(self, **kwargs):
        for name, pin in kwargs.items():
            if hasattr(pin, "signature"):
                assert isinstance(pin.signature, io.Buffer.Signature)
            else:
                assert isinstance(pin, io.Pin)

            pin_name = f"{name}_t"
            if hasattr(self, pin_name):
                raise ValueError("Cannot add {!r} as attribute {}; attribute already exists")

            setattr(self, pin_name, pin)
