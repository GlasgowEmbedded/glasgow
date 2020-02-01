from nmigen import *
from nmigen.lib.io import Pin
from nmigen.compat.fhdl.specials import TSTriple


__all__ = ['Pads']


class Pads(Elaboratable):
    """
    Pad adapter.

    Provides a common interface to device pads, wrapping either a Migen platform request,
    or a Glasgow I/O port slice.

    Construct a pad adapter providing signals, records, or tristate triples; name may
    be specified explicitly with keyword arguments. For each signal, record field, or
    triple with name ``n``, the pad adapter will have an attribute ``n_t`` containing
    a tristate triple. ``None`` may also be provided, and is ignored; no attribute
    is added to the adapter.

    For example, if a Migen platform file contains the definitions ::

        _io = [
            ("i2c", 0,
                Subsignal("scl", Pins("39")),
                Subsignal("sda", Pins("40")),
            ),
            # ...
        ]

    then a pad adapter constructed as ``Pads(platform.request("i2c"))`` will have
    attributes ``scl_t`` and ``sda_t`` containing tristate triples for their respective
    pins.

    If a Glasgow applet contains the code ::

        port = target.get_port(args.port)
        pads = Pads(tx=port[args.pin_tx], rx=port[args.pin_rx])
        target.submodules += pads

    then the pad adapter ``pads`` will have attributes ``tx_t`` and ``rx_t`` containing
    tristate triples for their respective pins; since Glasgow I/O ports return tristate
    triples when slicing, the results of slicing are unchanged.
    """
    def __init__(self, *args, **kwargs):
        self._tristates = []
        for (i, elem) in enumerate(args):
            self._add_elem(elem, index=i)
        for name, elem in kwargs.items():
            self._add_elem(elem, name)

    def _add_elem(self, elem, name=None, index=None):
        if elem is None:
            return
        elif isinstance(elem, Record):
            for field in elem.layout:
                if name is None:
                    field_name = field[0]
                else:
                    field_name = "{}_{}".format(name, field[0])
                self._add_elem(getattr(elem, field[0]), field_name)
            return
        elif isinstance(elem, Signal):
            triple = TSTriple()
            self._tristates.append(triple.get_tristate(elem))
            if name is None:
                name = elem.name
        elif isinstance(elem, (Pin, TSTriple)):
            triple = elem
        else:
            assert False

        if name is None and index is None:
            raise ValueError("Name must be provided for {!r}".format(elem))
        elif name is None:
            raise ValueError("Name must be provided for {!r} (argument {})"
                             .format(elem, index + 1))

        triple_name = "{}_t".format(name)
        if hasattr(self, triple_name):
            raise ValueError("Cannot add {!r} as attribute {}; attribute already exists")

        setattr(self, triple_name, triple)

    def elaborate(self, platform):
        m = Module()
        m.submodules += self._tristates
        return m

# -------------------------------------------------------------------------------------------------

import unittest


class PadsTestCase(unittest.TestCase):
    def assertIsTriple(self, obj):
        self.assertIsInstance(obj, TSTriple)

    def assertHasTristate(self, frag, sig):
        for tristate in frag._tristates:
            if tristate.target is sig:
                return
        self.fail("No tristate for {!r} in {!r}".format(sig, frag))

    def test_none(self):
        pads = Pads(x=None)

        self.assertFalse(hasattr(pads, "x_t"))

    def test_signal(self):
        sig  = Signal()
        pads = Pads(sig)

        self.assertIsTriple(pads.sig_t)
        self.assertHasTristate(pads, sig)

    def test_signal_named(self):
        sig  = Signal()
        pads = Pads(rx=sig)

        self.assertIsTriple(pads.rx_t)
        self.assertHasTristate(pads, sig)

    def test_triple(self):
        tri  = TSTriple()
        pads = Pads(sig=tri)

        self.assertIsTriple(pads.sig_t)
        self.assertEqual(pads.sig_t, tri)

    def test_triple_unnamed(self):
        tri  = TSTriple()
        self.assertRaises(ValueError, Pads, tri)

    def test_record(self):
        rec  = Record([("rx", 1), ("tx", 1)])
        pads = Pads(rec)

        self.assertIsTriple(pads.rx_t)
        self.assertHasTristate(pads, rec.rx)
        self.assertIsTriple(pads.tx_t)
        self.assertHasTristate(pads, rec.tx)

    def test_record_named(self):
        rec  = Record([("rx", 1), ("tx", 1)])
        pads = Pads(uart=rec)

        self.assertIsTriple(pads.uart_rx_t)
        self.assertHasTristate(pads, rec.rx)
        self.assertIsTriple(pads.uart_tx_t)
        self.assertHasTristate(pads, rec.tx)
