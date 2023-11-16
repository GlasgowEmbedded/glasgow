from amaranth import *
from amaranth.lib.io import Pin


__all__ = ['Pads']


class Pads(Elaboratable):
    """
    Pad adapter.

    Provides a common interface to device pads, wrapping either a Migen platform request,
    or a Glasgow I/O port slice.

    Construct a pad adapter providing pins; name may
    be specified explicitly with keyword arguments. For each
    pin with name ``n``, the pad adapter will have an attribute ``n_t`` containing
    a ``Pin``.

    For example, if a Migen platform file contains the definitions ::

        _io = [
            ("i2c", 0,
                Subsignal("scl", Pins("39")),
                Subsignal("sda", Pins("40")),
            ),
            # ...
        ]

    then a pad adapter constructed as ``Pads(platform.request("i2c"))`` will have
    attributes ``scl_t`` and ``sda_t`` containing ``Pin`` objects for their respective
    pins.
    """
    def __init__(self, **kwargs):
        for name, pin in kwargs.items():
            assert isinstance(pin, Pin)

            pin_name = f"{name}_t"
            if hasattr(self, pin_name):
                raise ValueError("Cannot add {!r} as attribute {}; attribute already exists")

            setattr(self, pin_name, pin)

    def elaborate(self, platform):
        m = Module()
        return m
