from migen.build.generic_platform import *
from migen.build.lattice import LatticePlatform

from .programmer import GlasgowProgrammer


__all__ = ["GlasgowPlatformRevC1"]


_io = [
    ("clk_fx", 0, Pins("L5")),
    ("clk_if", 0, Pins("K6")),

    ("fx2", 0,
        Subsignal("sloe",    Pins("L3")),
        Subsignal("slrd",    Pins("J5")),
        Subsignal("slwr",    Pins("J4")),
        Subsignal("pktend",  Pins("L1")),
        Subsignal("fifoadr", Pins("K3 L2")),
        Subsignal("flag",    Pins("L7 K5 L4 J3")),
        Subsignal("fd",      Pins("H7 J7 J9 K10 L10 K9 L8 K7")),
    ),

    ("i2c", 0,
        Subsignal("scl", Pins("H9")),
        Subsignal("sda", Pins("J8")),
    ),

    ("alert_n", 0, Pins("K4")),

    ("user_led", 0, Pins("G9")),
    ("user_led", 1, Pins("G8")),
    ("user_led", 2, Pins("E9")),
    ("user_led", 3, Pins("D9")),
    ("user_led", 4, Pins("E8")),

    ("port_a", 0, Subsignal("io", Pins("A1")),  Subsignal("oe", Pins("C7"))),
    ("port_a", 1, Subsignal("io", Pins("A2")),  Subsignal("oe", Pins("C8"))),
    ("port_a", 2, Subsignal("io", Pins("B3")),  Subsignal("oe", Pins("D7"))),
    ("port_a", 3, Subsignal("io", Pins("A3")),  Subsignal("oe", Pins("A7"))),
    ("port_a", 4, Subsignal("io", Pins("B6")),  Subsignal("oe", Pins("B8"))),
    ("port_a", 5, Subsignal("io", Pins("A4")),  Subsignal("oe", Pins("A8"))),
    ("port_a", 6, Subsignal("io", Pins("B7")),  Subsignal("oe", Pins("B9"))),
    ("port_a", 7, Subsignal("io", Pins("A5")),  Subsignal("oe", Pins("A9"))),

    ("port_b", 0, Subsignal("io", Pins("B11")), Subsignal("oe", Pins("F9"))),
    ("port_b", 1, Subsignal("io", Pins("C11")), Subsignal("oe", Pins("G11"))),
    ("port_b", 2, Subsignal("io", Pins("D10")), Subsignal("oe", Pins("G10"))),
    ("port_b", 3, Subsignal("io", Pins("D11")), Subsignal("oe", Pins("H11"))),
    ("port_b", 4, Subsignal("io", Pins("E10")), Subsignal("oe", Pins("H10"))),
    ("port_b", 5, Subsignal("io", Pins("E11")), Subsignal("oe", Pins("J11"))),
    ("port_b", 6, Subsignal("io", Pins("F11")), Subsignal("oe", Pins("J10"))),
    ("port_b", 7, Subsignal("io", Pins("F10")), Subsignal("oe", Pins("K11"))),

    ("port_s", 0, Subsignal("io", Pins("A11")), Subsignal("oe", Pins("B4"))),

    ("aux", 0, Pins("A10")),
    ("aux", 1, Pins("C9")),

    # On revC0, these balls are shared with B6 and B7, respectively.
    # Since the default pin state is a weak pullup, we need to tristate them explicitly.
    ("unused", 0, Pins("A6 B5")),
]

_connectors = [
]


class GlasgowPlatformRevC1(LatticePlatform):
    default_clk_name = "clk_if"
    default_clk_period = 1e9 / 48e6

    def __init__(self):
        LatticePlatform.__init__(self, "ice40-hx8k-bg121", _io, _connectors,
                                 toolchain="icestorm")

    def create_programmer(self):
        return GlasgowProgrammer()
